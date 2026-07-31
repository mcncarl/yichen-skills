#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


douyin = load_module("content_archive_douyin", "douyin_download.py")
xhs = load_module("content_archive_xhs", "xiaohongshu_fetch.py")


class DouyinAdapterTests(unittest.TestCase):
    def test_normalizes_only_known_douyin_urls(self) -> None:
        self.assertEqual(
            douyin.normalize_url(
                "https://www.douyin.com/jingxuan?modal_id=7611845735025364265"
            ),
            "https://www.douyin.com/video/7611845735025364265",
        )
        with self.assertRaises(ValueError):
            douyin.normalize_url("https://example.com/video/7611845735025364265")

    def test_output_path_never_overwrites_video_or_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "clip.mp4"
            requested.write_bytes(b"old")
            self.assertEqual(
                douyin.choose_unique_output_path(str(requested)).name,
                "clip-run-1.mp4",
            )
            requested.unlink()
            Path(f"{requested}.metadata.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                douyin.choose_unique_output_path(str(requested)).name,
                "clip-run-1.mp4",
            )


class XiaohongshuAdapterTests(unittest.TestCase):
    def test_extracts_note_id_and_rejects_other_hosts(self) -> None:
        self.assertEqual(
            xhs.extract_note_id("https://www.xiaohongshu.com/explore/abc123"),
            "abc123",
        )
        with self.assertRaises(ValueError):
            xhs.extract_note_id("https://example.com/explore/abc123")

    def test_cookie_is_never_used_without_explicit_flag(self) -> None:
        old_value = os.environ.get("XHS_COOKIE")
        os.environ["XHS_COOKIE"] = "private-cookie"
        try:
            self.assertNotIn("Cookie", xhs.request_headers(include_cookie=False))
            self.assertEqual(
                xhs.request_headers(include_cookie=True)["Cookie"],
                "private-cookie",
            )
        finally:
            if old_value is None:
                os.environ.pop("XHS_COOKIE", None)
            else:
                os.environ["XHS_COOKIE"] = old_value

    def test_existing_output_directory_gets_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            requested = Path(directory) / "xhs_abc123"
            requested.mkdir()
            self.assertEqual(
                xhs.choose_unique_output_dir(requested).name,
                "xhs_abc123-run-1",
            )

    def test_meta_fallback_is_marked_incomplete(self) -> None:
        metadata = xhs.build_metadata_from_meta(
            {
                "og:title": "Example",
                "og:description": "Summary",
                "og:image": "https://sns-img.example/image.jpg",
            },
            "https://www.xiaohongshu.com/explore/abc123",
            "abc123",
        )
        self.assertEqual(metadata["extraction_source"], "meta_fallback")
        self.assertEqual(metadata["image_count"], 1)


if __name__ == "__main__":
    unittest.main()
