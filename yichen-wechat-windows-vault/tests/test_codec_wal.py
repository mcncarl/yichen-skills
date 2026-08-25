from __future__ import annotations

import hashlib
import hmac
import ctypes
import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlcipher_codec import (  # noqa: E402
    DEFAULT_PROFILE,
    derive_hmac_key,
    key_matches_page,
    sqlite_integrity_check,
)
from wal_snapshot import (  # noqa: E402
    WAL_MAGIC_LITTLE_ENDIAN_CHECKSUM,
    decrypt_database_with_wal,
    parse_wal,
    wal_checksum,
)
import windows_vault  # noqa: E402
import windows_memory  # noqa: E402


def encrypt_page(clear_page: bytes, page_number: int, key: bytes, salt: bytes) -> bytes:
    profile = DEFAULT_PROFILE
    clear = bytearray(clear_page)
    clear[profile.reserve_offset :] = b"\x00" * profile.reserve_size
    if page_number == 1:
        clear[20] = profile.reserve_size
    start = profile.encrypted_offset(page_number)
    iv = hashlib.sha256(b"iv" + page_number.to_bytes(4, "little")).digest()[:16]
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(bytes(clear[start : profile.reserve_offset])) + encryptor.finalize()
    encrypted = bytearray(profile.page_size)
    if page_number == 1:
        encrypted[:16] = salt
    encrypted[start : profile.reserve_offset] = ciphertext
    encrypted[profile.reserve_offset : profile.hmac_offset] = iv
    message = bytes(encrypted[start : profile.hmac_offset]) + page_number.to_bytes(4, "little")
    digest = hmac.new(derive_hmac_key(key, salt), message, hashlib.sha512).digest()
    encrypted[profile.hmac_offset : profile.hmac_offset + profile.hmac_size] = digest
    return bytes(encrypted)


def encrypt_database(clear: Path, encrypted: Path, key: bytes, salt: bytes) -> None:
    data = clear.read_bytes()
    if len(data) % DEFAULT_PROFILE.page_size:
        raise AssertionError("fixture database is not page aligned")
    output = bytearray()
    for index in range(len(data) // DEFAULT_PROFILE.page_size):
        page = data[index * DEFAULT_PROFILE.page_size : (index + 1) * DEFAULT_PROFILE.page_size]
        output.extend(encrypt_page(page, index + 1, key, salt))
    encrypted.write_bytes(output)


def build_wal(frames: list[tuple[int, int, bytes]]) -> bytes:
    page_size = DEFAULT_PROFILE.page_size
    header = bytearray(
        struct.pack(
            ">IIIIII",
            WAL_MAGIC_LITTLE_ENDIAN_CHECKSUM,
            3_007_000,
            page_size,
            0,
            0x12345678,
            0x90ABCDEF,
        )
    )
    checksum = wal_checksum(bytes(header), byteorder="little")
    header.extend(struct.pack(">II", *checksum))
    output = bytearray(header)
    salt = header[16:24]
    for page_number, commit_pages, encrypted_page in frames:
        frame_header = bytearray(struct.pack(">II", page_number, commit_pages) + salt)
        checksum = wal_checksum(bytes(frame_header[:8]) + encrypted_page, checksum, byteorder="little")
        frame_header.extend(struct.pack(">II", *checksum))
        output.extend(frame_header)
        output.extend(encrypted_page)
    return bytes(output)


def build_shm(wal: bytes, max_frame: int, database_pages: int, backfill: int) -> bytes:
    prefix = "<" if sys.byteorder == "little" else ">"
    header = bytearray(48)
    struct.pack_into(f"{prefix}I", header, 0, 3_007_000)
    header[12] = 1
    header[13] = int(sys.byteorder == "big")
    struct.pack_into(f"{prefix}H", header, 14, DEFAULT_PROFILE.page_size)
    struct.pack_into(f"{prefix}I", header, 16, max_frame)
    struct.pack_into(f"{prefix}I", header, 20, database_pages)
    header[32:40] = wal[16:24]
    struct.pack_into(
        f"{prefix}II",
        header,
        40,
        *wal_checksum(bytes(header[:40]), byteorder=sys.byteorder),
    )
    checkpoint = bytearray(40)
    struct.pack_into(f"{prefix}I", checkpoint, 0, backfill)
    return bytes(header + header + checkpoint)


class CodecWalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.key = bytes(range(32))
        self.salt = bytes(range(16, 32))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_database(self, path: Path, rows: list[str]) -> None:
        if os.name != "nt":
            self.skipTest("fixture uses Windows sqlite3_file_control")
        sqlite = ctypes.WinDLL(str(Path(sys.base_prefix) / "DLLs/sqlite3.dll"))
        sqlite.sqlite3_open.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))
        sqlite.sqlite3_open.restype = ctypes.c_int
        sqlite.sqlite3_exec.argtypes = (
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
        )
        sqlite.sqlite3_exec.restype = ctypes.c_int
        sqlite.sqlite3_file_control.argtypes = (
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        sqlite.sqlite3_file_control.restype = ctypes.c_int
        sqlite.sqlite3_close.argtypes = (ctypes.c_void_p,)
        handle = ctypes.c_void_p()
        self.assertEqual(sqlite.sqlite3_open(os.fsencode(path), ctypes.byref(handle)), 0)
        try:
            error = ctypes.c_char_p()
            self.assertEqual(
                sqlite.sqlite3_exec(handle, b"PRAGMA page_size=4096;", None, None, ctypes.byref(error)),
                0,
            )
            reserve = ctypes.c_int(80)
            self.assertEqual(sqlite.sqlite3_file_control(handle, b"main", 38, ctypes.byref(reserve)), 0)
            values = ",".join("('" + row.replace("'", "''") + "')" for row in rows)
            sql = (
                "CREATE TABLE items(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);"
                f"INSERT INTO items(payload) VALUES {values};"
            ).encode("utf-8")
            self.assertEqual(sqlite.sqlite3_exec(handle, sql, None, None, ctypes.byref(error)), 0)
        finally:
            sqlite.sqlite3_close(handle)
        self.assertEqual(path.read_bytes()[20], 80)
        sqlite_integrity_check(path)

    def test_database_key_and_hmac_validation(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "encrypted.db"
        output = self.root / "output.db"
        self.make_database(clear, ["base"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        first_page = encrypted.read_bytes()[:4096]
        self.assertTrue(key_matches_page(first_page, self.key))
        tampered = bytearray(first_page)
        tampered[100] ^= 1
        self.assertFalse(key_matches_page(bytes(tampered), self.key))
        report = decrypt_database_with_wal(encrypted, None, output, self.key)
        self.assertFalse(report.present)
        connection = sqlite3.connect(output)
        try:
            self.assertEqual(connection.execute("SELECT payload FROM items").fetchall(), [("base",)])
        finally:
            connection.close()

    def test_wal_only_commit_is_applied_and_trailing_bytes_are_ignored(self) -> None:
        base_clear = self.root / "base-clear.db"
        updated_clear = self.root / "updated-clear.db"
        encrypted = self.root / "encrypted.db"
        wal = self.root / "encrypted.db-wal"
        output = self.root / "output.db"
        self.make_database(base_clear, ["base"])
        shutil_data = base_clear.read_bytes()
        updated_clear.write_bytes(shutil_data)
        connection = sqlite3.connect(updated_clear)
        try:
            connection.execute("INSERT INTO items(payload) VALUES ('wal-only')")
            connection.commit()
        finally:
            connection.close()
        encrypt_database(base_clear, encrypted, self.key, self.salt)

        base_data = base_clear.read_bytes()
        updated_data = updated_clear.read_bytes()
        page_count = len(updated_data) // DEFAULT_PROFILE.page_size
        changed: list[tuple[int, int, bytes]] = []
        differing_pages = [
            index + 1
            for index in range(page_count)
            if base_data[index * 4096 : (index + 1) * 4096]
            != updated_data[index * 4096 : (index + 1) * 4096]
        ]
        self.assertTrue(differing_pages)
        for position, page_number in enumerate(differing_pages):
            clear_page = updated_data[(page_number - 1) * 4096 : page_number * 4096]
            commit_pages = page_count if position == len(differing_pages) - 1 else 0
            changed.append((page_number, commit_pages, encrypt_page(clear_page, page_number, self.key, self.salt)))
        wal.write_bytes(build_wal(changed) + b"partial-tail")

        parsed, trailing, invalid = parse_wal(wal, 4096)
        self.assertEqual(len(parsed), len(changed))
        self.assertEqual(trailing, len(b"partial-tail"))
        self.assertEqual(invalid, 0)
        report = decrypt_database_with_wal(encrypted, wal, output, self.key)
        self.assertEqual(report.applied_frames, len(changed))
        self.assertEqual(report.ignored_trailing_bytes, len(b"partial-tail"))
        connection = sqlite3.connect(output)
        try:
            rows = connection.execute("SELECT payload FROM items ORDER BY id").fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [("base",), ("wal-only",)])

    def test_wal_checksum_rejects_corrupted_frame(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "encrypted.db"
        wal = self.root / "encrypted.db-wal"
        self.make_database(clear, ["base"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        page = encrypted.read_bytes()[:4096]
        data = bytearray(build_wal([(1, len(encrypted.read_bytes()) // 4096, page)]))
        data[-1] ^= 1
        wal.write_bytes(data)
        frames, trailing, invalid = parse_wal(wal, 4096)
        self.assertEqual(frames, [])
        self.assertEqual(trailing, 0)
        self.assertEqual(invalid, 1)
        with self.assertRaisesRegex(ValueError, "invalid complete frame"):
            decrypt_database_with_wal(encrypted, wal, self.root / "rejected.db", self.key)

    def test_valid_shm_ignores_stale_frames_after_wal_index_reset(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "encrypted.db"
        wal = self.root / "encrypted.db-wal"
        shm = self.root / "encrypted.db-shm"
        output = self.root / "output.db"
        self.make_database(clear, ["base"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        database_pages = encrypted.stat().st_size // DEFAULT_PROFILE.page_size
        stale = bytearray(build_wal([(1, database_pages, encrypted.read_bytes()[:4096])]))
        stale[-1] ^= 1
        wal.write_bytes(stale)
        shm.write_bytes(build_shm(stale, max_frame=0, database_pages=database_pages, backfill=0))

        report = decrypt_database_with_wal(encrypted, wal, output, self.key)

        self.assertTrue(report.shm_validated)
        self.assertEqual(report.applied_frames, 0)
        connection = sqlite3.connect(output)
        try:
            rows = connection.execute("SELECT payload FROM items ORDER BY id").fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [("base",)])

    def test_incremental_refresh_reuses_only_unchanged_verified_plaintext(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "contact.db"
        account_root = self.root / "account"
        vault = self.root / "vault"
        account_root.mkdir()
        self.make_database(clear, ["base"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        key_store = MagicMock()

        def get_key(relative: str):
            if relative in {"contact/contact.db", "general/general.db"}:
                return self.key, DEFAULT_PROFILE
            raise KeyError(relative)

        key_store.get.side_effect = get_key
        databases = {
            "contact/contact.db": encrypted,
            "general/general.db": encrypted,
        }

        real_decrypt = windows_vault.decrypt_database_with_wal

        def decrypt_or_raise(database, wal, destination, key, profile):
            if destination.as_posix().endswith("general/general.db"):
                raise sqlite3.OperationalError("fixture codec extension is unavailable")
            return real_decrypt(database, wal, destination, key, profile)

        with (
            patch.object(windows_vault, "find_process_ids", return_value=[]),
            patch.object(windows_vault, "database_paths", return_value=databases),
            patch.object(windows_vault, "KeyStore", return_value=key_store),
            patch.object(
                windows_vault,
                "decrypt_database_with_wal",
                side_effect=decrypt_or_raise,
            ),
        ):
            first = windows_vault.refresh(account_root, self.root / "keys.json", vault, "full")
            second = windows_vault.refresh(
                account_root, self.root / "keys.json", vault, "incremental"
            )
            second_manifest = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
            self.assertTrue(first["complete"])
            self.assertEqual(first["optional_missing_count"], 1)
            contact_record = next(
                record
                for record in second_manifest["records"]
                if record["database"] == "contact/contact.db"
            )
            self.assertTrue(contact_record["incremental_reuse"])

            updated = self.root / "updated.db"
            self.make_database(updated, ["changed"])
            encrypt_database(updated, encrypted, self.key, self.salt)
            third = windows_vault.refresh(
                account_root, self.root / "keys.json", vault, "incremental"
            )
            third_manifest = json.loads(Path(third["manifest"]).read_text(encoding="utf-8"))
            contact_record = next(
                record
                for record in third_manifest["records"]
                if record["database"] == "contact/contact.db"
            )
            self.assertFalse(contact_record["incremental_reuse"])

    def test_missing_required_database_key_prevents_snapshot_promotion(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "encrypted.db"
        account_root = self.root / "account"
        vault = self.root / "vault"
        account_root.mkdir()
        self.make_database(clear, ["required"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        key_store = MagicMock()

        def get_key(relative: str):
            if relative == "contact/contact.db":
                return self.key, DEFAULT_PROFILE
            raise KeyError(relative)

        key_store.get.side_effect = get_key
        databases = {
            "contact/contact.db": encrypted,
            "session/session.db": encrypted,
        }
        with (
            patch.object(windows_vault, "find_process_ids", return_value=[]),
            patch.object(windows_vault, "database_paths", return_value=databases),
            patch.object(windows_vault, "KeyStore", return_value=key_store),
        ):
            result = windows_vault.refresh(account_root, self.root / "keys.json", vault, "full")

        self.assertFalse(result["complete"])
        self.assertEqual(result["required_missing_count"], 1)
        self.assertFalse((vault / "current.json").exists())

    def test_public_codec_geometry_finds_and_validates_a_read_only_key_buffer(self) -> None:
        clear = self.root / "clear.db"
        encrypted = self.root / "message_0.db"
        self.make_database(clear, ["scanner"])
        encrypt_database(clear, encrypted, self.key, self.salt)
        target = windows_memory.DatabaseTarget.from_path("message/message_0.db", encrypted)

        context_address = 0x2000
        salt_address = 0x2800
        cipher_address = 0x3000
        key_address = 0x3800
        codec = bytearray(136)
        pattern = windows_memory._codec_patterns([target])[0]
        codec[12 : 12 + len(pattern)] = pattern
        struct.pack_into("<Q", codec, 72, salt_address)
        struct.pack_into("<Q", codec, 104, cipher_address)
        struct.pack_into("<Q", codec, 112, cipher_address)
        cipher = bytearray(24)
        struct.pack_into("<iiQ", cipher, 0, 0, 32, key_address)
        memory = {
            (context_address, 136): bytes(codec),
            (salt_address, 16): self.salt,
            (cipher_address, 24): bytes(cipher),
            (key_address, 32): self.key,
        }

        def read_memory(_handle: int, address: int, size: int) -> bytes:
            return memory.get((address, size), b"")

        regions = [(0x1000, 0x4000)]
        with (
            patch.object(
                windows_memory,
                "_iter_region_data",
                return_value=[(context_address, bytes(codec))],
            ),
            patch.object(windows_memory, "_read_region", side_effect=read_memory),
        ):
            candidates, contexts = windows_memory._find_candidates(1, regions, [target])
            matches = windows_memory._monitor_candidates(1, 1234, candidates, 0)

        self.assertEqual(contexts, 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].key_address, key_address)
        self.assertEqual([match.database for match in matches], ["message/message_0.db"])

    def test_capture_aggregates_validated_matches_from_multiple_weixin_processes(self) -> None:
        page = b"x" * DEFAULT_PROFILE.page_size
        first = windows_memory.DatabaseTarget("first.db", self.root / "first.db", page)
        second = windows_memory.DatabaseTarget("second.db", self.root / "second.db", page)
        candidate_by_pid = {
            101: [windows_memory.Candidate(first, 0x1000)],
            202: [windows_memory.Candidate(second, 0x2000)],
        }
        fake_kernel32 = MagicMock()
        fake_kernel32.OpenProcess.side_effect = lambda _rights, _inherit, pid: pid

        def find_candidates(handle, _regions, _targets):
            return candidate_by_pid[handle], 1

        def monitor(_handle, pid, candidates, _duration):
            target = candidates[0].target
            return (
                windows_memory.Match(
                    database=target.database,
                    pid=pid,
                    key=self.key,
                    profile=DEFAULT_PROFILE,
                ),
            )

        with (
            patch.object(windows_memory, "kernel32", fake_kernel32),
            patch.object(windows_memory, "find_process_ids", return_value=[101, 202]),
            patch.object(windows_memory, "_readable_regions", return_value=[(0x1000, 0x4000)]),
            patch.object(windows_memory, "_find_candidates", side_effect=find_candidates),
            patch.object(windows_memory, "_monitor_candidates", side_effect=monitor),
        ):
            report = windows_memory.capture_keys([first, second], 0)

        self.assertEqual(report.pids_checked, 2)
        self.assertEqual(report.codec_contexts, 2)
        self.assertEqual(report.monitored_buffers, 2)
        self.assertEqual(
            sorted(match.database for match in report.matches),
            ["first.db", "second.db"],
        )
        self.assertEqual(fake_kernel32.CloseHandle.call_count, 2)


if __name__ == "__main__":
    unittest.main()
