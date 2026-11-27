"""Mac `images` command on synthetic data: private-chat lookup, decoding and gaps.

No real vault, configuration, key directory or WeChat client is touched.
"""

from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
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

from Crypto.Cipher import AES

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import group_image_media as media
import vault_cli
from fixture_factory import ACCOUNT, ALICE, build

ARTIFACT_ROOT = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-chat-image-tests-")).resolve()
KEY_CODE = 42
AES_KEY = hashlib.md5(f"{KEY_CODE}wxid_owner".encode()).hexdigest()[:16].encode()
CLEAR_JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-jpeg-body"
CLEAR_PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-hd-png"


def encrypted_dat(clear: bytes, key: bytes = AES_KEY, xor_key: int = KEY_CODE) -> bytes:
    head, middle, tail = clear[:8], clear[8:-2], clear[-2:]
    payload = b"\x07\x08V2\x08\x07" + struct.pack("<I", 8) + struct.pack("<I", 2) + b"\x00"
    return payload + AES.new(key, AES.MODE_ECB).encrypt(head + bytes([8]) * 8) + middle + bytes(v ^ xor_key for v in tail)


def packed_info(file_hash: str) -> bytes:
    # Shape of the real column: protobuf framing around the ASCII attachment hash.
    return b"\x08\x03\x12\x20" + file_hash.encode() + b"\x18\x01"


def image_xml(cdn_md5: str) -> str:
    return f'<msg><img md5="{cdn_md5}" length="1024"/></msg>'


class ChatImagesTests(unittest.TestCase):
    def setUp(self):
        self.base = ARTIFACT_ROOT / (self._testMethodName + "-" + uuid.uuid4().hex)
        self.vault = self.base / "vault"
        build(self.vault)
        documents = self.base / "Documents"
        self.db_dir = documents / "xwechat_files" / ACCOUNT / "db_storage"
        self.db_dir.mkdir(parents=True)
        kvcomm = documents / "app_data/net/kvcomm"
        kvcomm.mkdir(parents=True)
        (kvcomm / f"key_{KEY_CODE}_fixture").write_bytes(b"")
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({"wxid": ACCOUNT}))
        self.cache = self.base / "cache"
        self.month = self.db_dir.parent / "msg/attach" / hashlib.md5(ALICE.encode()).hexdigest() / "2026-11/Img"
        self.month.mkdir(parents=True)

        self.hash_new, self.hash_old, self.hash_gone = "a" * 32, "b" * 32, "c" * 32
        cdn_md5 = "d" * 32
        (self.month / f"{self.hash_new}.dat").write_bytes(encrypted_dat(CLEAR_JPEG))
        (self.month / f"{self.hash_new}_h.dat").write_bytes(encrypted_dat(CLEAR_PNG))
        (self.month / f"{self.hash_new}_t.dat").write_bytes(encrypted_dat(CLEAR_JPEG))
        (self.month / f"{self.hash_old}.dat").write_bytes(encrypted_dat(CLEAR_JPEG))
        # A file named after the XML md5 must never be taken for the image.
        (self.month / f"{cdn_md5}.dat").write_bytes(encrypted_dat(CLEAR_JPEG))

        table = vault_cli.message_table(ALICE)
        rows = [
            (1, 1, 3, 1000, 2, image_xml(cdn_md5), packed_info(self.hash_old)),
            (2, 2, 1, 1001, 2, "文字消息", None),
            (3, 3, 3, 1002, 2, image_xml(cdn_md5), packed_info(self.hash_gone)),
            (4, 4, 3, 1003, 2, image_xml(cdn_md5), None),
            (5, 5, 3, 1004, 2, image_xml(cdn_md5), packed_info(self.hash_new)),
        ]
        con = sqlite3.connect(self.vault / "message/message_0.db")
        try:
            con.execute(f"CREATE TABLE [{table}](local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB,compress_content BLOB,WCDB_CT_message_content INTEGER,packed_info_data BLOB)")
            con.executemany(f"INSERT INTO [{table}] VALUES(?,?,?,?,?,?,NULL,0,?)", rows)
            con.commit()
        finally:
            con.close()

    def run_images(self, *argv, db_dir: Path | None = None, finder=None, include_identifiers: bool = False) -> dict:
        out = io.StringIO()
        prefix = ["--include-identifiers"] if include_identifiers else []
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(vault_cli, "load_config", return_value={}))
            stack.enter_context(mock.patch.object(vault_cli, "resolve_db_dir", return_value=db_dir or self.db_dir))
            stack.enter_context(mock.patch.object(vault_cli, "CONFIG_FILE", self.config))
            # Keep key discovery inside the fixture instead of the real home directory.
            stack.enter_context(mock.patch.object(Path, "home", return_value=self.base))
            if finder:
                stack.enter_context(mock.patch.object(media, "AttachmentFinder", finder))
            stack.enter_context(redirect_stdout(out))
            code = vault_cli.main([*prefix, "--decrypted-dir", str(self.vault), "images", ALICE, "--cache-dir", str(self.cache), *argv]) or 0
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def by_id(self, data: dict) -> dict:
        return {item["local_id"]: item for item in data["images"]}

    def test_private_chat_images_are_found_by_packed_hash_not_xml_md5(self):
        data = self.run_images()
        images = self.by_id(data)
        self.assertEqual(list(images), [1, 3, 4, 5])
        self.assertEqual(images[5]["status"], "found")
        self.assertEqual(images[5]["assets"], ["high-resolution", "original", "thumbnail"])
        self.assertEqual(images[1]["status"], "found")
        self.assertEqual(images[1]["assets"], ["original"])
        self.assertEqual(images[3]["status"], "missing")
        self.assertEqual(images[4]["status"], "no-hash")
        self.assertEqual(data["found"], 2)
        self.assertEqual(data["gaps"], [])
        self.assertNotIn("preview_path", images[5])
        self.assertFalse(self.cache.exists(), "listing alone must not write decoded images")

    def test_decode_prefers_hd_and_writes_owner_only_previews(self):
        data = self.run_images("--decode")
        images = self.by_id(data)
        self.assertEqual(data["decoded"], 2)
        preview = Path(images[5]["preview_path"])
        self.assertEqual(images[5]["asset_level"], "high-resolution")
        self.assertEqual(preview.read_bytes(), CLEAR_PNG)
        self.assertEqual(preview.parent, self.cache)
        self.assertEqual(stat.S_IMODE(preview.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cache.stat().st_mode), 0o700)
        self.assertEqual(Path(images[1]["preview_path"]).read_bytes(), CLEAR_JPEG)
        self.assertNotIn("preview_path", images[3])
        self.assertEqual(data["username"], vault_cli.HIDDEN_ID)

    def test_local_id_reaches_images_older_than_the_limit(self):
        data = self.run_images("--limit", "1", "--local-id", "1", "--decode")
        self.assertEqual([item["local_id"] for item in data["images"]], [1])
        self.assertEqual(Path(data["images"][0]["preview_path"]).read_bytes(), CLEAR_JPEG)
        self.assertEqual([item["local_id"] for item in self.run_images("--limit", "1")["images"]], [5])

    def test_wrong_key_reports_decode_error_without_a_preview(self):
        (self.month / f"{self.hash_old}.dat").write_bytes(encrypted_dat(CLEAR_JPEG, key=b"0" * 16))
        images = self.by_id(self.run_images("--decode", "--local-id", "1"))
        self.assertNotIn("preview_path", images[1])
        self.assertIn("没有可用的图片密钥", images[1]["decode_error"])

    def test_scan_budget_is_a_gap_not_a_missing_image(self):
        real_finder = media.AttachmentFinder
        data = self.run_images(finder=lambda root: real_finder(root, max_files_per_chat=0))
        self.assertEqual({item["status"] for item in data["images"] if item["local_id"] != 4}, {"scan-gap"})
        self.assertTrue(any("scan-budget-exceeded" in gap for gap in data["gaps"]))

    def test_missing_attachment_directory_is_reported(self):
        data = self.run_images("--decode", db_dir=self.base / "elsewhere/db_storage")
        self.assertEqual({item["status"] for item in data["images"]}, {"no-attach-dir"})
        self.assertTrue(data["gaps"])
        self.assertEqual(data["decoded"], 0)

    def test_text_output_names_the_private_cache(self):
        out = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(vault_cli, "load_config", return_value={}))
            stack.enter_context(mock.patch.object(vault_cli, "resolve_db_dir", return_value=self.db_dir))
            stack.enter_context(mock.patch.object(vault_cli, "CONFIG_FILE", self.config))
            stack.enter_context(mock.patch.object(Path, "home", return_value=self.base))
            stack.enter_context(redirect_stdout(out))
            vault_cli.main(["--decrypted-dir", str(self.vault), "images", ALICE, "--cache-dir", str(self.cache), "--decode", "--local-id", "5", "--format", "text"])
        text = out.getvalue()
        self.assertIn("含明文图片", text)
        self.assertIn("预览（高清）", text)
        self.assertNotIn(ALICE, text)


if __name__ == "__main__":
    unittest.main()
