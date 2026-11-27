"""Synthetic regressions for decrypt_all_dbs: a failed refresh must never cost the old copy.

Every source here is a fake SQLCipher-style file built from a tiny SQLite database;
no real WeChat database, key, configuration or vault path is read or written.
"""

from __future__ import annotations

from Crypto.Cipher import AES
from contextlib import redirect_stderr, redirect_stdout
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import decrypt_all_dbs as decrypt
import vault_cli

ARTIFACT_ROOT = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-decrypt-tests-")).resolve()

# WeChat 4.x page layout, kept independent of the production constants.
PAGE = 4096
RESERVE = 80
KEY_A = hashlib.sha256(b"fixture-key-a").digest()
KEY_B = hashlib.sha256(b"fixture-key-b").digest()
WRONG_KEY = hashlib.sha256(b"fixture-wrong-key").digest()


def plain_database(path: Path, body: str) -> bytes:
    """Build a tiny WAL-mode SQLite file laid out like a decrypted SQLCipher database.

    SQLCipher keeps the last 80 bytes of every page for IV + HMAC, so SQLite must see
    them as reserved space: move each leaf page's cells below that tail and set the
    header's reserved-space byte. The result is checked with integrity_check.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA page_size = 4096")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY, body TEXT)")
        con.execute("INSERT INTO fixture(body) VALUES (?)", (body,))
        con.commit()
    finally:
        con.close()
    data = bytearray(path.read_bytes())
    assert struct.unpack_from(">H", data, 16)[0] == PAGE and data[20] == 0
    for number in range(len(data) // PAGE):
        base = number * PAGE
        header = base + (100 if number == 0 else 0)
        assert data[header] == 0x0D, "fixture expects table leaf pages only"
        assert struct.unpack_from(">H", data, header + 1)[0] == 0, "fixture expects no freeblocks"
        cells, start = struct.unpack_from(">HH", data, header + 3)
        assert start - RESERVE >= header - base + 8 + 2 * cells
        data[base + start - RESERVE : base + PAGE - RESERVE] = data[base + start : base + PAGE]
        data[base + PAGE - RESERVE : base + PAGE] = bytes(RESERVE)
        struct.pack_into(">H", data, header + 5, start - RESERVE)
        for index in range(cells):
            pointer = header + 8 + 2 * index
            struct.pack_into(">H", data, pointer, struct.unpack_from(">H", data, pointer)[0] - RESERVE)
    data[20] = RESERVE
    path.write_bytes(data)
    assert read_bodies(path) == [body]
    con = sqlite3.connect(f"{path.as_uri()}?immutable=1", uri=True)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
    return bytes(data)


def encrypt_like_wechat(plain: bytes, key: bytes) -> bytes:
    """Salt on page 1, AES-256-CBC body, then IV and HMAC filler in each page tail."""
    out = bytearray()
    for number in range(len(plain) // PAGE):
        page = plain[number * PAGE : (number + 1) * PAGE]
        start = 16 if number == 0 else 0
        iv = hashlib.md5(b"iv" + key + bytes([number])).digest()
        out += b"S" * start
        out += AES.new(key, AES.MODE_CBC, iv).encrypt(page[start : PAGE - RESERVE])
        out += iv + bytes(RESERVE - len(iv))
    return bytes(out)


def read_bodies(path: Path) -> list[str]:
    con = sqlite3.connect(f"{path.as_uri()}?immutable=1", uri=True)
    try:
        return [row[0] for row in con.execute("SELECT body FROM fixture ORDER BY id")]
    finally:
        con.close()


def tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class DecryptAllDbsTests(unittest.TestCase):
    def setUp(self):
        self.root = ARTIFACT_ROOT / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.root.mkdir(mode=0o700, parents=True)
        self.db_base = self.root / "source/db_storage"
        self.vault = self.root / "vault"
        self.out = self.vault / "decrypted/current"
        self.config_file = self.root / "config/wechat-local-vault.json"
        self.keys_file = self.root / "config/wechat-keys.json"
        self.state_file = self.vault / "state/decrypt_state.json"
        self.config_file.parent.mkdir(parents=True)
        self.config_file.write_text(json.dumps({"db_base_path": str(self.db_base)}))
        self.set_keys(contact=KEY_A, session=KEY_B)
        self.writes = 0
        for name, value in {
            "CONFIG_FILE": self.config_file,
            "KEYS_FILE": self.keys_file,
            "DEFAULT_VAULT_DIR": self.vault,
            "DEFAULT_OUTPUT_DIR": self.out,
            "DECRYPT_STATE_FILE": self.state_file,
        }.items():
            patcher = mock.patch.object(decrypt, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_keys(self, **keys: bytes) -> None:
        data = {name: key.hex() for name, key in keys.items()}
        data["__meta"] = "not a database key"
        self.keys_file.write_text(json.dumps(data))

    def write_source(self, rel: str, key: bytes, body: str) -> None:
        self.writes += 1
        plain = plain_database(self.root / f"plain/{self.writes}.db", body)
        src = self.db_base / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(encrypt_like_wechat(plain, key))
        stamp = 1_800_000_000_000_000_000 + self.writes * 1_000_000_000
        os.utime(src, ns=(stamp, stamp))

    def seed(self) -> None:
        self.write_source("contact/contact.db", KEY_A, "contact v1")
        self.write_source("session/session.db", KEY_B, "session v1")
        self.assertEqual(self.run_main()[0], 0)

    def run_main(self, *extra: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = decrypt.main(["--mode", "incremental", "-o", str(self.out), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def manifest(self) -> dict:
        paths = (self.vault / "manifests").glob("decrypt-*.json")
        latest = max(paths, key=lambda path: (path.stat().st_mtime_ns, path.name))
        return json.loads(latest.read_text())

    def records(self) -> dict[str, dict]:
        return {item["rel"]: item for item in self.manifest()["records"]}

    def bodies(self, rel: str) -> list[str]:
        return read_bodies(self.out / rel)

    def leftovers(self) -> list[str]:
        """Temp files or SQLite sidecars left in the output tree."""
        return sorted(
            str(path.relative_to(self.out))
            for path in self.out.rglob("*")
            if path.is_file() and not path.name.endswith(".db")
        )

    def deny(self, rel: str) -> None:
        if os.geteuid() == 0:
            self.skipTest("file permissions do not stop root")
        src = self.db_base / rel
        src.chmod(0)
        self.addCleanup(src.chmod, 0o600)

    def sandbox_reads(self):
        """Mimic the sandbox: stat() works, but opening a source raises Errno 1."""
        real_open = Path.open
        db_base = self.db_base

        def guarded(path, *args, **kwargs):
            if db_base in path.absolute().parents:
                raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(path))
            return real_open(path, *args, **kwargs)

        return mock.patch.object(Path, "open", guarded)

    def test_decrypt_db_reproduces_the_plain_pages(self):
        plain = plain_database(self.root / "plain.db", "round trip")
        src = self.root / "cipher.db"
        src.write_bytes(encrypt_like_wechat(plain, KEY_A))
        out = self.root / "decrypted.db"
        decrypt.decrypt_db(src, out, KEY_A.hex())
        self.assertEqual(out.read_bytes(), plain)

    def test_refresh_swaps_in_new_copy_without_leftovers(self):
        self.seed()
        manifest = self.manifest()
        self.assertFalse(manifest["aborted"])
        self.assertEqual(manifest["stale_databases"], [])
        self.assertEqual({item["status"] for item in manifest["records"]}, {"ok"})
        self.assertEqual(self.bodies("contact/contact.db"), ["contact v1"])

        self.write_source("contact/contact.db", KEY_A, "contact v2")
        code, out, _ = self.run_main()

        self.assertEqual(code, 0)
        self.assertEqual(self.bodies("contact/contact.db"), ["contact v2"])
        records = self.records()
        self.assertEqual(records["contact/contact.db"]["status"], "ok")
        self.assertEqual(records["session/session.db"]["status"], "unchanged")
        self.assertNotIn("Stale:", out)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(stat.S_IMODE((self.out / "contact/contact.db").stat().st_mode), 0o600)

    def test_unreadable_source_keeps_previous_copy_and_marks_it_stale(self):
        self.seed()
        before = (self.out / "contact/contact.db").read_bytes()
        state_before = json.loads(self.state_file.read_text())["contact/contact.db"]

        self.write_source("contact/contact.db", KEY_A, "contact v2")
        self.write_source("session/session.db", KEY_B, "session v2")
        self.deny("contact/contact.db")
        code, out, _ = self.run_main()

        self.assertEqual(code, 0)  # session is still readable, so no abort
        self.assertEqual((self.out / "contact/contact.db").read_bytes(), before)
        self.assertEqual(self.bodies("session/session.db"), ["session v2"])
        record = self.records()["contact/contact.db"]
        self.assertEqual(record["status"], "miss")
        self.assertIn("Permission denied", record["reason"])
        self.assertTrue(record["kept_previous_copy"])
        self.assertTrue(record["stale"])
        self.assertIn("previous_copy_mtime", record)
        self.assertEqual(self.manifest()["stale_databases"], ["contact/contact.db"])
        self.assertIn("kept previous copy, now stale", out)
        self.assertIn("Stale: 1 previous copies kept but not refreshed: contact/contact.db", out)
        self.assertEqual(json.loads(self.state_file.read_text())["contact/contact.db"], state_before)
        self.assertEqual(self.leftovers(), [])

        # Once the source is readable again, the next incremental run refreshes it.
        (self.db_base / "contact/contact.db").chmod(0o600)
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.bodies("contact/contact.db"), ["contact v2"])
        self.assertEqual(self.records()["contact/contact.db"]["status"], "ok")

    def test_bad_decryption_keeps_previous_copy(self):
        self.seed()
        before = (self.out / "contact/contact.db").read_bytes()

        self.set_keys(contact=WRONG_KEY, session=KEY_B)
        self.assertEqual(self.run_main()[0], 0)

        self.assertEqual((self.out / "contact/contact.db").read_bytes(), before)
        record = self.records()["contact/contact.db"]
        self.assertEqual(record["status"], "miss")
        self.assertIn("not a database", record["reason"])
        self.assertTrue(record["kept_previous_copy"])
        self.assertTrue(record["stale"])
        self.assertEqual(self.leftovers(), [])

    def test_first_failure_reports_that_no_copy_exists(self):
        self.write_source("contact/contact.db", WRONG_KEY, "contact v1")
        self.write_source("session/session.db", KEY_B, "session v1")

        self.assertEqual(self.run_main()[0], 0)

        record = self.records()["contact/contact.db"]
        self.assertEqual(record["status"], "miss")
        self.assertFalse(record["kept_previous_copy"])
        self.assertFalse(record["stale"])
        self.assertNotIn("previous_copy_mtime", record)
        self.assertFalse((self.out / "contact/contact.db").exists())
        self.assertEqual(self.manifest()["stale_databases"], [])
        self.assertEqual(self.leftovers(), [])

    def test_write_or_replace_failure_removes_only_the_temp_file(self):
        self.seed()
        before = (self.out / "contact/contact.db").read_bytes()

        def disk_full(src, dst, key_hex):
            dst.write_bytes(b"partial page")
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

        failures = {
            "write": mock.patch.object(decrypt, "decrypt_db", side_effect=disk_full),
            "replace": mock.patch.object(decrypt.os, "replace", side_effect=OSError(errno.EIO, "replace failed")),
        }
        for label, failure in failures.items():
            with self.subTest(label):
                self.write_source("contact/contact.db", KEY_A, f"contact {label}")
                with failure:
                    self.assertEqual(self.run_main()[0], 0)
                self.assertEqual((self.out / "contact/contact.db").read_bytes(), before)
                record = self.records()["contact/contact.db"]
                self.assertEqual(record["status"], "miss")
                self.assertTrue(record["kept_previous_copy"])
                self.assertEqual(self.leftovers(), [])

    def test_sandboxed_run_aborts_and_keeps_every_copy(self):
        """Regression for the 2026-10-09 22:10 sandboxed run that deleted 14 copies.

        In the sandbox stat() works but every read fails with Errno 1; the old loop
        treated each changed source as a failure and unlinked its decrypted copy.
        """
        self.seed()
        outputs = tree_digest(self.out)
        state, config = self.state_file.read_bytes(), self.config_file.read_bytes()

        self.write_source("contact/contact.db", KEY_A, "contact v2")  # session stays unchanged
        with self.sandbox_reads():
            code, out, err = self.run_main("--clean")

        self.assertEqual(code, decrypt.ABORT_EXIT_CODE)
        self.assertIn("[Errno 1] Operation not permitted", err)
        self.assertIn("outside the sandbox", err)
        self.assertIn("Aborted: 0 decrypted", out)
        self.assertEqual(tree_digest(self.out), outputs)  # --clean never ran
        self.assertEqual(self.state_file.read_bytes(), state)
        self.assertEqual(self.config_file.read_bytes(), config)
        manifest = self.manifest()
        self.assertTrue(manifest["aborted"])
        self.assertIn("source unreadable [Errno 1]", manifest["abort_reason"])
        self.assertEqual(manifest["database_count"], 0)
        self.assertEqual(manifest["stale_databases"], ["contact/contact.db", "session/session.db"])
        for record in manifest["records"]:
            self.assertEqual(record["status"], "miss")
            self.assertTrue(record["kept_previous_copy"])
            self.assertTrue(record["stale"])

    def test_permission_denied_on_every_source_also_aborts(self):
        self.seed()
        outputs = tree_digest(self.out)

        self.write_source("contact/contact.db", KEY_A, "contact v2")
        self.deny("contact/contact.db")
        self.deny("session/session.db")
        code, _, err = self.run_main()

        self.assertEqual(code, decrypt.ABORT_EXIT_CODE)
        self.assertIn("Permission denied", err)
        self.assertEqual(tree_digest(self.out), outputs)
        self.assertTrue(self.manifest()["aborted"])

    def test_missing_sources_are_skipped_not_aborted(self):
        code, _, err = self.run_main()

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        manifest = self.manifest()
        self.assertFalse(manifest["aborted"])
        self.assertEqual({item["status"] for item in manifest["records"]}, {"skip"})

    def use_account_folder(self) -> str:
        """Lay sources out as WeChat does: xwechat_files/<wxid>/db_storage."""
        wxid = "wxid_fixtureowner_1a2b"
        self.db_base = self.root / "xwechat_files" / wxid / "db_storage"
        self.config_file.write_text(json.dumps({"db_base_path": str(self.db_base), "wxid": wxid}))
        return wxid

    def test_logs_hide_the_account_folder_but_still_read_from_it(self):
        wxid = self.use_account_folder()
        self.write_source("contact/contact.db", KEY_A, "contact v1")
        self.write_source("session/session.db", KEY_B, "session v1")
        code, out, err = self.run_main()

        self.assertEqual(code, 0)
        self.assertEqual(self.bodies("contact/contact.db"), ["contact v1"])
        self.assertIn(f"DB base: {self.root / 'xwechat_files' / decrypt.ACCOUNT_PLACEHOLDER / 'db_storage'}\n", out)
        self.assertNotIn(wxid.rsplit("_", 1)[0], out + err)

    def test_unreadable_source_error_hides_the_account_folder(self):
        wxid = self.use_account_folder()
        self.write_source("contact/contact.db", KEY_A, "contact v1")
        self.write_source("session/session.db", KEY_B, "session v1")
        self.deny("contact/contact.db")
        code, out, _ = self.run_main()

        self.assertEqual(code, 0)  # session is still readable, so no abort
        reason = self.records()["contact/contact.db"]["reason"]
        self.assertIn("Permission denied", reason)
        self.assertIn(f"xwechat_files/{decrypt.ACCOUNT_PLACEHOLDER}/db_storage/contact/contact.db", reason)
        self.assertIn("MISS contact", out)
        for text in (out, json.dumps(self.manifest(), ensure_ascii=False)):
            self.assertNotIn(wxid.rsplit("_", 1)[0], text)

    def test_folders_named_after_the_configured_wxid_are_hidden(self):
        self.config_file.write_text(json.dumps({"wxid": "custom_owner_9f3e"}))
        hidden = decrypt.ACCOUNT_PLACEHOLDER
        for path, expected in [
            ("/backup/custom_owner_9f3e/copy", f"/backup/{hidden}/copy"),
            ("/backup/custom_owner/copy", f"/backup/{hidden}/copy"),
            ("/x/xwechat_files/renamed/db_storage", f"/x/xwechat_files/{hidden}/db_storage"),
            ("/plain/source", "/plain/source"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(decrypt.public_db_base(Path(path)), expected)
                self.assertEqual(decrypt.hide_account(f"open '{path}/a.db' failed", Path(path)), f"open '{expected}/a.db' failed")

    def test_temp_copy_is_invisible_to_vault_cli_message_glob(self):
        self.set_keys(message_0=KEY_A)
        seen = []
        real_check = decrypt.sqlite_table_count

        def spy(path):
            seen.append((path.name, [item.name for item in vault_cli.message_dbs(self.out)]))
            return real_check(path)

        with mock.patch.object(decrypt, "sqlite_table_count", side_effect=spy):
            for version in ("v1", "v2"):
                self.write_source("message/message_0.db", KEY_A, f"message {version}")
                self.assertEqual(self.run_main()[0], 0)

        self.assertEqual([visible for _, visible in seen], [[], ["message_0.db"]])
        for temp_name, _ in seen:
            self.assertTrue(temp_name.startswith(".message_0.db.") and temp_name.endswith(".tmp"))
        self.assertEqual(self.bodies("message/message_0.db"), ["message v2"])
        self.assertEqual(self.leftovers(), [])

    def test_empty_keys_aborts_with_distinct_message_and_keeps_copies(self):
        self.seed()
        outputs = tree_digest(self.out)
        state, config = self.state_file.read_bytes(), self.config_file.read_bytes()

        for payload in ({}, {"__meta": "only metadata"}):
            with self.subTest(payload=payload):
                self.keys_file.write_text(json.dumps(payload))
                code, out, err = self.run_main("--clean")
                self.assertEqual(code, decrypt.NO_KEYS_EXIT_CODE)
                self.assertIn("no database keys", err)
                self.assertIn("Aborted (no keys)", out)
                self.assertNotIn("0 decrypted, 0 failed, 0 skipped", out)
                self.assertEqual(tree_digest(self.out), outputs)
                self.assertEqual(self.state_file.read_bytes(), state)
                self.assertEqual(self.config_file.read_bytes(), config)
                manifest = self.manifest()
                self.assertTrue(manifest["aborted"])
                self.assertEqual(manifest["abort_reason"], "no database keys configured")
                self.assertEqual(manifest["database_count"], 0)

    def test_status_reports_not_ready_when_dir_has_zero_readable_databases(self):
        def run_status(target: Path, fmt: str) -> str:
            stdout = io.StringIO()
            with mock.patch.object(vault_cli, "load_config", return_value={}), redirect_stdout(stdout):
                vault_cli.main(["--decrypted-dir", str(target), "status", "--format", fmt])
            return stdout.getvalue()

        missing_dir = self.root / "missing-vault"
        self.assertIn("状态: 不存在", run_status(missing_dir, "text"))
        missing_json = json.loads(run_status(missing_dir, "json"))
        self.assertFalse(missing_json["exists"])
        self.assertFalse(missing_json["ready"])
        self.assertEqual(missing_json["available_count"], 0)

        empty_dir = self.root / "empty-vault"
        empty_dir.mkdir()
        self.assertIn("状态: 尚未就绪：没有可读数据库", run_status(empty_dir, "text"))
        empty_json = json.loads(run_status(empty_dir, "json"))
        self.assertTrue(empty_json["exists"])
        self.assertFalse(empty_json["ready"])
        self.assertEqual(empty_json["status"], "empty")
        self.assertEqual(empty_json["available_count"], 0)

        corrupt_db = empty_dir / "contact/contact.db"
        corrupt_db.parent.mkdir(parents=True)
        corrupt_db.write_bytes(b"not a valid sqlite database" * 10)
        self.assertIn("状态: 尚未就绪：没有可读数据库", run_status(empty_dir, "text"))
        self.assertFalse(json.loads(run_status(empty_dir, "json"))["ready"])

        self.seed()
        self.assertIn("状态: 可用", run_status(self.out, "text"))
        ready_json = json.loads(run_status(self.out, "json"))
        self.assertTrue(ready_json["ready"])
        self.assertEqual(ready_json["status"], "ready")
        self.assertGreaterEqual(ready_json["available_count"], 2)


if __name__ == "__main__":
    unittest.main()
