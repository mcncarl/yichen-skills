"""Synthetic Windows acquisition/decryption tests. No real process or account."""
from __future__ import annotations

import ctypes as c
import ctypes.util
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import unittest
from contextlib import ExitStack
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import windows_crypto as crypto
import windows_live as live
import windows_keyscan as keyscan
import windows_wal as wal
import snapshot_reader as reader
from fixture_factory import build


ARTIFACTS = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT", Path.cwd() / "work/windows-live-tests")) / uuid.uuid4().hex
KEY = hashlib.sha256(b"synthetic-test-key-not-a-user-key").digest()
SALT = hashlib.md5(b"synthetic-database-salt").digest()


class TestAES:
    def __init__(self, key):
        self.key = key
        self.native = crypto.CngAES(key) if sys.platform == "win32" else None

    def decrypt(self, iv, data):
        if self.native:
            return self.native.decrypt(iv, data)
        from Crypto.Cipher import AES
        return AES.new(self.key, AES.MODE_CBC, iv).decrypt(data)

    def encrypt(self, iv, data):
        if self.native:
            from ctypes import wintypes as w
            api = self.native.api.BCryptEncrypt
            api.argtypes = self.native.api.BCryptDecrypt.argtypes
            api.restype = w.LONG
            source, vector, output = c.create_string_buffer(data, len(data)), c.create_string_buffer(iv, 16), c.create_string_buffer(len(data))
            written = w.ULONG()
            crypto.CngAES._check(api(self.native.key, source, len(data), None, vector, 16, output, len(data), c.byref(written), 0))
            if written.value != len(data):
                raise ValueError("Incomplete synthetic encryption")
            return output.raw
        from Crypto.Cipher import AES
        return AES.new(self.key, AES.MODE_CBC, iv).encrypt(data)

    def close(self):
        if self.native:
            self.native.close()


def reserve_database(path):
    """Use SQLite's public file-control API to reserve the real 80-byte trailer."""
    if sys.platform == "win32":
        candidates = [
            Path(sys.executable).parent / "sqlite3.dll",
            Path(sys.executable).parent / "DLLs" / "sqlite3.dll",
            Path(sys.base_prefix) / "DLLs" / "sqlite3.dll",
            Path(sys.base_prefix) / "sqlite3.dll",
        ]
        library = next((str(p) for p in candidates if p.is_file()), None) or ctypes.util.find_library("sqlite3")
    else:
        library = ctypes.util.find_library("sqlite3")
    if not library:
        raise RuntimeError("sqlite3 shared library not found")
    api = c.CDLL(library)
    api.sqlite3_open.argtypes = [c.c_char_p, c.POINTER(c.c_void_p)]
    api.sqlite3_file_control.argtypes = [c.c_void_p, c.c_char_p, c.c_int, c.c_void_p]
    api.sqlite3_exec.argtypes = [c.c_void_p, c.c_char_p, c.c_void_p, c.c_void_p, c.c_void_p]
    api.sqlite3_close.argtypes = [c.c_void_p]
    handle, reserve = c.c_void_p(), c.c_int(80)
    if api.sqlite3_open(str(path).encode("utf-8"), c.byref(handle)):
        raise RuntimeError("Synthetic SQLite fixture open failed")
    try:
        if api.sqlite3_exec(handle, b"PRAGMA page_size=4096; PRAGMA schema_version;", None, None, None):
            raise RuntimeError("Synthetic fixture schema load failed")
        if api.sqlite3_file_control(handle, b"main", 38, c.byref(reserve)):
            raise RuntimeError("SQLite reserve file-control unavailable")
        if api.sqlite3_exec(handle, b"VACUUM;", None, None, None):
            raise RuntimeError("Synthetic fixture VACUUM failed")
    finally:
        api.sqlite3_close(handle)


def encrypt_database(data):
    cipher, output = TestAES(KEY), bytearray()
    authentication_key = crypto.mac_key(KEY, SALT)
    try:
        for index in range(len(data) // crypto.PAGE):
            page = data[index * crypto.PAGE:(index + 1) * crypto.PAGE]
            start = 16 if index == 0 else 0
            iv = hashlib.md5(struct.pack("<I", index + 1)).digest()
            payload = cipher.encrypt(iv, page[start:4016]) + iv
            signature = hmac.new(authentication_key, payload + struct.pack("<I", index + 1), hashlib.sha512).digest()
            output.extend((SALT if index == 0 else b"") + payload + signature)
    finally:
        cipher.close()
    return bytes(output)


def wal_bytes(frames, *, byteorder="<", stale=False):
    generation = b"12345678"
    header = struct.pack(">IIII", 0x377F0682 if byteorder == "<" else 0x377F0683, 3007000, 4096, 0) + generation
    state = wal._checksum(header, byteorder)
    output = bytearray(header + struct.pack(">II", *state))
    for number, commit, page in frames:
        beginning = struct.pack(">II", number, commit)
        state = wal._checksum(beginning + page, byteorder, state)
        output.extend(beginning + (b"old-salt" if stale else generation) + struct.pack(">II", *state) + page)
    return bytes(output)


class WindowsLiveTests(unittest.TestCase):
    def setUp(self):
        self.root = (ARTIFACTS / uuid.uuid4().hex).resolve()
        self.root.mkdir(parents=True)

    def test_known_aes256_cbc_vector(self):
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        cipher = TestAES(key)
        try:
            self.assertEqual(cipher.decrypt(iv, bytes.fromhex("f58c4c04d6e5f1ba779eabfb5f7bfbd6")), bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"))
        finally:
            cipher.close()

    def test_known_aes128_ecb_vector(self):
        # FIPS-197 Appendix C.1 AES-128 known answer test.
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        expected = bytes.fromhex("00112233445566778899aabbccddeeff")
        if sys.platform == "win32":
            cipher = crypto.CngAES(key, chaining_mode="ChainingModeECB")
            try:
                self.assertEqual(cipher.decrypt(None, ciphertext), expected)
            finally:
                cipher.close()
        else:
            from Crypto.Cipher import AES
            self.assertEqual(AES.new(key, AES.MODE_ECB).decrypt(ciphertext), expected)

    def encrypted_fixture(self):
        path = self.root / "synthetic.db"
        reserve_database(path)
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE messages(body TEXT)")
            con.executemany("INSERT INTO messages VALUES(?)", [("中文测试 " + str(i) + "x" * 200,) for i in range(70)])
        data = path.read_bytes()
        self.assertEqual(data[20], 80)
        return encrypt_database(data)

    def test_every_page_authentication_and_real_sqlite_readback(self):
        encrypted = self.encrypted_fixture()
        self.assertTrue(crypto.verify_enc_key(KEY, encrypted[:4096]))
        output = self.root / "decrypted.db"
        output.write_bytes(crypto.decrypt_pages(encrypted, KEY, aes_factory=TestAES))
        with reader.connect_read_only(output) as con:
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(con.execute("SELECT count(*) FROM messages").fetchone()[0], 70)
        damaged = bytearray(encrypted)
        damaged[4096 + 100] ^= 1
        with self.assertRaisesRegex(ValueError, "authentication"):
            crypto.decrypt_pages(damaged, KEY, aes_factory=TestAES)
        with self.assertRaises(ValueError):
            crypto.decrypt_pages(encrypted, bytes(32), aes_factory=TestAES)
        with self.assertRaises(ValueError):
            crypto.decrypt_pages(encrypted[:-1], KEY, aes_factory=TestAES)

    def test_sqlite_lock_byte_page_passthrough_is_strict(self):
        self.assertEqual(crypto.LOCK_BYTE_PAGE, 262145)
        self.assertEqual((crypto.LOCK_BYTE_PAGE - 1) * crypto.PAGE, 0x40000000)
        self.assertTrue(crypto.is_sqlite_lock_byte_page(bytes(crypto.PAGE), 262145))
        self.assertFalse(crypto.is_sqlite_lock_byte_page(bytes(crypto.PAGE), 262144))
        self.assertFalse(crypto.is_sqlite_lock_byte_page(b"\x01" + bytes(crypto.PAGE - 1), 262145))

        encrypted = self.encrypted_fixture()
        plain = crypto.decrypt_pages(encrypted, KEY, aes_factory=TestAES)
        total_pages = len(encrypted) // crypto.PAGE
        self.assertGreaterEqual(total_pages, 3)

        # Page 3 acts as the SQLite 1 GiB lock-byte page in this synthetic fixture.
        with_zero_lock = bytearray(encrypted)
        with_zero_lock[2 * crypto.PAGE : 3 * crypto.PAGE] = bytes(crypto.PAGE)
        with mock.patch.object(crypto, "LOCK_BYTE_PAGE", 3):
            out = crypto.decrypt_pages(bytes(with_zero_lock), KEY, aes_factory=TestAES)
            self.assertEqual(out[: 2 * crypto.PAGE], plain[: 2 * crypto.PAGE])
            self.assertEqual(out[2 * crypto.PAGE : 3 * crypto.PAGE], bytes(crypto.PAGE))
            self.assertEqual(out[3 * crypto.PAGE :], plain[3 * crypto.PAGE :])

            # A non-zero tampered lock-byte page must still fail HMAC.
            bad_lock = bytearray(with_zero_lock)
            bad_lock[2 * crypto.PAGE] = 1
            with self.assertRaisesRegex(ValueError, "authentication"):
                crypto.decrypt_pages(bytes(bad_lock), KEY, aes_factory=TestAES)

            # An all-zero page at any non-lock-byte position must still fail HMAC.
            zero_other = bytearray(encrypted)
            zero_other[1 * crypto.PAGE : 2 * crypto.PAGE] = bytes(crypto.PAGE)
            with self.assertRaisesRegex(ValueError, "authentication"):
                crypto.decrypt_pages(bytes(zero_other), KEY, aes_factory=TestAES)

    def test_wal_growth_across_lock_byte_page_synthesizes_zero_page_only(self):
        a, b = b"A" * 4096, b"B" * 4096
        with mock.patch.object(wal, "LOCK_BYTE_OFFSET", 4096):
            # lock_byte_page = 4096 // 4096 + 1 = 2; growing 1 -> 3 skips writing page 2 in WAL.
            self.assertEqual(wal.merge_committed_pages(a, wal_bytes([(3, 3, b)])), a + bytes(4096) + b)
            # Skipping a non-lock-byte page (page 3 missing when growing to 4) must still fail.
            with self.assertRaises(ValueError):
                wal.merge_committed_pages(a, wal_bytes([(4, 4, b)]))

    def test_wal_only_committed_pages_both_byte_orders_and_corruption(self):
        a, b, pending = b"A" * 4096, b"B" * 4096, b"P" * 4096
        for order in ("<", ">"):
            log = wal_bytes([(1, 1, b), (1, 0, pending)], byteorder=order)
            self.assertEqual(wal.merge_committed_pages(a, log), b)
            damaged = bytearray(log)
            damaged[100] ^= 1
            with self.assertRaises(ValueError):
                wal.merge_committed_pages(a, damaged)
        self.assertEqual(wal.merge_committed_pages(a, wal_bytes([(1, 1, b)], stale=True)), a)

    def test_wal_growth_truncation_and_unavailable_pages(self):
        a, b = b"A" * 4096, b"B" * 4096
        self.assertEqual(wal.merge_committed_pages(a, wal_bytes([(2, 2, b)])), a + b)
        self.assertEqual(wal.merge_committed_pages(a + b, wal_bytes([(1, 1, b)])), b)
        with self.assertRaises(ValueError):
            wal.merge_committed_pages(a, wal_bytes([(3, 3, b)]))

    def test_stable_snapshot_size_bound_and_rollback_journal(self):
        source = self.root / "source.db"
        source.write_bytes(b"A" * 4096)
        Path(str(source) + "-wal").write_bytes(wal_bytes([(1, 1, b"B" * 4096)]))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()}
        self.assertEqual(wal.read_snapshot(source), b"B" * 4096)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()})
        with self.assertRaises(ValueError):
            wal.read_snapshot(source, max_bytes=4095)
        Path(str(source) + "-journal").write_bytes(b"synthetic")
        with self.assertRaisesRegex(ValueError, "journal"):
            wal.read_snapshot(source)

    def test_rollback_journal_appearing_mid_capture_is_rejected(self):
        source = self.root / "source.db"
        source.write_bytes(b"A" * 4096)
        metadata = wal._metadata
        def begin_journal(path):
            Path(str(source) + "-journal").write_bytes(b"synthetic journal")
            return metadata(path)
        with mock.patch.object(wal, "_metadata", side_effect=begin_journal):
            with self.assertRaisesRegex(ValueError, "journal"):
                wal.read_snapshot(source)

    def test_live_profile_does_not_fabricate_optional_databases(self):
        root = self.root / "full"
        build(root, include_sns=False)
        manifest = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(reader.validate_snapshot(root)["valid"])
        manifest["profile"] = live.PROFILE
        (root / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(reader.validate_snapshot(root)["valid"])
        self.assertFalse((root / "sns/sns.db").exists())

    def test_key_blob_decode_requires_hmac_match(self):
        encrypted = self.encrypted_fixture()
        literal = ("x'" + KEY.hex() + SALT.hex() + "'").encode()
        mask = keyscan.WINDOWS_CONFIG_XOR_MASK
        blob = bytes(value ^ mask[i % len(mask)] for i, value in enumerate(literal))
        candidates = keyscan._windows_v411_config_key_candidates(blob)
        self.assertIn((KEY.hex(), SALT.hex()), candidates)
        found, remaining = {}, {SALT.hex()}
        keyscan._verify_windows_direct_key_candidate(KEY.hex(), SALT.hex(), [("synthetic.db", None, len(encrypted), SALT.hex(), encrypted[:4096])], {}, found, remaining)
        self.assertFalse(remaining)
        self.assertEqual(found[SALT.hex()], KEY.hex())
        self.assertEqual(keyscan._windows_v411_config_key_candidates(blob * 100), [])
        alternate_mask = hashlib.sha256(b"different architecture mask").digest()
        alternate = bytes(value ^ alternate_mask[i % 32] for i, value in enumerate(literal))
        self.assertIn((KEY.hex(), SALT.hex()), keyscan._windows_v411_config_key_candidates(alternate, [SALT.hex()]))

    def test_runtime_object_traversal_accepts_only_authenticated_candidates(self):
        encrypted = self.encrypted_fixture()
        base, node, config, blob_address = 0x10000, 0x10100, 0x10400, 0x10800
        memory = bytearray(4096)
        name = keyscan.WINDOWS_CONFIG_CIPHER_NAME
        memory[64:64 + len(name)] = name
        struct.pack_into("<QQ", memory, node - base + 0x10, base + 64, len(name))
        struct.pack_into("<Q", memory, node - base + 0x28, config)
        struct.pack_into("<QQ", memory, config - base + 0x90, blob_address, 99)
        def read(address, size):
            return bytes(memory[address - base:address - base + size]) if base <= address < base + len(memory) else b""
        for candidate, should_match in ((KEY, True), (hashlib.sha256(b"wrong candidate").digest(), False)):
            literal = ("x'" + candidate.hex() + SALT.hex() + "'").encode()
            mask = hashlib.sha256(b"synthetic architecture mask").digest()
            memory[blob_address - base:blob_address - base + 99] = bytes(value ^ mask[i % 32] for i, value in enumerate(literal))
            keys, remaining = {}, {SALT.hex()}
            stats = keyscan._scan_windows_v411_config_cipher(999999, [(base, len(memory))], read, read, [("synthetic.db", None, len(encrypted), SALT.hex(), encrypted[:4096])], {SALT.hex(): ["synthetic.db"]}, keys, remaining, lambda *args: None)
            self.assertEqual(bool(keys), should_match)
            self.assertEqual(stats["matched_salts"], int(should_match))

    def test_ambiguous_sources_do_not_select_by_recency(self):
        with self.assertRaises(ValueError):
            live.choose_source([(self.root / "one", []), (self.root / "two", [])], None)

    def capture_fixture(self, scope="chat"):
        plain = self.root / "plain"
        fixture = build(plain, first_message="WINDOWS_SYNTHETIC_CAPTURE_MARKER")
        source = self.root / "source/db_storage"
        for path in live.selected_files(plain.rename(self.root / "db_storage"), scope=scope):
            reserve_database(path)
            destination = source / path.relative_to(self.root / "db_storage")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(encrypt_database(path.read_bytes()))
        return source, fixture

    def run_capture_fixture(self, source, vault, extractor=None, scope="chat", mode="full"):
        import windows_native
        def private_directory(path):
            path.mkdir(parents=True, exist_ok=True)
            return reader._secure_existing_path(path, label="synthetic vault", expected="directory")
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(live, "private_root", return_value=vault))
            if sys.platform != "win32":
                stack.enter_context(mock.patch.object(windows_native, "secure_output_root", side_effect=private_directory))
            stack.enter_context(mock.patch.object(live, "extract_keys", side_effect=extractor or (lambda *args: ({SALT.hex(): KEY.hex()}, []))))
            stack.enter_context(mock.patch.object(live, "decrypt_pages", side_effect=lambda data, key: crypto.decrypt_pages(data, key, aes_factory=TestAES)))
            return live.capture(source, live.selected_files(source, scope=scope), [999999], max_bytes=1024**2, seconds=1, scope=scope, mode=mode)

    def test_incremental_capture_reuses_verified_unchanged_dbs_and_decrypts_only_changed(self):
        source, _ = self.capture_fixture(scope="chat")
        vault = self.root / "vault-inc"
        first = self.run_capture_fixture(source, vault, scope="chat", mode="full")
        self.assertEqual(first["mode"], "full")
        self.assertEqual(first["reused_databases"], 0)
        self.assertEqual(first["decrypted_databases"], first["databases"])

        # Nothing changed: incremental skips memory key extraction and reuses every DB into a fresh immutable snapshot.
        def forbid_extract(*args):
            self.fail("extract_keys should not run when every database is unchanged")
        second = self.run_capture_fixture(source, vault, extractor=forbid_extract, scope="chat", mode="incremental")
        self.assertEqual(second["mode"], "incremental")
        self.assertEqual(second["reused_databases"], second["databases"])
        self.assertEqual(second["decrypted_databases"], 0)
        self.assertNotEqual(second["snapshot_id"], first["snapshot_id"])
        self.assertTrue(reader.validate_snapshot(Path(second["snapshot"]))["valid"])

        # Modify one encrypted message shard: incremental decrypts only that 1 DB and reuses the rest.
        plain_updated = self.root / "plain-updated"
        build(plain_updated, first_message="WINDOWS_INCREMENTAL_SECOND_MARKER")
        updated_msg = plain_updated / "message/message_0.db"
        reserve_database(updated_msg)
        (source / "message/message_0.db").write_bytes(encrypt_database(updated_msg.read_bytes()))
        third = self.run_capture_fixture(source, vault, scope="chat", mode="incremental")
        self.assertEqual(third["decrypted_databases"], 1)
        self.assertEqual(third["reused_databases"], third["databases"] - 1)
        snap3 = Path(third["snapshot"])
        chat = next(item for item in reader.contact_records(snap3).values() if item["display_name"] == "测试群")
        hits = reader.filtered_messages(snap3, chat["chat_id"], "WINDOWS_INCREMENTAL_SECOND_MARKER", None, None, 20)
        self.assertEqual(len(hits), 1)
        # Previous snapshot remains untouched and still holds the first marker.
        snap1 = Path(first["snapshot"])
        chat1 = next(item for item in reader.contact_records(snap1).values() if item["display_name"] == "测试群")
        self.assertEqual(len(reader.filtered_messages(snap1, chat1["chat_id"], "WINDOWS_INCREMENTAL_SECOND_MARKER", None, None, 20)), 0)

        # If a previous plaintext copy is tampered with, SHA-256 verification catches it and re-decrypts cleanly.
        (snap3 / "contact/contact.db").write_bytes(b"tampered plaintext")
        fourth = self.run_capture_fixture(source, vault, scope="chat", mode="incremental")
        self.assertEqual(fourth["decrypted_databases"], fourth["databases"])
        self.assertTrue(reader.validate_snapshot(Path(fourth["snapshot"]))["valid"])

    def test_full_scope_captures_required_domains_and_retains_chat_default(self):
        source, _ = self.capture_fixture(scope="all")
        default_files = {p.relative_to(source).as_posix() for p in live.selected_files(source)}
        all_files = {p.relative_to(source).as_posix() for p in live.selected_files(source, scope="all")}
        self.assertNotIn("favorite/favorite.db", default_files)
        self.assertTrue(set(reader.REQUIRED_DATABASES).issubset(all_files))
        before = {p: p.read_bytes() for p in source.rglob("*.db")}
        receipt = self.run_capture_fixture(source, self.root / "vault", scope="all")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["scope"], "all")
        snapshot = Path(receipt["snapshot"])
        self.assertEqual(reader._read_manifest(snapshot)["profile"], "full-snapshot-v1")
        self.assertTrue(reader.validate_snapshot(snapshot)["valid"])
        self.assertEqual(before, {p: p.read_bytes() for p in source.rglob("*.db")})

    def test_full_scope_rejects_directory_alias_before_traversing_it(self):
        source, _ = self.capture_fixture()
        external = self.root / "outside"; external.mkdir()
        try:
            (source / "external").symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Synthetic symlink unavailable: {type(exc).__name__}")
        with self.assertRaises(reader.ReaderError):
            live.selected_files(source, scope="all")

    def test_full_scope_records_optional_index_gap_without_waiving_authentication(self):
        source, _ = self.capture_fixture(scope="all")
        index = source / "message/message_fts.db"
        index.write_bytes(self.encrypted_fixture())
        original_connect = live.connect_read_only
        def index_logic_error(path):
            if Path(path).name == "message_fts.db":
                raise sqlite3.OperationalError("SQL logic error")
            return original_connect(path)
        with mock.patch.object(live, "connect_read_only", side_effect=index_logic_error):
            receipt = self.run_capture_fixture(source, self.root / "vault", scope="all")
        self.assertEqual(receipt["status"], "complete_with_index_gaps")
        self.assertEqual(receipt["validation"], "passed_core_with_index_gaps")
        self.assertEqual([x["database"] for x in receipt["integrity_gaps"]], ["message/message_fts.db"])
        validation = reader.validate_snapshot(Path(receipt["snapshot"]))
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["integrity_gaps"], [{"database": "message/message_fts.db", "check": "unverified"}])
        damaged = bytearray(index.read_bytes()); damaged[100] ^= 1; index.write_bytes(damaged)
        with mock.patch.object(live, "connect_read_only", side_effect=index_logic_error):
            with self.assertRaisesRegex(ValueError, "authentication"):
                self.run_capture_fixture(source, self.root / "vault-corrupted", scope="all")
        self.assertFalse((self.root / "vault-corrupted/latest.json").exists())

    def test_full_scope_never_waives_main_database_integrity(self):
        source, _ = self.capture_fixture(scope="all")
        original_connect = live.connect_read_only
        def main_logic_error(path):
            if Path(path).name == "contact.db":
                raise sqlite3.OperationalError("SQL logic error")
            return original_connect(path)
        vault = self.root / "vault"
        with mock.patch.object(live, "connect_read_only", side_effect=main_logic_error):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_capture_fixture(source, vault, scope="all")
        self.assertFalse((vault / "latest.json").exists())

    def test_full_scope_missing_required_domain_cannot_publish_latest(self):
        source, _ = self.capture_fixture(scope="all")
        favorite = source / "favorite/favorite.db"
        favorite.rename(favorite.with_suffix(".omitted"))
        vault = self.root / "vault"
        with self.assertRaisesRegex(ValueError, "schema"):
            self.run_capture_fixture(source, vault, scope="all")
        self.assertFalse((vault / "latest.json").exists())

    def test_capture_query_export_overwrite_and_source_immutability(self):
        source, fixture = self.capture_fixture()
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in source.rglob("*.db")}
        receipt = self.run_capture_fixture(source, self.root / "vault")
        snapshot = Path(receipt["snapshot"])
        self.assertTrue(reader.validate_snapshot(snapshot)["valid"])
        self.assertEqual(len(before), receipt["databases"])
        chat = next(item for item in reader.contact_records(snapshot).values() if item["display_name"] == "测试群")
        self.assertNotEqual(chat["chat_id"], fixture["group_id"])
        messages = reader.filtered_messages(snapshot, chat["chat_id"], "WINDOWS_SYNTHETIC_CAPTURE_MARKER", None, None, 20)
        self.assertEqual(len(messages), 1)
        target = self.root / "exports/chat.md"
        reader.atomic_write(reader.require_safe_output(target, True, snapshot), "first", False)
        reader.atomic_write(reader.require_safe_output(target, True, snapshot), "second", True)
        self.assertEqual(target.read_text(encoding="utf-8"), "second")
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).digest() for p in source.rglob("*.db")})

    def test_snapshots_alias_is_rejected_before_key_or_plaintext_access(self):
        source, _ = self.capture_fixture()
        vault, external = self.root / "vault", self.root / "external"
        vault.mkdir(); external.mkdir()
        try:
            (vault / "snapshots").symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Synthetic symlink unavailable: {type(exc).__name__}")
        def reject_keys(*args):
            self.fail("Key boundary reached before alias rejection")
        with self.assertRaises(reader.ReaderError):
            self.run_capture_fixture(source, vault, extractor=reject_keys)
        self.assertFalse(list(external.iterdir()))

    def test_latest_replace_failure_preserves_pointer_and_rejects_failed_capture(self):
        source, _ = self.capture_fixture()
        vault = self.root / "vault"; vault.mkdir()
        latest = vault / "latest.json"
        previous = '{"synthetic_previous_good_pointer":true}'
        latest.write_text(previous, encoding="utf-8")
        original_replace = os.replace
        def fail_pointer(src, dst):
            if Path(dst) == latest:
                raise OSError("Synthetic pointer replace failure")
            return original_replace(src, dst)
        with mock.patch.object(live.os, "replace", side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.run_capture_fixture(source, vault)
        self.assertEqual(latest.read_text(encoding="utf-8"), previous)
        attempts = list((vault / "snapshots").iterdir())
        self.assertEqual(len(attempts), 1)
        self.assertFalse(reader.validate_snapshot(attempts[0])["valid"])
        self.assertTrue((attempts[0] / "capture-failed.json").is_file())

    def test_non_windows_live_route_never_loads_mac_config(self):
        import vault_cli
        with mock.patch("sys.platform", "darwin"), mock.patch.object(vault_cli, "load_config", side_effect=AssertionError("Mac config was read")):
            self.assertEqual(vault_cli.main(["windows", "discover"]), 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows native API check")
    def test_windows_private_acl_and_wrong_process_rejection(self):
        from windows_native import profile_owner, secure_output_root, sid_text, ProcessReader
        from ctypes import wintypes as w

        class AclSizeInfo(c.Structure):
            _fields_ = [("AceCount", w.DWORD), ("AclBytesInUse", w.DWORD), ("AclBytesFree", w.DWORD)]

        owner = profile_owner()
        protected = secure_output_root(self.root / "private")
        api = c.WinDLL("advapi32", use_last_error=True)
        api.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, w.DWORD, w.DWORD, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)]
        api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.POINTER(w.ULONG)]
        api.GetAclInformation.argtypes = [c.c_void_p, c.c_void_p, w.DWORD, w.DWORD]
        api.GetAclInformation.restype = w.BOOL
        api.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
        api.GetAce.restype = w.BOOL
        descriptor, dacl, text = c.c_void_p(), c.c_void_p(), w.LPWSTR()
        self.assertEqual(api.GetNamedSecurityInfoW(str(protected), 1, 4, None, None, c.byref(dacl), None, c.byref(descriptor)), 0)
        self.assertTrue(bool(dacl.value))
        kernel = c.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [c.c_void_p]
        try:
            self.assertTrue(api.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, c.byref(text), None))
            self.assertTrue(text.value.startswith("D:P"), text.value)
            self.assertEqual(text.value.count("(A;"), 2, text.value)
            self.assertIn(";;;SY)", text.value)
            acl_info = AclSizeInfo()
            self.assertTrue(api.GetAclInformation(dacl, c.byref(acl_info), c.sizeof(acl_info), 2))
            self.assertEqual(acl_info.AceCount, 2)
            trustees = set()
            for idx in range(acl_info.AceCount):
                ace = c.c_void_p()
                self.assertTrue(api.GetAce(dacl, idx, c.byref(ace)))
                # ACCESS_ALLOWED_ACE: ACE_HEADER (4 bytes) + ACCESS_MASK (4 bytes) + SidStart at offset 8.
                trustees.add(sid_text(c.c_void_p(ace.value + 8)))
            self.assertEqual(trustees, {owner, "S-1-5-18"})
        finally:
            if text.value:
                kernel.LocalFree(text)
            kernel.LocalFree(descriptor)
        with self.assertRaisesRegex(RuntimeError, "not a Windows-trusted Weixin"):
            ProcessReader(os.getpid(), owner)

    def test_v2_image_key_memory_scan_recovers_key_and_rejects_wrong_candidates(self):
        def ecb_encrypt(key_bytes: bytes, data: bytes) -> bytes:
            if sys.platform == "win32":
                from ctypes import wintypes as w
                aes = crypto.CngAES(key_bytes, chaining_mode="ChainingModeECB")
                try:
                    api = aes.api.BCryptEncrypt
                    api.argtypes = aes.api.BCryptDecrypt.argtypes
                    api.restype = w.LONG
                    src = c.create_string_buffer(data, len(data))
                    out = c.create_string_buffer(len(data))
                    written = w.ULONG()
                    crypto.CngAES._check(api(aes.key, src, len(data), None, None, 0, out, len(data), c.byref(written), 0))
                    return out.raw
                finally:
                    aes.close()
            from Crypto.Cipher import AES
            return AES.new(key_bytes, AES.MODE_ECB).encrypt(data)

        def ecb_factory(key_bytes: bytes):
            if sys.platform == "win32":
                return crypto.CngAES(key_bytes, chaining_mode="ChainingModeECB")
            from Crypto.Cipher import AES
            class _PyECB:
                def decrypt(self, _iv, data):
                    return AES.new(key_bytes, AES.MODE_ECB).decrypt(data)
                def close(self):
                    pass
            return _PyECB()

        real_key = b"a1b2c3d4e5f60718"
        xor_key = 0x42
        clear_jpg = b"\xff\xd8\xff\xe0" + b"synthetic-v2-jpeg-body" + b"\xff\xd9"
        head, mid, tail = clear_jpg[:8], clear_jpg[8:-2], clear_jpg[-2:]
        v2_dat = (
            b"\x07\x08V2\x08\x07"
            + struct.pack("<I", len(head))
            + struct.pack("<I", len(tail))
            + b"\x00"
            + ecb_encrypt(real_key, head + bytes([8]) * 8)
            + mid
            + bytes(b ^ xor_key for b in tail)
        )

        base = 0x20000
        mem = b"\x00" * 128 + b"deadbeef00112233" + b"\x00" * 64 + real_key + b"9988776655443322" + b"\x00" * 128
        def read_mem(addr, size):
            return mem[addr - base : addr - base + size] if base <= addr < base + len(mem) else b""

        hit = keyscan.scan_v2_image_key_in_regions([(base, len(mem))], read_mem, v2_dat, aes_factory=ecb_factory)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["aesKey"], real_key)
        self.assertEqual(hit["xorKey"], xor_key)
        self.assertEqual(hit["source"], "memory")

        # Without the real key in memory, scanner returns None cleanly.
        decoy_mem = b"\x00" * 128 + b"deadbeef00112233" + b"\x00" * 128
        hit_none = keyscan.scan_v2_image_key_in_regions(
            [(base, len(decoy_mem))],
            lambda addr, size: decoy_mem[addr - base : addr - base + size] if base <= addr < base + len(decoy_mem) else b"",
            v2_dat,
            aes_factory=ecb_factory,
        )
        self.assertIsNone(hit_none)

        # Also recover when only a C++ wstring UTF-16LE kvcomm path (`key_<code>_...`) is in memory!
        code_num = 200890261
        acct = "wxid_owner_fixture"
        kv_aes = hashlib.md5(f"{code_num}{acct}".encode("utf-8")).hexdigest()[:16].encode("ascii")
        kv_xor = code_num & 0xFF
        v2_kv_dat = (
            b"\x07\x08V2\x08\x07"
            + struct.pack("<I", len(head))
            + struct.pack("<I", len(tail))
            + b"\x00"
            + ecb_encrypt(kv_aes, head + bytes([8]) * 8)
            + mid
            + bytes(b ^ kv_xor for b in tail)
        )
        utf16_mem = (
            b"\x00" * 64
            + f"C:\\AppData\\Roaming\\Tencent\\xwechat\\net_1\\kvcomm\\key_{code_num}_1_input.statistic".encode("utf-16le")
            + b"\x00" * 64
        )
        hit_utf16 = keyscan.scan_v2_image_key_in_regions(
            [(base, len(utf16_mem))],
            lambda addr, size: utf16_mem[addr - base : addr - base + size] if base <= addr < base + len(utf16_mem) else b"",
            v2_kv_dat,
            account_names=(acct,),
            aes_factory=ecb_factory,
        )
        self.assertIsNotNone(hit_utf16)
        self.assertEqual(hit_utf16["aesKey"], kv_aes)
        self.assertEqual(hit_utf16["xorKey"], kv_xor)
        self.assertEqual(hit_utf16["source"], "memory")

    def test_fts_mmftstokenizer_verifies_physical_btrees_and_rejects_btree_corruption(self):
        fts_db = self.root / "synthetic_fts.db"
        orig_tok = "unicode61 remove_diacritics 2"
        mm_tok = "MMFtsTokenizer disable_pinyin"
        self.assertEqual(len(orig_tok), len(mm_tok))
        con = sqlite3.connect(fts_db)
        try:
            con.execute("PRAGMA page_size = 4096")
            con.execute(f"CREATE VIRTUAL TABLE fav_fts_v1 USING fts5(tokenize = '{orig_tok}', content)")
            for idx in range(60):
                con.execute("INSERT INTO fav_fts_v1(content) VALUES (?)", (f"row-{idx}-" + ("X" * 200),))
            con.commit()
        finally:
            con.close()

        # Patch equal-length tokenizer name in page 1 sqlite_master so it mirrors real WeChat 4.x FTS5 DBs.
        db_bytes = fts_db.read_bytes()
        self.assertIn(orig_tok.encode("ascii"), db_bytes[:4096])
        patched = db_bytes[:4096].replace(orig_tok.encode("ascii"), mm_tok.encode("ascii"), 1) + db_bytes[4096:]
        fts_db.write_bytes(patched)

        # Whole-DB PRAGMA integrity_check fails with SQL logic error due to unregistered MMFtsTokenizer.
        with live.connect_read_only(fts_db) as ro:
            with self.assertRaisesRegex(sqlite3.OperationalError, "SQL logic error"):
                ro.execute("PRAGMA integrity_check").fetchall()

        state, reason = live._verify_fts_physical_btrees(fts_db)
        self.assertEqual(state, "unverified")
        self.assertIn("MMFtsTokenizer", reason)
        self.assertIn("5 physical B-tree tables passed", reason)

        # Corrupt a physical FTS5 shadow B-tree page: _verify_fts_physical_btrees MUST fail closed!
        raw = bytearray(fts_db.read_bytes())
        self.assertGreaterEqual(len(raw), 3 * 4096)
        raw[2 * 4096 : 2 * 4096 + 128] = b"\xff" * 128
        fts_db.write_bytes(raw)
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            live._verify_fts_physical_btrees(fts_db)

    @unittest.skipUnless(sys.platform == "win32", "Windows native Medium-Integrity non-admin token check")
    def test_medium_integrity_non_admin_token_acl_and_memory_read(self):
        from ctypes import wintypes as w
        import subprocess
        import tempfile
        import uuid

        # Spawn a helper that drops to SAFER_LEVELID_NORMALUSER (Medium Integrity, non-elevated)
        # and runs ACL + CNG + same-user OpenProcess/ReadProcessMemory checks without admin privileges.
        scripts_dir = str((Path(__file__).resolve().parents[1] / "scripts").resolve())
        work_dir = str((self.root / "med-integrity").resolve())
        os.makedirs(work_dir, exist_ok=True)
        helper_py = self.root / "med_helper.py"
        helper_py.write_text(
            "import ctypes as c, json, os, pathlib, subprocess, sys, time\n"
            "from ctypes import wintypes as w\n"
            f"sys.path.insert(0, {scripts_dir!r})\n"
            "import windows_crypto, windows_native\n"
            "\n"
            "def token_integrity_rid():\n"
            "    adv = c.WinDLL('advapi32', use_last_error=True)\n"
            "    ker = c.WinDLL('kernel32', use_last_error=True)\n"
            "    ker.GetCurrentProcess.restype = w.HANDLE\n"
            "    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]\n"
            "    adv.GetTokenInformation.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]\n"
            "    tok = w.HANDLE()\n"
            "    assert adv.OpenProcessToken(ker.GetCurrentProcess(), 8, c.byref(tok))\n"
            "    sz = w.DWORD()\n"
            "    adv.GetTokenInformation(tok, 25, None, 0, c.byref(sz))\n"
            "    buf = c.create_string_buffer(sz.value)\n"
            "    assert adv.GetTokenInformation(tok, 25, buf, sz, c.byref(sz))\n"
            "    sid_ptr = c.cast(buf, c.POINTER(c.c_void_p))[0]\n"
            "    sid_str = windows_native.sid_text(sid_ptr)\n"
            "    ker.CloseHandle(tok)\n"
            "    return sid_str\n"
            "\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'hold':\n"
            "    secret = b'MED_INTEGRITY_MEM_OK_2026'\n"
            "    buf = c.create_string_buffer(secret)\n"
            "    print(c.addressof(buf), len(secret), flush=True)\n"
            "    time.sleep(10)\n"
            "    sys.exit(0)\n"
            "\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'worker':\n"
            "    import shutil, tempfile, uuid\n"
            "    il = token_integrity_rid()\n"
            "    owner = windows_native.profile_owner()\n"
            "    med_tmp = pathlib.Path(tempfile.gettempdir()) / ('wechat-med-' + uuid.uuid4().hex)\n"
            "    try:\n"
            "        acl_dir = windows_native.secure_output_root(med_tmp / 'vault')\n"
            "        acl_ok = acl_dir.is_dir()\n"
            "    finally:\n"
            "        shutil.rmtree(med_tmp, ignore_errors=True)\n"
            "    aes = windows_crypto.CngAES(b'0123456789abcdef', chaining_mode='ChainingModeECB')\n"
            "    aes.close()\n"
            "    holder = subprocess.Popen([sys.executable, __file__, 'hold'], stdout=subprocess.PIPE, text=True)\n"
            "    try:\n"
            "        addr_s, ln_s = holder.stdout.readline().strip().split()\n"
            "        addr, ln = int(addr_s), int(ln_s)\n"
            "        ker = c.WinDLL('kernel32', use_last_error=True)\n"
            "        ker.OpenProcess.argtypes, ker.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE\n"
            "        ker.ReadProcessMemory.argtypes, ker.ReadProcessMemory.restype = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)], w.BOOL\n"
            "        h = ker.OpenProcess(0x0010 | 0x0400, False, holder.pid)\n"
            "        assert h, f'OpenProcess failed err={c.get_last_error()}'\n"
            "        out = c.create_string_buffer(ln)\n"
            "        got = c.c_size_t()\n"
            "        assert ker.ReadProcessMemory(h, c.c_void_p(addr), out, ln, c.byref(got))\n"
            "        ker.CloseHandle(h)\n"
            "        assert out.raw[:got.value] == b'MED_INTEGRITY_MEM_OK_2026'\n"
            "    finally:\n"
            "        holder.terminate()\n"
            "        holder.wait(timeout=5)\n"
            "    print(json.dumps({'integrity_sid': il, 'owner_ok': owner.startswith('S-1-5-21-'), 'acl_exists': acl_ok}))\n"
            "    sys.exit(0)\n"
            "\n"
            "# Launcher: compute SAFER_LEVELID_NORMALUSER token, explicitly lower to Medium Integrity (S-1-16-8192), and spawn worker.\n"
            "adv = c.WinDLL('advapi32', use_last_error=True)\n"
            "ker = c.WinDLL('kernel32', use_last_error=True)\n"
            "adv.SaferCreateLevel.argtypes, adv.SaferCreateLevel.restype = [w.DWORD, w.DWORD, w.DWORD, c.POINTER(w.HANDLE), c.c_void_p], w.BOOL\n"
            "adv.SaferComputeTokenFromLevel.argtypes, adv.SaferComputeTokenFromLevel.restype = [w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE), w.DWORD, c.c_void_p], w.BOOL\n"
            "adv.SaferCloseLevel.argtypes, adv.SaferCloseLevel.restype = [w.HANDLE], w.BOOL\n"
            "adv.ConvertStringSidToSidW.argtypes, adv.ConvertStringSidToSidW.restype = [w.LPCWSTR, c.POINTER(c.c_void_p)], w.BOOL\n"
            "adv.GetLengthSid.argtypes, adv.GetLengthSid.restype = [c.c_void_p], w.DWORD\n"
            "adv.SetTokenInformation.argtypes, adv.SetTokenInformation.restype = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD], w.BOOL\n"
            "level = w.HANDLE()\n"
            "assert adv.SaferCreateLevel(2, 0x20000, 1, c.byref(level), None), c.get_last_error()\n"
            "restricted = w.HANDLE()\n"
            "assert adv.SaferComputeTokenFromLevel(level, None, c.byref(restricted), 0, None), c.get_last_error()\n"
            "adv.SaferCloseLevel(level)\n"
            "\n"
            "class SID_AND_ATTRIBUTES(c.Structure):\n"
            "    _fields_ = [('Sid', c.c_void_p), ('Attributes', w.DWORD)]\n"
            "med_sid = c.c_void_p()\n"
            "assert adv.ConvertStringSidToSidW('S-1-16-8192', c.byref(med_sid)), c.get_last_error()\n"
            "tml = SID_AND_ATTRIBUTES(med_sid, 0x20)\n"
            "tml_len = c.sizeof(SID_AND_ATTRIBUTES) + adv.GetLengthSid(med_sid)\n"
            "assert adv.SetTokenInformation(restricted, 25, c.byref(tml), tml_len), c.get_last_error()\n"
            "ker.LocalFree.argtypes = [c.c_void_p]\n"
            "ker.LocalFree(med_sid)\n"
            "\n"
            "class STARTUPINFOW(c.Structure):\n"
            "    _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR),\n"
            "                ('dwX', w.DWORD), ('dwY', w.DWORD), ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),\n"
            "                ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD),\n"
            "                ('dwFlags', w.DWORD), ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),\n"
            "                ('lpReserved2', c.c_void_p), ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]\n"
            "class PROCESS_INFORMATION(c.Structure):\n"
            "    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]\n"
            "\n"
            "out_file = pathlib.Path(sys.argv[2])\n"
            "adv.CreateProcessAsUserW.argtypes = [w.HANDLE, w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFOW), c.POINTER(PROCESS_INFORMATION)]\n"
            "adv.CreateProcessAsUserW.restype = w.BOOL\n"
            "si = STARTUPINFOW()\n"
            "si.cb = c.sizeof(si)\n"
            "pi = PROCESS_INFORMATION()\n"
            "cmd_str = f'\"{sys.executable}\" -c \"import pathlib, subprocess, sys; p = subprocess.run([sys.executable, {str(pathlib.Path(__file__))!r}, \\'worker\\'], capture_output=True, text=True); pathlib.Path({str(out_file)!r}).write_text(str(p.returncode) + \\'\\\\n\\' + p.stdout + p.stderr, encoding=\\'utf-8\\')\"'\n"
            "cmd_buf = c.create_unicode_buffer(cmd_str)\n"
            "ok = adv.CreateProcessAsUserW(restricted, None, cmd_buf, None, None, False, 0x08000000, None, None, c.byref(si), c.byref(pi))\n"
            "err = c.get_last_error()\n"
            "ker.CloseHandle(restricted)\n"
            "assert ok, f'CreateProcessAsUserW failed err={err}'\n"
            "ker.WaitForSingleObject(pi.hProcess, 30000)\n"
            "ker.CloseHandle(pi.hThread)\n"
            "ker.CloseHandle(pi.hProcess)\n",
            encoding="utf-8",
        )
        out_path = Path(tempfile.gettempdir()) / f"wechat-med-res-{uuid.uuid4().hex}.txt"
        try:
            proc = subprocess.run(
                [sys.executable, str(helper_py), "launch", str(out_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = out_path.read_text(encoding="utf-8").splitlines()
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.assertEqual(lines[0], "0", "\n".join(lines))
        payload = json.loads(lines[1])
        # S-1-16-8192 is Mandatory Label\Medium Mandatory Level (strictly non-admin/non-elevated).
        self.assertEqual(payload["integrity_sid"], "S-1-16-8192", payload)
        self.assertTrue(payload["owner_ok"])
        self.assertTrue(payload["acl_exists"])


if __name__ == "__main__":
    unittest.main()
