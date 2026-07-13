#!/usr/bin/env python3
"""Offline unit tests; no WeCom process or user database is touched."""

from __future__ import annotations

import struct
import unittest

from vault_cli import decode_content
from wecom_crypto import (
    PAGE_SIZE,
    SQLITE_HEADER,
    _wal_frames,
    database_format,
    decrypt_database_bytes,
    decrypt_page,
    encrypt_page_for_test,
    page_iv,
    page_key,
    verify_key,
)


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes.fromhex("00112233445566778899aabbccddeeff")
        self.page_one = bytearray(PAGE_SIZE)
        self.page_one[:16] = SQLITE_HEADER
        self.page_one[16:18] = (PAGE_SIZE).to_bytes(2, "big")
        self.page_one[21:24] = b"\x40\x20\x20"
        self.page_one[100] = 0x0D
        self.page_one[108:124] = b"offline-test-row"

    def test_page_one_round_trip_and_validation(self):
        encrypted = encrypt_page_for_test(self.key, bytes(self.page_one), 1)
        self.assertEqual(database_format(encrypted), "wecom-wxsqlite3-aes128")
        self.assertTrue(verify_key(self.key, encrypted))
        self.assertFalse(verify_key(bytes(16), encrypted))
        self.assertEqual(decrypt_page(self.key, encrypted, 1), bytes(self.page_one))

    def test_later_page_round_trip(self):
        page = bytes((index * 17) % 256 for index in range(PAGE_SIZE))
        encrypted = encrypt_page_for_test(self.key, page, 9)
        self.assertEqual(decrypt_page(self.key, encrypted, 9), page)

    def test_key_and_iv_are_page_specific(self):
        self.assertNotEqual(page_key(self.key, 1), page_key(self.key, 2))
        self.assertNotEqual(page_iv(1), page_iv(2))

    def test_wal_parser_stops_at_last_commit(self):
        wal_header = struct.pack(">IIIIIIII", 0x377F0682, 3007000, PAGE_SIZE, 0, 1, 2, 0, 0)
        frame_one = struct.pack(">IIIIII", 2, 0, 1, 2, 0, 0) + bytes(PAGE_SIZE)
        frame_two = struct.pack(">IIIIII", 3, 3, 1, 2, 0, 0) + bytes([1]) * PAGE_SIZE
        uncommitted = struct.pack(">IIIIII", 4, 0, 1, 2, 0, 0) + bytes([2]) * PAGE_SIZE
        frames = _wal_frames(wal_header + frame_one + frame_two + uncommitted, PAGE_SIZE)
        self.assertEqual([(page, commit) for page, commit, _ in frames], [(2, 0), (3, 3)])

    def test_wal_parser_skips_stale_salt_frames(self):
        wal_header = struct.pack(">IIIIIIII", 0x377F0682, 3007000, PAGE_SIZE, 0, 1, 2, 0, 0)
        stale_frame = struct.pack(">IIIIII", 2, 2, 9, 9, 0, 0) + bytes([7]) * PAGE_SIZE
        current_frame = struct.pack(">IIIIII", 3, 3, 1, 2, 0, 0) + bytes([8]) * PAGE_SIZE
        frames = _wal_frames(wal_header + stale_frame + current_frame, PAGE_SIZE)
        self.assertEqual([(page, commit) for page, commit, _ in frames], [(3, 3)])

    def test_database_and_committed_wal_round_trip(self):
        base_second_page = bytes([3]) * PAGE_SIZE
        updated_second_page = bytes([9]) * PAGE_SIZE
        encrypted_database = (
            encrypt_page_for_test(self.key, bytes(self.page_one), 1)
            + encrypt_page_for_test(self.key, base_second_page, 2)
        )
        wal_header = struct.pack(">IIIIIIII", 0x377F0682, 3007000, PAGE_SIZE, 0, 1, 2, 0, 0)
        wal_frame = (
            struct.pack(">IIIIII", 2, 2, 1, 2, 0, 0)
            + encrypt_page_for_test(self.key, updated_second_page, 2)
        )
        plaintext, details = decrypt_database_bytes(
            encrypted_database, self.key, wal_bytes=wal_header + wal_frame
        )
        self.assertEqual(plaintext, bytes(self.page_one) + updated_second_page)
        self.assertEqual(details["wal_frames_applied"], 1)


class ContentTests(unittest.TestCase):
    def test_plain_utf8(self):
        self.assertEqual(decode_content("企业微信测试".encode()), "企业微信测试")

    def test_simple_protobuf_string(self):
        text = "项目进展正常".encode()
        payload = bytes([0x0A, len(text)]) + text
        self.assertEqual(decode_content(payload), "项目进展正常")


if __name__ == "__main__":
    unittest.main(verbosity=2)
