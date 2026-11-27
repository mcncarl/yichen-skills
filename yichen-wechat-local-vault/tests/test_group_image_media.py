"""Synthetic regressions for local group-image lookup and decoding."""

from __future__ import annotations

from Crypto.Cipher import AES
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import group_image_media as media

ARTIFACT_ROOT = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-group-image-tests-")).resolve()


@contextmanager
def fixture_directory():
    ARTIFACT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    yield tempfile.mkdtemp(prefix="group-image-media-", dir=ARTIFACT_ROOT)


class GroupImageMediaTests(unittest.TestCase):
    def test_attachment_lookup_is_exact_and_stays_in_one_chat(self):
        with fixture_directory() as directory:
            root = Path(directory)
            chat = "group-a"
            other = "group-b"
            target_md5 = "a" * 32
            target = root / hashlib.md5(chat.encode()).hexdigest() / "2026-10" / f"{target_md5}_h.dat"
            thumbnail = target.with_name(f"{target_md5}_t.dat")
            misleading = target.with_name(f"{target_md5}f_h.dat")
            other_chat = root / hashlib.md5(other.encode()).hexdigest() / "2026-10" / f"{target_md5}_h.dat"
            for path in (target, thumbnail, misleading, other_chat):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            finder = media.AttachmentFinder(root)
            self.assertEqual(finder.find(chat, target_md5), [target, thumbnail])
            self.assertEqual(finder.find(other, target_md5), [other_chat])
            self.assertEqual(finder.find(chat, "b" * 32), [])
            self.assertFalse(finder.gaps)

    def test_scan_budget_is_reported_as_a_gap(self):
        with fixture_directory() as directory:
            root = Path(directory)
            chat = "group-a"
            target_md5 = "a" * 32
            path = root / hashlib.md5(chat.encode()).hexdigest() / "2026-10" / f"{target_md5}.dat"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fixture")
            finder = media.AttachmentFinder(root, max_files_per_chat=0)
            self.assertEqual(finder.find(chat, target_md5), [])
            self.assertTrue(finder.scan_failed(chat))
            self.assertEqual(finder.gaps[0]["reason"], "scan-budget-exceeded")

    def test_key_candidates_and_preview_decode_use_local_files(self):
        with fixture_directory() as directory:
            root = Path(directory)
            db_base = root / "Documents/xwechat_files/wxid_example_suffix/db_storage"
            db_base.mkdir(parents=True)
            kvcomm = root / "Documents/app_data/net/kvcomm"
            kvcomm.mkdir(parents=True)
            (kvcomm / "key_42_fixture").write_bytes(b"")
            source_config = root / "config.json"
            source_config.write_text(json.dumps({"wxid": "wxid_example_suffix"}))
            expected_key = hashlib.md5(b"42wxid_example").hexdigest()[:16].encode()
            with mock.patch.object(Path, "home", return_value=root):
                keys = media.image_key_candidates(source_config, db_base)
            self.assertIn({"aesKey": expected_key, "xorKey": 42}, keys)

            clear = b"\x89PNG\r\n\x1a\n" + b"fixture-bytes"
            head, middle, tail = clear[:8], clear[8:-2], clear[-2:]
            encrypted = AES.new(expected_key, AES.MODE_ECB).encrypt(head + bytes([8]) * 8)
            payload = b"\x07\x08V2\x08\x07" + struct.pack("<I", 8) + struct.pack("<I", 2) + b"\x00"
            payload += encrypted + middle + bytes(value ^ 42 for value in tail)
            dat = root / "image_h.dat"
            dat.write_bytes(payload)
            key = next(value for value in keys if value["aesKey"] == expected_key and value["xorKey"] == 42)
            preview = media.decode_image_dat_to_preview(dat, key, {"chatKey": "fixture", "messageLocalId": 1}, root / "cache")
            self.assertEqual(Path(preview["previewPath"]).read_bytes(), clear)
            self.assertEqual(preview["assetLevel"], "high-resolution")


if __name__ == "__main__":
    unittest.main()
