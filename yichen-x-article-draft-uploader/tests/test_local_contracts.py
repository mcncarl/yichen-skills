from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    path = SKILL_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


parser = load_module("x_article_parse_markdown", "scripts/parse_markdown.py")
uploader = load_module("x_article_upload", "scripts/upload_markdown_to_x_article.py")
cookie_exporter = load_module(
    "x_article_cookie_exporter",
    "scripts/export_x_cookies_from_chrome.py",
)


class CookieExporterDomainTests(unittest.TestCase):
    def test_matches_only_exact_hosts_and_label_boundaries(self):
        self.assertTrue(cookie_exporter.host_matches_domain(".x.com", "x.com"))
        self.assertTrue(cookie_exporter.host_matches_domain("api.x.com", "x.com"))
        self.assertTrue(cookie_exporter.host_matches_domain(".twitter.com", "twitter.com"))
        self.assertFalse(cookie_exporter.host_matches_domain("notx.com", "x.com"))
        self.assertFalse(cookie_exporter.host_matches_domain("x.com.evil.example", "x.com"))
        self.assertFalse(cookie_exporter.host_matches_domain("twitter.com.evil.example", "twitter.com"))


class FinalStatusOutputTests(unittest.TestCase):
    def test_final_status_is_bounded_and_repeats_url_immediately_before_marker(self):
        draft_url = "https://x.com/compose/articles/edit/example-draft-id"
        with mock.patch("builtins.print") as print_mock:
            uploader.emit_final_status(draft_url, True)

        self.assertEqual(
            print_mock.call_args_list,
            [
                mock.call("draft_url=" + draft_url),
                mock.call("RESULT_OK", True),
            ],
        )


class PublicReleaseSafetyTests(unittest.TestCase):
    def test_release_is_versioned_and_docs_pin_the_tag(self):
        version = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertEqual(version, "1.0.1")
        self.assertIn("x-article-draft-uploader-v1.0.1", readme)
        self.assertIn("skills@1.5.22", readme)
        self.assertNotIn("tree/main/yichen-x-article-draft-uploader", readme)

        license_text = (SKILL_ROOT / "LICENSE").read_text(encoding="utf-8")
        instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Commercial use requires prior explicit written authorization", license_text)
        self.assertIn("yichen365ai", license_text)
        self.assertIn("商业用途，必须事先取得作者明确的书面授权", instructions)
        self.assertIn("不改变 Ailu 核心的 AGPL-3.0-or-later 许可", instructions)

        requirements = (SKILL_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(requirements, ["playwright==1.58.0", "pycryptodome==3.23.0"])

    def test_existing_draft_replacement_requires_explicit_user_confirmation(self):
        instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("只有用户当轮明确确认", instructions)
        self.assertIn("--draft-url", instructions)
        self.assertIn("--confirm-existing-draft-write", instructions)
        self.assertIn("会清空这个草稿已有的", instructions)
        self.assertIn("标题、正文、表格、正文媒体和封面", instructions)


class ExistingDraftAndCookieBoundaryTests(unittest.TestCase):
    def test_draft_url_is_restricted_to_exact_x_edit_urls(self):
        self.assertTrue(
            uploader.is_allowed_x_draft_url(
                "https://x.com/compose/articles/edit/example-draft-id"
            )
        )
        for value in (
            "http://x.com/compose/articles/edit/123",
            "https://x.com.evil.example/compose/articles/edit/123",
            "https://x.com/compose/articles/edit/123?next=https://example.com",
            "https://x.com/home",
            "file:///etc/passwd",
        ):
            self.assertFalse(uploader.is_allowed_x_draft_url(value), value)

        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(
            encoding="utf-8"
        )
        confirmation_guard = source.index("if not args.confirm_existing_draft_write:")
        markdown_read = source.index("markdown_file = Path(args.markdown_file).expanduser()")
        self.assertLess(confirmation_guard, markdown_read)

    def test_cookie_loader_accepts_private_x_only_records(self):
        records = [
            {"name": "auth_token", "value": "synthetic-auth", "domain": ".x.com"},
            {"name": "ct0", "value": "synthetic-csrf", "domain": ".x.com"},
            {"name": "twid", "value": "synthetic-id", "domain": ".twitter.com"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookies.json"
            cookie_file.write_text(json.dumps(records), encoding="utf-8")
            os.chmod(cookie_file, 0o600)

            self.assertEqual(uploader.load_cookies(cookie_file), records)

    def test_cookie_loader_rejects_non_x_domain_and_broad_permissions(self):
        valid = [
            {"name": "auth_token", "value": "synthetic-auth", "domain": ".x.com"},
            {"name": "ct0", "value": "synthetic-csrf", "domain": ".x.com"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookies.json"
            cookie_file.write_text(
                json.dumps(valid + [{"name": "sid", "value": "synthetic", "domain": "example.com"}]),
                encoding="utf-8",
            )
            os.chmod(cookie_file, 0o600)
            with self.assertRaisesRegex(ValueError, "outside x.com/twitter.com"):
                uploader.load_cookies(cookie_file)

            cookie_file.write_text(json.dumps(valid), encoding="utf-8")
            os.chmod(cookie_file, 0o644)
            with self.assertRaisesRegex(ValueError, "chmod 600"):
                uploader.load_cookies(cookie_file)

            os.chmod(cookie_file, 0o600)
            cookie_file.write_text(
                json.dumps([{"name": "auth_token", "value": "synthetic-auth", "domain": ".x.com"}]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "ct0"):
                uploader.load_cookies(cookie_file)

    def test_default_artifacts_live_in_private_ailu_home_not_shared_tmp(self):
        self.assertEqual(
            uploader.DEFAULT_ARTIFACT_DIRECTORY,
            Path.home() / ".ailu" / "runs" / "x-article-draft-uploader",
        )
        for target in (
            uploader.DEFAULT_RESULT_JSON,
            uploader.DEFAULT_DRAFT_URL_OUTPUT,
            uploader.DEFAULT_SCREENSHOT,
        ):
            self.assertEqual(target.parent, uploader.DEFAULT_ARTIFACT_DIRECTORY)
            self.assertNotEqual(target.parent, Path("/tmp"))

    def test_artifact_targets_reject_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular.txt"
            regular.write_text("synthetic", encoding="utf-8")
            link = root / "result.json"
            link.symlink_to(regular)

            with self.assertRaisesRegex(ValueError, "regular file"):
                uploader.validate_artifact_target(link)


class HostedCoverFetchTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def response(url: str, content_type: str = "image/jpeg", body: bytes = b"image"):
        response = mock.MagicMock()
        response.ok = True
        response.url = url
        response.headers = {
            "content-type": content_type,
            "content-length": str(len(body)),
        }
        response.body = mock.AsyncMock(return_value=body)
        return response

    async def test_api_request_success_does_not_open_temporary_page(self):
        source_url = "https://pbs.twimg.com/media/cover.jpg"
        response = self.response(source_url, body=b"direct")
        page = mock.MagicMock()
        page.context.request.get = mock.AsyncMock(return_value=response)
        page.context.new_page = mock.AsyncMock()

        fetched = await uploader.fetch_hosted_cover_image_bytes(page, source_url)

        self.assertEqual(fetched, (b"direct", "image/jpeg", "context-fetch"))
        page.context.new_page.assert_not_awaited()

    async def test_api_request_failure_uses_same_browser_context_and_closes_page(self):
        source_url = "https://pbs.twimg.com/media/cover.jpg"
        response = self.response(source_url, body=b"browser")
        image_page = mock.MagicMock()
        image_page.goto = mock.AsyncMock(return_value=response)
        image_page.close = mock.AsyncMock()
        page = mock.MagicMock()
        page.context.request.get = mock.AsyncMock(side_effect=OSError("connection reset"))
        page.context.new_page = mock.AsyncMock(return_value=image_page)

        fetched = await uploader.fetch_hosted_cover_image_bytes(page, source_url)

        self.assertEqual(fetched, (b"browser", "image/jpeg", "browser-page-fetch"))
        image_page.goto.assert_awaited_once_with(
            source_url,
            wait_until="commit",
            timeout=30_000,
        )
        image_page.close.assert_awaited_once()

    async def test_redirect_to_non_x_host_is_rejected_without_reading_body(self):
        source_url = "https://pbs.twimg.com/media/cover.jpg"
        redirected = self.response("https://example.com/cover.jpg")
        image_page = mock.MagicMock()
        image_page.goto = mock.AsyncMock(return_value=redirected)
        image_page.close = mock.AsyncMock()
        page = mock.MagicMock()
        page.context.request.get = mock.AsyncMock(return_value=redirected)
        page.context.new_page = mock.AsyncMock(return_value=image_page)

        fetched = await uploader.fetch_hosted_cover_image_bytes(page, source_url)

        self.assertIsNone(fetched)
        redirected.body.assert_not_awaited()
        image_page.close.assert_awaited_once()

    async def test_non_image_and_oversized_responses_are_rejected(self):
        non_image = self.response(
            "https://pbs.twimg.com/media/cover.jpg",
            content_type="text/html",
        )
        self.assertIsNone(await uploader.read_bounded_x_image_response(non_image))
        non_image.body.assert_not_awaited()

        oversized = self.response("https://pbs.twimg.com/media/cover.jpg")
        oversized.headers["content-length"] = str(uploader.MAX_HOSTED_COVER_BYTES + 1)
        self.assertIsNone(await uploader.read_bounded_x_image_response(oversized))
        oversized.body.assert_not_awaited()


class OptionalDiagnosticArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_screenshot_failure_is_warning_not_exception(self):
        page = mock.MagicMock()
        page.screenshot = mock.AsyncMock(side_effect=OSError("renderer unavailable"))

        evidence = await uploader.capture_optional_screenshot(page, "/tmp/final.png")

        self.assertFalse(evidence["written"])
        self.assertEqual(evidence["warning"]["type"], "diagnostic_screenshot_failed")
        self.assertEqual(evidence["error_type"], "OSError")
        page.screenshot.assert_awaited_once_with(path="/tmp/final.png", full_page=True)


class BalancedImageParsingTests(unittest.TestCase):
    def test_image_at_parsed_body_start_does_not_use_removed_h1_as_anchor(self):
        markdown = "# **Removed title**\n![](body.png)\nFirst surviving paragraph."
        data = {
            "cover_image": None,
            "content_images": [
                {
                    "path": "/local/body.png",
                    "original_path": "/local/body.png",
                    "exists": True,
                    "block_index": 0,
                    "text_before": "",
                    "after_text": "",
                    "source_occurrence": 1,
                }
            ],
        }
        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(data, Path("/local/article.md"))

        self.assertEqual(items[0]["placement"], uploader.MEDIA_PLACEMENT_COMPOSER_START)
        self.assertEqual(items[0]["expected_anchor"], "")
        self.assertEqual(items[0]["candidates"], [])

    def test_body_start_placement_is_not_rejected_as_a_weak_anchor(self):
        content_image = {
            "index": 1,
            "line": 2,
            "path": "/local/body.png",
            "exists": True,
            "placement": uploader.MEDIA_PLACEMENT_COMPOSER_START,
            "expected_anchor": "",
            "candidates": [],
        }
        data = {
            "cover_image": None,
            "expected_image_count": 1,
            "tables": [],
        }
        cover_policy = {
            "starts_with_image": False,
            "first_content_line": 1,
            "first_content_preview": "# Title",
        }
        with mock.patch.object(Path, "is_file", return_value=True):
            preflight = uploader.validate_preflight(
                data,
                cover_policy,
                [content_image],
                "# Title\n![](body.png)\nBody",
            )

        self.assertFalse(
            any(error.get("type") == "weak_image_anchor" for error in preflight["errors"])
        )

    def test_consecutive_composer_start_images_are_allowed_only_as_a_prefix(self):
        items = [
            {
                "index": 1,
                "path": "/local/start-1.png",
                "exists": True,
                "placement": uploader.MEDIA_PLACEMENT_COMPOSER_START,
                "expected_anchor": "",
                "candidates": [],
            },
            {
                "index": 2,
                "path": "/local/start-2.png",
                "exists": True,
                "placement": uploader.MEDIA_PLACEMENT_COMPOSER_START,
                "expected_anchor": "",
                "candidates": [],
            },
            {
                "index": 3,
                "path": "/local/later.png",
                "exists": True,
                "placement": uploader.MEDIA_PLACEMENT_AFTER_ANCHOR,
                "expected_anchor": "后续正文锚点",
                "candidates": ["后续正文锚点"],
            },
        ]
        cover_policy = {
            "starts_with_image": False,
            "first_content_line": 1,
            "first_content_preview": "正文",
        }
        with mock.patch.object(Path, "is_file", return_value=True):
            valid = uploader.validate_preflight(
                {"cover_image": None, "expected_image_count": 3, "tables": []},
                cover_policy,
                items,
                "正文",
            )
            invalid = uploader.validate_preflight(
                {"cover_image": None, "expected_image_count": 3, "tables": []},
                cover_policy,
                [items[0], items[2], dict(items[1], index=3)],
                "正文",
            )
        self.assertFalse(any(error["type"] == "composer_start_not_prefix" for error in valid["errors"]))
        self.assertTrue(any(error["type"] == "composer_start_not_prefix" for error in invalid["errors"]))

    def test_first_non_cover_body_image_keeps_its_real_nonzero_block_position(self):
        markdown = "正文锚点\n\n![](body.png)\n\n后续正文"
        data = {
            "cover_image": "/local/body.png",
            "cover_image_item": {
                "path": "/local/body.png",
                "original_path": "/local/body.png",
                "exists": True,
                "block_index": 1,
                "after_text": "正文锚点",
                "text_before": "正文锚点",
                "source_occurrence": 1,
            },
            "content_images": [],
        }
        with (
            mock.patch.object(Path, "read_text", return_value=markdown),
            mock.patch.object(Path, "exists", return_value=True),
        ):
            items = uploader.build_content_images(
                data,
                Path("/local/article.md"),
                include_cover_as_body=True,
            )
        self.assertEqual(items[0]["placement"], uploader.MEDIA_PLACEMENT_AFTER_ANCHOR)
        self.assertEqual(items[0]["expected_anchor"], "正文锚点")

    def test_reserved_composer_start_marker_is_rejected_before_opening_x(self):
        preflight = uploader.validate_preflight(
            {"cover_image": None, "expected_image_count": 0, "tables": []},
            {
                "starts_with_image": False,
                "first_content_line": 1,
                "first_content_preview": "Body",
            },
            [],
            f"正文里意外出现 {uploader.MEDIA_START_MARKER}",
        )
        self.assertTrue(
            any(error.get("type") == "reserved_internal_marker" for error in preflight["errors"])
        )

    def test_multiple_balanced_images_on_one_line_are_independent(self):
        line = "前文 ![图 [一]](assets/图 (1).png) 中间 ![图二](assets/two.png) 后文"
        images = parser.scan_inline_markdown_images(line)
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["alt"], "图 [一]")
        self.assertEqual(images[0]["destination"], "assets/图 (1).png")
        self.assertEqual(images[1]["destination"], "assets/two.png")
        self.assertLess(images[0]["end"], images[1]["start"])

        cleaned, fixes = parser.clean_markdown_errors(line)
        self.assertEqual(
            cleaned.splitlines(),
            ["前文", "![图 [一]](assets/图 (1).png)", "中间", "![图二](assets/two.png)", "后文"],
        )
        self.assertTrue(any("2 inline image" in fix for fix in fixes))

    def test_escaped_and_fenced_images_are_not_extracted(self):
        markdown = "\\![忽略](escaped.png)\n\n```md\n![代码](code.png)\n```\n\n![正文](body.png)"
        cleaned, _ = parser.clean_markdown_errors(markdown)
        blocks = parser.split_into_blocks(cleaned)
        images = [parser._parse_inline_image_block(block) for block in blocks]
        images = [image for image in images if image]
        self.assertEqual(images, [("正文", "body.png")])

    def test_twelve_same_line_images_keep_source_order(self):
        line = " ".join(f"![图{i}](assets/image ({i}).png)" for i in range(1, 13))
        images = parser.scan_inline_markdown_images(line)
        self.assertEqual(len(images), 12)
        self.assertEqual(
            [image["destination"] for image in images],
            [f"assets/image ({i}).png" for i in range(1, 13)],
        )
        cleaned, _ = parser.clean_markdown_errors(line)
        self.assertEqual(cleaned.splitlines(), [image["markdown"] for image in images])

    def test_same_line_images_use_their_parser_anchors(self):
        data = {
            "cover_image": None,
            "content_images": [
                {"path": "/local/one.png", "after_text": "第一张前文", "text_before": "第一张前文"},
                {"path": "/local/two.png", "after_text": "第二张前文", "text_before": "第二张前文"},
            ],
        }
        source = "总锚点\n第一张前文 ![一](one.png) 第二张前文 ![二](two.png)"
        with mock.patch.object(Path, "read_text", return_value=source):
            items = uploader.build_content_images(data, Path("/virtual/article.md"))
        self.assertEqual([item["expected_anchor"] for item in items], ["第一张前文", "第二张前文"])

    def test_two_images_on_one_line_keep_their_own_complete_preceding_segments(self):
        first_anchor = "第一张图片之前的完整长段落，不应该和第二张图片共享整行末尾文字。"
        second_anchor = "第二张图片只绑定两张图片之间的这一段完整可见文字。"
        markdown = f"{first_anchor}![](one.png){second_anchor}![](two.png)"
        cleaned, _ = parser.clean_markdown_errors(markdown)
        with mock.patch.object(
            parser,
            "find_image_file",
            side_effect=lambda resolved, _filename, _base: (resolved, True),
        ):
            images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                cleaned,
                Path("/virtual"),
            )
        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(
                {"cover_image": None, "content_images": images},
                Path("/virtual/article.md"),
            )
        self.assertEqual(
            [item["expected_anchor"] for item in items],
            [first_anchor, second_anchor],
        )
        self.assertEqual(
            uploader.find_line_anchor(
                markdown.splitlines(),
                "/virtual/one.png",
                source_path="/virtual/one.png",
                markdown_dir=Path("/virtual"),
            )[0],
            first_anchor,
        )
        self.assertEqual(
            uploader.find_line_anchor(
                markdown.splitlines(),
                "/virtual/two.png",
                source_path="/virtual/two.png",
                markdown_dir=Path("/virtual"),
            )[0],
            second_anchor,
        )

    def test_inline_then_image_only_keeps_full_anchor_without_prior_image_markup(self):
        anchor = (
            "直接在 obsidian 里面打开终端，并且定位到当前obsidian 仓库，非常方便，"
            "里面可以直接打开 claude code，然后对文章进行修改。"
        )
        markdown = f"{anchor}![](one.png)\n![](two.png)"
        cleaned, _ = parser.clean_markdown_errors(markdown)
        with mock.patch.object(
            parser,
            "find_image_file",
            side_effect=lambda resolved, _filename, _base: (resolved, True),
        ):
            images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                cleaned,
                Path("/virtual"),
            )
        self.assertEqual([image["text_before"] for image in images], [anchor, anchor])
        self.assertTrue(all("![](" not in image["text_before"] for image in images))

        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(
                {"cover_image": None, "content_images": images},
                Path("/virtual/article.md"),
            )
        self.assertEqual([item["expected_anchor"] for item in items], [anchor, anchor])
        self.assertTrue(all("![](" not in item["expected_anchor"] for item in items))
        self.assertEqual(
            uploader.find_line_anchor(
                markdown.splitlines(),
                "/virtual/two.png",
                source_path="/virtual/two.png",
                markdown_dir=Path("/virtual"),
            )[0],
            anchor,
        )

    def test_anchor_metadata_has_no_50_character_boundary_or_unicode_truncation(self):
        anchors = (
            "甲" * 50,
            "乙" * 51,
            ("完整🙂段落e\u0301与扩展字符𠀀" * 18) + "结束。",
        )
        for anchor in anchors:
            with self.subTest(length=len(anchor), tail=anchor[-8:]):
                markdown = f"{anchor}![](one.png)\n![](two.png)"
                cleaned, _ = parser.clean_markdown_errors(markdown)
                with mock.patch.object(
                    parser,
                    "find_image_file",
                    side_effect=lambda resolved, _filename, _base: (resolved, True),
                ):
                    images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                        cleaned,
                        Path("/virtual"),
                    )
                self.assertEqual([image["text_before"] for image in images], [anchor, anchor])
                self.assertEqual([image["after_text"] for image in images], [anchor, anchor])

    def test_soft_wrapped_paragraph_uses_complete_nearest_line_for_consecutive_images(self):
        nearest = "第二行是完整的最近语义锚点，而且明确超过五十个字符，不能回退到第一行或截掉尾部。"
        markdown = f"第一行只是同一段的较早内容\n{nearest}![](one.png)\n![](two.png)"
        cleaned, _ = parser.clean_markdown_errors(markdown)
        with mock.patch.object(
            parser,
            "find_image_file",
            side_effect=lambda resolved, _filename, _base: (resolved, True),
        ):
            images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                cleaned,
                Path("/virtual"),
            )
        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(
                {"cover_image": None, "content_images": images},
                Path("/virtual/article.md"),
            )
        self.assertEqual([item["expected_anchor"] for item in items], [nearest, nearest])

    def test_repeated_path_keeps_distinct_occurrence_anchors_through_parser_chain(self):
        markdown = (
            "![封面](cover.png)\n\n"
            "锚点甲：第一次出现\n\n"
            "![重复图](same.png)\n\n"
            "锚点乙：第二次出现\n\n"
            "![重复图](same.png)"
        )
        with mock.patch.object(
            parser,
            "find_image_file",
            side_effect=lambda resolved, _filename, _base: (resolved, True),
        ):
            images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                markdown,
                Path("/virtual"),
            )
        self.assertEqual([item["source_occurrence"] for item in images[1:]], [1, 2])

        data = {
            "cover_image": images[0]["path"],
            "content_images": images[1:],
        }
        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(data, Path("/virtual/article.md"))
        self.assertEqual([item["line"] for item in items], [5, 9])
        self.assertEqual(
            [item["expected_anchor"] for item in items],
            ["锚点甲：第一次出现", "锚点乙：第二次出现"],
        )

        duplicate_signature = "visual-dhash-v1:" + "a" * 64
        contract = uploader.build_source_media_contract(
            items,
            [{"sourceSignature": duplicate_signature}, {"sourceSignature": duplicate_signature}],
        )
        observed = [
            {
                "sourceSignature": duplicate_signature,
                "naturalWidth": 100,
                "naturalHeight": 100,
                "mediaIndex": index,
                "anchorBefore": item["expected_anchor"],
            }
            for index, item in enumerate(items)
        ]
        self.assertTrue(uploader.validate_composer_media_evidence(observed, contract)["valid"])

    def test_same_basename_in_different_directories_keeps_distinct_anchors(self):
        markdown = (
            "锚点甲：目录 A\n\n"
            "![甲图](dir-a/same.png)\n\n"
            "锚点乙：目录 B\n\n"
            "![乙图](dir-b/same.png)"
        )
        with mock.patch.object(
            parser,
            "find_image_file",
            side_effect=lambda resolved, _filename, _base: (resolved, True),
        ):
            images, _dividers, _clean, _count = parser.extract_images_and_dividers(
                markdown,
                Path("/virtual"),
            )
        self.assertEqual([item["source_occurrence"] for item in images], [1, 1])

        data = {"cover_image": None, "content_images": images}
        with mock.patch.object(Path, "read_text", return_value=markdown):
            items = uploader.build_content_images(data, Path("/virtual/article.md"))
        self.assertEqual([item["line"] for item in items], [3, 7])
        self.assertEqual(
            [item["expected_anchor"] for item in items],
            ["锚点甲：目录 A", "锚点乙：目录 B"],
        )


class TablePersistenceContractTests(unittest.TestCase):
    def test_table_contract_requires_exact_non_empty_matrix(self):
        table = {
            "rows": [["标题 **一**", "标题二"], ["[链接](https://example.com)", ""]],
            "row_count": 2,
            "column_count": 2,
        }
        contract = uploader.validate_table_contract(table)
        self.assertTrue(contract["valid"])
        self.assertEqual(contract["matrix"], [["标题 一", "标题二"], ["链接", ""]])
        self.assertEqual(contract["non_empty_cells"], 3)

        empty = uploader.validate_table_contract(
            {"rows": [["", ""], ["", ""]], "row_count": 2, "column_count": 2}
        )
        self.assertFalse(empty["valid"])
        self.assertEqual(empty["non_empty_cells"], 0)

    def test_dimension_drift_is_rejected(self):
        contract = uploader.validate_table_contract(
            {"rows": [["A", "B"], ["C"]], "row_count": 2, "column_count": 2}
        )
        self.assertFalse(contract["valid"])


class AnchorSemanticNormalizationTests(unittest.TestCase):
    def test_shared_cross_language_normalization_and_binding_vectors(self):
        fixture = json.loads(
            (SKILL_ROOT / "tests/anchor_normalization_vectors.json").read_text(encoding="utf-8")
        )
        for vector in fixture["normalization_vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(
                    uploader.normalize_media_anchor(vector["source"]),
                    vector["normalized_source"],
                )
                self.assertEqual(
                    uploader.normalize_visible_media_anchor(vector["actual"]),
                    vector["normalized_actual"],
                )
                self.assertEqual(
                    uploader.media_anchor_matches(vector["source"], vector["actual"]),
                    vector["matches"],
                )
        for vector in fixture["binding_vectors"]:
            with self.subTest(binding=vector["name"]):
                self.assertEqual(
                    uploader.media_identity_key(
                        vector["source_signature"],
                        vector["occurrence"],
                        vector["anchor"],
                        vector["dom_order"],
                    ),
                    vector["binding_key"],
                )

    def test_long_bold_anchor_accepts_only_the_merged_dom_prefix_shape(self):
        expected = (
            "这个公开测试段落用于说明插件会创建可编辑的流程图，然后"
            "**保留完整的粗体锚点文本**，并在编辑器合并前缀后继续精确定位正文图片。"
        )
        visible = (
            "这个公开测试段落用于说明插件会创建可编辑的流程图，然后"
            "保留完整的粗体锚点文本，并在编辑器合并前缀后继续精确定位正文图片。"
        )

        self.assertTrue(uploader.media_anchor_matches(expected, "更早的测试段落。 " + visible))
        self.assertFalse(
            uploader.media_anchor_matches(expected, "更早的测试段落。 " + visible + " 后续错误段落")
        )
        self.assertFalse(uploader.media_anchor_matches(expected, visible[:-8]))

    def test_full_long_anchor_rejects_truncated_prefix_and_wrong_paragraph(self):
        expected = "长段落语义锚点" * 12 + "唯一结尾。"
        self.assertTrue(uploader.media_anchor_matches(expected, expected))
        self.assertTrue(uploader.media_anchor_matches(expected, "更早正文 " + expected))
        self.assertFalse(uploader.media_anchor_matches(expected, expected[:50]))
        self.assertFalse(uploader.media_anchor_matches(expected, expected + " 错误后续段落"))
        self.assertFalse(uploader.media_anchor_matches(expected, "完全不同的段落"))

    def test_source_and_dom_normalizers_share_visible_semantics_without_reparsing_dom(self):
        vectors = [
            ("**同文**", "同文"),
            ("__同文__", "同文"),
            ("*同文*", "同文"),
            ("_同文_", "同文"),
            ("~~同文~~", "同文"),
            ("[同文](https://example.com/a_(b))", "同文"),
            ("[同文][ref]", "同文"),
            ("<https://example.com/a>", "https://example.com/a"),
            ("<me@example.com>", "me@example.com"),
            ("`**literal**`", "**literal**"),
            (r"这是\*字面星号\*", "这是*字面星号*"),
            (r"保留\&copy;", "保留&copy;"),
            ("实体 &copy;", "实体 ©"),
            ("Cafe\u0301", "Café"),
            ("A\u200b\u200c\u200d\u2060\ufeffB", "AB"),
        ]
        for source, visible in vectors:
            with self.subTest(source=source):
                self.assertEqual(
                    uploader.normalize_media_anchor(source),
                    uploader.normalize_visible_media_anchor(visible),
                )
                self.assertTrue(uploader.media_anchor_matches(source, visible))

    def test_semantically_duplicate_anchors_are_rejected_before_opening_x(self):
        content_images = [
            {
                "index": 1,
                "path": "/virtual/one.png",
                "exists": True,
                "expected_anchor": "**相同锚点文本**",
                "candidates": ["**相同锚点文本**"],
            },
            {
                "index": 2,
                "path": "/virtual/two.png",
                "exists": True,
                "expected_anchor": "中间锚点",
                "candidates": ["中间锚点"],
            },
            {
                "index": 3,
                "path": "/virtual/three.png",
                "exists": True,
                "expected_anchor": "[相同锚点文本](https://example.com/other)",
                "candidates": ["[相同锚点文本](https://example.com/other)"],
            },
        ]
        with mock.patch.object(uploader.Path, "is_file", return_value=True):
            preflight = uploader.validate_preflight(
                {"expected_image_count": 3, "content_images": content_images},
                {"starts_with_image": False, "first_content_line": 1, "first_content_preview": "正文"},
                content_images,
                "正文",
            )
        reused = [error for error in preflight["errors"] if error["type"] == "reused_anchor"]
        self.assertEqual(len(reused), 1)
        self.assertEqual(reused[0]["normalized_anchor"], "相同锚点文本")

    def test_three_adjacent_semantic_duplicates_are_allowed_by_occurrence_and_order(self):
        content_images = [
            {
                "index": index,
                "path": f"/virtual/{index}.png",
                "exists": True,
                "expected_anchor": anchor,
                "candidates": [anchor],
            }
            for index, anchor in enumerate(
                (
                    "**连续图片锚点**",
                    "__连续图片锚点__",
                    "[连续图片锚点](https://example.com)",
                ),
                1,
            )
        ]
        with mock.patch.object(uploader.Path, "is_file", return_value=True):
            preflight = uploader.validate_preflight(
                {"expected_image_count": 3},
                {"starts_with_image": False, "first_content_line": 1, "first_content_preview": "正文"},
                content_images,
                "正文",
            )
        self.assertFalse(any(error["type"] == "reused_anchor" for error in preflight["errors"]))

    def test_transient_anchor_can_defer_but_wrong_final_position_still_fails(self):
        signature = "visual-dhash-v1:" + "a" * 64
        expected = uploader.build_source_media_contract(
            [{"path": "/local/image.png", "expected_anchor": "**正确锚点**"}],
            [{"sourceSignature": signature}],
        )
        transient = {
            "sourceSignature": signature,
            "naturalWidth": 800,
            "naturalHeight": 600,
            "mediaIndex": 0,
            "anchorBefore": "DOM 暂时没有稳定锚点",
        }
        binding = uploader.identify_single_new_media_signature([], [transient], expected[0], expected)
        self.assertFalse(binding["valid"])
        self.assertTrue(binding["identity_binding_valid"])
        self.assertTrue(binding["position_verification_deferred"])
        self.assertTrue(binding["eligible_for_final_verification"])
        transient_evidence = uploader.validate_composer_media_evidence([transient], expected)
        self.assertFalse(transient_evidence["valid"])
        self.assertTrue(uploader.composer_media_identity_is_valid(transient_evidence))

        persisted = dict(transient, anchorBefore="上一行前缀 正确锚点")
        persisted_evidence = uploader.validate_composer_media_evidence([persisted], expected)
        self.assertTrue(persisted_evidence["valid"])
        self.assertTrue(
            uploader.validate_media_phase_persistence(
                transient_evidence,
                persisted_evidence,
            )["valid"]
        )


class MarkdownRenderingRegressionTests(unittest.TestCase):
    def test_common_inline_markdown_is_rendered_without_losing_visible_text(self):
        markdown = (
            "普通 **粗体** __粗体二__ *斜体* _斜体二_ ~~删除~~，"
            "`**literal**`，\\*字面星号\\*，"
            "[括号链接](https://example.com/a_(b))。"
        )
        rendered = parser.markdown_to_html(markdown)
        visible = uploader.plain_text_from_html(rendered)
        self.assertEqual(
            " ".join(visible.split()),
            "普通 粗体 粗体二 斜体 斜体二 删除，**literal**，*字面星号*，括号链接。",
        )
        self.assertIn('href="https://example.com/a_(b)"', rendered)

    def test_reference_and_autolinks_render_as_visible_links(self):
        rendered = parser.markdown_to_html(
            "看 [文档][doc]、[折叠][]、<https://example.com/a?q=1&b=2> 和 "
            "<me@example.com>。\n\n"
            "[doc]: https://example.com/doc\n"
            "[折叠]: https://example.com/collapsed"
        )
        visible = " ".join(uploader.plain_text_from_html(rendered).split())
        self.assertEqual(
            visible,
            "看 文档、折叠、https://example.com/a?q=1&b=2 和 me@example.com。",
        )
        self.assertIn('href="mailto:me@example.com"', rendered)

    def test_entities_escaped_entities_and_unclosed_angle_text_are_lossless(self):
        rendered = parser.markdown_to_html(
            "实体 &copy;；字面 \\&copy;；开头 <tagless 后面的文字不能消失"
        )
        visible = " ".join(uploader.plain_text_from_html(rendered).split())
        self.assertEqual(visible, "实体 ©；字面 &copy;；开头 <tagless 后面的文字不能消失")
        self.assertIn("&lt;tagless", rendered)

    def test_different_filename_title_keeps_source_h1_as_body_content(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            article = Path(directory) / "Ailu入门教程.md"
            article.write_text("# 正文章节标题\n\n这里是完整正文。", encoding="utf-8")
            result = parser.parse_markdown_file(str(article))
        self.assertEqual(result["title"], "Ailu入门教程")
        self.assertIn("<h2>正文章节标题</h2>", result["html"])
        self.assertIn("这里是完整正文。", result["html"])

    def test_semantically_equal_filename_title_does_not_duplicate_source_h1(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            article = Path(directory) / "Ailu入门教程.md"
            article.write_text("# **Ailu入门教程**\n\n这里是完整正文。", encoding="utf-8")
            result = parser.parse_markdown_file(str(article))
        self.assertEqual(result["title"], "Ailu入门教程")
        self.assertNotIn("<h2><strong>Ailu入门教程</strong></h2>", result["html"])
        self.assertEqual(uploader.plain_text_from_html(result["html"]), "这里是完整正文。")


class ComposerMediaEvidenceTests(unittest.TestCase):
    @staticmethod
    def patterned_sample(delta: int = 0, invert: bool = False) -> str:
        raw = bytearray()
        for index in range(64):
            channels = (
                48 + (index * 29) % 160,
                48 + (index * 43) % 160,
                48 + (index * 61) % 160,
            )
            for value in channels:
                adjusted = 255 - value if invert else value
                raw.append(max(0, min(255, adjusted + delta)))
        return "visual-rgb8-v1:" + raw.hex()

    @staticmethod
    def flat_sample(value: int) -> str:
        return "visual-rgb8-v1:" + (bytes([value, value, value]) * 64).hex()

    def setUp(self):
        content_images = [
            {"path": "/local/one.png", "expected_anchor": "第一张图说明"},
            {"path": "/local/two.png", "expected_anchor": "第二张图说明"},
        ]
        self.expected = uploader.build_source_media_contract(
            content_images,
            [
                {"sourceSignature": "visual-dhash-v1:" + "a" * 64},
                {"sourceSignature": "visual-dhash-v1:" + "b" * 64},
            ],
        )
        self.items = [
            {
                "sourceSignature": "visual-dhash-v1:" + "a" * 64,
                "naturalWidth": 1200,
                "naturalHeight": 800,
                "mediaIndex": 0,
                "blockIndex": 3,
                "anchorBefore": "第一张图说明",
            },
            {
                "sourceSignature": "visual-dhash-v1:" + "b" * 64,
                "naturalWidth": 1000,
                "naturalHeight": 700,
                "mediaIndex": 1,
                "blockIndex": 6,
                "anchorBefore": "第二张图说明",
            },
        ]

    def test_source_contract_requires_rgb_sample_before_opening_x(self):
        content = [{"path": "/local/one.png", "expected_anchor": "图片说明"}]
        signature = "visual-dhash-v1:" + "0" * 64
        invalid_samples = [
            "",
            "visual-rgb8-v1:" + "00" * 191,
            "visual-rgb8-v1:" + "gg" * 192,
            "visual-rgb8-v2:" + "00" * 192,
            "visual-rgb8-v1:" + "AA" * 192,
        ]
        for invalid_sample in invalid_samples:
            with self.subTest(invalid_sample=invalid_sample[:32]):
                with self.assertRaisesRegex(ValueError, "RGB comparison sample"):
                    uploader.build_source_media_contract(
                        content,
                        [{"sourceSignature": signature, "visualSample": invalid_sample}],
                        require_visual_sample=True,
                    )

        contract = uploader.build_source_media_contract(
            content,
            [
                {
                    "sourceSignature": signature,
                    "visualSample": "visual-rgb8-v1:" + "00" * 192,
                }
            ],
            require_visual_sample=True,
        )
        self.assertTrue(
            uploader.VISUAL_RGB_SAMPLE_RE.fullmatch(contract[0]["source_visual_sample"])
        )
        self.assertEqual(
            contract[0]["source_visual_sample_id"],
            uploader.visual_sample_id(contract[0]["source_visual_sample"]),
        )
        self.assertEqual(len(contract[0]["source_visual_sample_id"]), 16)

    def test_rgb_sample_decoder_and_metrics_fail_closed_on_malformed_data(self):
        valid = self.patterned_sample()
        decoded = uploader.decode_visual_rgb_sample(valid)
        self.assertIsNotNone(decoded)
        self.assertEqual(len(decoded), 64)
        self.assertEqual(decoded[0], (48, 48, 48))

        malformed = [
            "",
            "visual-rgb8-v1:" + "00" * 191,
            "visual-rgb8-v1:" + "zz" * 192,
            "visual-rgb8-v1:" + "00" * 192 + "00",
            "visual-rgb16-v1:" + "00" * 192,
        ]
        for value in malformed:
            with self.subTest(value=value[:32]):
                self.assertIsNone(uploader.decode_visual_rgb_sample(value))
                self.assertIsNone(uploader.visual_rgb_sample_metrics(valid, value))

        identical = uploader.visual_rgb_sample_metrics(valid, valid)
        self.assertIsNotNone(identical)
        self.assertEqual(identical["rgb_mean_absolute_error"], 0)
        self.assertEqual(identical["luma_mean_absolute_error"], 0)
        self.assertAlmostEqual(identical["luma_correlation"], 1.0)

    def test_exact_order_signatures_and_anchor_adjacency_are_required(self):
        evidence = uploader.validate_composer_media_evidence(self.items, self.expected)
        self.assertTrue(evidence["valid"])
        self.assertEqual(
            evidence["ordered_signatures"],
            ["visual-dhash-v1:" + "a" * 64, "visual-dhash-v1:" + "b" * 64],
        )
        self.assertEqual(evidence["ordered_binding_keys"], [item["identity_key"] for item in self.expected])
        self.assertTrue(all(item["anchor_matches"] for item in evidence["items"]))

        swapped = uploader.validate_composer_media_evidence(list(reversed(self.items)), self.expected)
        self.assertFalse(swapped["valid"])

    def test_transient_binding_failure_cannot_veto_exact_final_reload(self):
        transient = uploader.validate_composer_media_evidence(
            [dict(self.items[0], sourceSignature="visual-dhash-v1:" + "0" * 64)],
            self.expected,
        )
        self.assertFalse(transient["valid"])

        final_evidence = uploader.validate_composer_media_evidence(self.items, self.expected)
        final_contract = uploader.validate_final_media_contract(
            final_evidence,
            self.expected,
        )
        cross_phase = uploader.validate_media_phase_persistence(
            transient,
            final_evidence,
        )

        self.assertFalse(cross_phase["cross_phase_observation_valid"])
        self.assertTrue(cross_phase["valid"])
        self.assertTrue(final_contract["valid"])

    def test_final_reload_wrong_identity_order_or_anchor_remains_hard_failure(self):
        cases = {
            "wrong_identity": [
                dict(self.items[0], sourceSignature="visual-dhash-v1:" + "0" * 64),
                self.items[1],
            ],
            "wrong_order": list(reversed(self.items)),
            "wrong_anchor": [
                self.items[0],
                dict(self.items[1], anchorBefore="完全错误的段落"),
            ],
        }
        for name, items in cases.items():
            with self.subTest(name=name):
                final_evidence = uploader.validate_composer_media_evidence(items, self.expected)
                final_contract = uploader.validate_final_media_contract(
                    final_evidence,
                    self.expected,
                )
                self.assertFalse(final_evidence["valid"])
                self.assertFalse(final_contract["valid"])

    def test_composer_start_media_requires_no_preceding_text_anchor(self):
        signature = "visual-dhash-v1:" + "c" * 64
        expected = uploader.build_source_media_contract(
            [
                {
                    "path": "/local/start.png",
                    "expected_anchor": "",
                    "placement": uploader.MEDIA_PLACEMENT_COMPOSER_START,
                }
            ],
            [{"sourceSignature": signature}],
        )
        at_start = {
            "sourceSignature": signature,
            "naturalWidth": 1000,
            "naturalHeight": 700,
            "mediaIndex": 0,
            "blockIndex": 0,
            "anchorBefore": "",
        }

        evidence = uploader.validate_composer_media_evidence([at_start], expected)
        self.assertTrue(evidence["valid"])
        self.assertTrue(
            uploader.identify_single_new_media_signature([], [at_start], expected[0], expected)[
                "valid"
            ]
        )

        during_insertion = dict(at_start, anchorBefore=uploader.MEDIA_START_MARKER)
        self.assertFalse(
            uploader.validate_composer_media_evidence([during_insertion], expected)["valid"]
        )
        self.assertTrue(
            uploader.identify_single_new_media_signature(
                [],
                [during_insertion],
                expected[0],
                expected,
            )["valid"]
        )

        displaced = dict(at_start, anchorBefore="正文已经出现在图片前面")
        self.assertFalse(uploader.validate_composer_media_evidence([displaced], expected)["valid"])
        self.assertFalse(
            uploader.identify_single_new_media_signature([], [displaced], expected[0], expected)[
                "valid"
            ]
        )

    def test_duplicate_source_images_are_bound_by_occurrence_anchor_and_order(self):
        duplicate_expected = uploader.build_source_media_contract(
            [
                {"path": "/local/same.png", "expected_anchor": "第一次出现"},
                {"path": "/local/same.png", "expected_anchor": "第二次出现"},
            ],
            [
                {"sourceSignature": self.items[0]["sourceSignature"]},
                {"sourceSignature": self.items[0]["sourceSignature"]},
            ],
        )
        duplicate_items = [
            dict(self.items[0], mediaIndex=0, anchorBefore="第一次出现"),
            dict(self.items[0], mediaIndex=1, blockIndex=6, anchorBefore="第二次出现"),
        ]
        evidence = uploader.validate_composer_media_evidence(duplicate_items, duplicate_expected)
        self.assertTrue(evidence["valid"])
        self.assertTrue(evidence["duplicate_signatures_allowed"])
        self.assertEqual([item["occurrence"] for item in evidence["items"]], [1, 2])

    def test_transport_url_signature_fails_closed(self):
        ephemeral = [dict(self.items[0], sourceSignature="blob:https://x.com/temporary"), self.items[1]]
        self.assertFalse(uploader.validate_composer_media_evidence(ephemeral, self.expected)["valid"])

    def test_each_paste_must_add_exactly_one_hosted_signature(self):
        before = [dict(self.items[0], runtimeKey="epoch-before-0")]
        after = [before[0], dict(self.items[1], runtimeKey="")]
        binding = uploader.identify_single_new_media_signature(before, after, self.expected[1])
        self.assertTrue(binding["valid"])
        self.assertEqual(binding["source_signature"], "visual-dhash-v1:" + "b" * 64)
        self.assertEqual(binding["binding_key"], self.expected[1]["identity_key"])

        replaced = [self.items[1], dict(self.items[0], sourceSignature="visual-dhash-v1:" + "c" * 64)]
        self.assertFalse(uploader.identify_single_new_media_signature(before, replaced, self.expected[1])["valid"])
        ephemeral = [self.items[0], dict(self.items[1], sourceSignature="blob:https://x.com/new")]
        self.assertFalse(uploader.identify_single_new_media_signature(before, ephemeral, self.expected[1])["valid"])

    def test_rerendered_prior_node_may_lose_runtime_key_without_losing_pixel_identity(self):
        prior = dict(
            self.items[1],
            runtimeKey="temporary-before-key",
            visualSample=self.patterned_sample(),
        )
        new_item = dict(
            self.items[0],
            runtimeKey="",
            visualSample=self.patterned_sample(invert=True),
        )
        rerendered_prior = dict(prior, runtimeKey="")

        binding = uploader.identify_single_new_media_signature(
            [prior],
            [new_item, rerendered_prior],
            self.expected[0],
            self.expected,
        )

        self.assertTrue(binding["valid"])
        self.assertEqual(binding["candidate_indices"], [0])
        self.assertEqual(binding["actual_dom_order"], 0)
        self.assertEqual(binding["before_runtime_keys"], ["temporary-before-key"])
        self.assertEqual(binding["after_runtime_keys"], ["", ""])
        self.assertTrue(binding["prior_sequence_preserved"])

    def test_synthetic_rerender_evidence_binds_the_exact_new_node(self):
        old_image_signature = "visual-dhash-v1:" + "2" * 64
        new_image_signature = "visual-dhash-v1:" + "1" * 64
        anchor = "这是只包含合成内容的唯一长锚点，用于确认重新渲染后仍绑定到新增媒体节点。"
        expected = uploader.build_source_media_contract(
            [{"path": "/local/synthetic-new.png", "expected_anchor": anchor}],
            [
                {
                    "sourceSignature": new_image_signature,
                    "naturalWidth": 80,
                    "naturalHeight": 66,
                }
            ],
        )
        before = [
            {
                "sourceSignature": old_image_signature,
                "naturalWidth": 80,
                "naturalHeight": 66,
                "runtimeKey": "temporary-before-key",
            }
        ]
        after = [
            {
                "sourceSignature": new_image_signature,
                "naturalWidth": 80,
                "naturalHeight": 66,
                "runtimeKey": "",
                "anchorBefore": anchor,
            },
            {
                "sourceSignature": old_image_signature,
                "naturalWidth": 80,
                "naturalHeight": 66,
                "runtimeKey": "",
            },
        ]

        binding = uploader.identify_single_new_media_signature(
            before,
            after,
            expected[0],
            expected,
        )

        self.assertTrue(binding["valid"])
        self.assertEqual(binding["candidate_indices"], [0])
        self.assertEqual(binding["matching_candidate_indices"], [0])
        self.assertEqual(binding["observed_signature"], new_image_signature)
        self.assertEqual(binding["source_hamming_distance"], 0)
        self.assertTrue(binding["prior_sequence_preserved"])

    def test_runtime_key_reuse_cannot_override_changed_prior_pixels(self):
        prior = dict(self.items[1], runtimeKey="reused-key")
        wrong_prior = dict(
            prior,
            sourceSignature="visual-dhash-v1:" + "0" * 64,
            runtimeKey="reused-key",
        )
        new_item = dict(self.items[0], runtimeKey="")

        binding = uploader.identify_single_new_media_signature(
            [prior],
            [new_item, wrong_prior],
            self.expected[0],
            self.expected,
        )

        self.assertFalse(binding["valid"])
        self.assertEqual(binding["candidate_indices"], [])

    def test_calibrated_hamming_boundary_and_non_exact_reload_match(self):
        source = "visual-dhash-v1:" + "0" * 64
        at_boundary = "visual-dhash-v1:" + f"{(1 << 64) - 1:064x}"
        over_boundary = "visual-dhash-v1:" + f"{(1 << 65) - 1:064x}"
        self.assertEqual(uploader.visual_signature_hamming_distance(source, at_boundary), 64)
        self.assertTrue(uploader.visual_signatures_match(source, at_boundary))
        self.assertFalse(uploader.visual_signatures_match(source, over_boundary))

        expected = uploader.build_source_media_contract(
            [{"path": "/local/same.png", "expected_anchor": "图片说明"}],
            [{"sourceSignature": source}],
        )
        before = uploader.validate_composer_media_evidence(
            [{"sourceSignature": source, "naturalWidth": 10, "naturalHeight": 10, "mediaIndex": 0, "anchorBefore": "图片说明"}],
            expected,
        )
        after = uploader.validate_composer_media_evidence(
            [{"sourceSignature": at_boundary, "naturalWidth": 10, "naturalHeight": 10, "mediaIndex": 0, "anchorBefore": "图片说明"}],
            expected,
        )
        persisted = uploader.validate_media_phase_persistence(before, after)
        self.assertTrue(persisted["valid"])
        self.assertFalse(persisted["exact_signatures_equal"])

    def test_x_recompressed_image_uses_bounded_multi_signal_match(self):
        source = "visual-dhash-v1:" + "0" * 64
        observed = "visual-dhash-v1:" + f"{(1 << 71) - 1:064x}"
        next_nearest = "visual-dhash-v1:" + f"{(1 << 162) - 1:064x}"
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/recompressed.png", "expected_anchor": "压缩图说明"},
                {"path": "/local/other.png", "expected_anchor": "另一张图说明"},
            ],
            [
                {"sourceSignature": source, "naturalWidth": 1536, "naturalHeight": 1024},
                {"sourceSignature": next_nearest, "naturalWidth": 1200, "naturalHeight": 800},
            ],
        )
        recompressed_item = {
            "sourceSignature": observed,
            "naturalWidth": 1200,
            "naturalHeight": 800,
            "mediaIndex": 0,
            "anchorBefore": "压缩图说明",
        }
        items = [
            recompressed_item,
            {
                "sourceSignature": next_nearest,
                "naturalWidth": 900,
                "naturalHeight": 600,
                "mediaIndex": 1,
                "anchorBefore": "另一张图说明",
            },
        ]

        binding = uploader.identify_single_new_media_signature(
            [],
            [recompressed_item],
            expected[0],
            expected,
        )
        persisted = uploader.validate_composer_media_evidence(items, expected)

        self.assertTrue(binding["valid"])
        self.assertEqual(binding["source_hamming_distance"], 71)
        self.assertEqual(binding["nearest_source_margin"], 20)
        self.assertEqual(binding["match_policy"], "adaptive-unique-nearest")
        self.assertTrue(binding["aspect_ratio_matches"])
        self.assertTrue(persisted["valid"])
        self.assertTrue(persisted["items"][0]["adaptive_source_match"])

    def test_pixel_sample_consensus_can_accept_large_dhash_transform(self):
        def sample(transform=lambda value: value):
            raw = bytearray()
            for index in range(64):
                for value in ((index * 37) % 256, (index * 53) % 256, (index * 71) % 256):
                    raw.append(max(0, min(255, transform(value))))
            return "visual-rgb8-v1:" + raw.hex()

        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        distractor_signature = "visual-dhash-v1:" + "f" * 64
        source_sample = sample()
        observed_sample = sample(lambda value: value + 3)
        distractor_sample = sample(lambda value: 255 - value)
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/source.png", "expected_anchor": "源图锚点"},
                {"path": "/local/distractor.png", "expected_anchor": "干扰图锚点"},
            ],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                },
                {
                    "sourceSignature": distractor_signature,
                    "visualSample": distractor_sample,
                    "naturalWidth": 1200,
                    "naturalHeight": 800,
                },
            ],
        )
        candidate = {
            "sourceSignature": observed_signature,
            "visualSample": observed_sample,
            "naturalWidth": 1200,
            "naturalHeight": 800,
            "mediaIndex": 0,
            "anchorBefore": "源图锚点",
        }

        match = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            1200,
            800,
            observed_sample,
        )
        binding = uploader.identify_single_new_media_signature(
            [],
            [candidate],
            expected[0],
            expected,
        )

        self.assertEqual(match["expected_source_distance"], 120)
        self.assertFalse(match["expected_source_within_adaptive_radius"])
        self.assertTrue(match["sample_similarity_matches"])
        self.assertTrue(match["sample_consensus_match"])
        self.assertEqual(match["match_policy"], "multi-signal-consensus")
        self.assertLess(match["expected_source_sample_metrics"]["rgb_mean_absolute_error"], 0.02)
        self.assertTrue(binding["valid"])
        self.assertEqual(binding["match_policy"], "multi-signal-consensus")

    def test_pixel_sample_consensus_rejects_wrong_or_ambiguous_content(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        black = "visual-rgb8-v1:" + (bytes([0, 0, 0]) * 64).hex()
        near_black = "visual-rgb8-v1:" + (bytes([3, 3, 3]) * 64).hex()
        white = "visual-rgb8-v1:" + (bytes([255, 255, 255]) * 64).hex()
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/black.png", "expected_anchor": "黑图"},
                {"path": "/local/near-black.png", "expected_anchor": "近黑图"},
            ],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": black,
                    "naturalWidth": 1000,
                    "naturalHeight": 1000,
                },
                {
                    "sourceSignature": "visual-dhash-v1:" + "f" * 64,
                    "visualSample": near_black,
                    "naturalWidth": 1000,
                    "naturalHeight": 1000,
                },
            ],
        )
        wrong_content = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            1000,
            1000,
            white,
        )
        ambiguous_content = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            1000,
            1000,
            near_black,
        )

        self.assertFalse(wrong_content["valid"])
        self.assertFalse(wrong_content["sample_similarity_matches"])
        self.assertFalse(ambiguous_content["valid"])
        self.assertFalse(ambiguous_content["expected_source_sample_is_unique_nearest"])

    def test_pixel_consensus_does_not_require_an_arbitrary_nearest_margin(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_int = (1 << 120) - 1
        observed_signature = "visual-dhash-v1:" + f"{observed_int:064x}"
        close_signature = "visual-dhash-v1:" + f"{observed_int ^ (((1 << 125) - 1) << 120):064x}"
        black = "visual-rgb8-v1:" + (bytes([0, 0, 0]) * 64).hex()
        almost_black = "visual-rgb8-v1:" + (bytes([1, 1, 1]) * 64).hex()
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/source.png", "expected_anchor": "源图"},
                {"path": "/local/close.png", "expected_anchor": "近邻图"},
            ],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": black,
                    "naturalWidth": 1000,
                    "naturalHeight": 1000,
                },
                {
                    "sourceSignature": close_signature,
                    "visualSample": almost_black,
                    "naturalWidth": 1000,
                    "naturalHeight": 1000,
                },
            ],
        )

        match = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            800,
            800,
            black,
        )

        self.assertFalse(match["adaptive_margin_matches"])
        self.assertFalse(match["sample_margin_matches"])
        self.assertTrue(match["expected_source_sample_is_unique_nearest"])
        self.assertTrue(match["sample_consensus_match"])
        self.assertTrue(match["valid"])

    def test_flat_images_use_bounded_error_when_correlation_is_undefined(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        expected = uploader.build_source_media_contract(
            [{"path": "/local/flat.png", "expected_anchor": "纯色图"}],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": self.flat_sample(100),
                    "naturalWidth": 1000,
                    "naturalHeight": 1000,
                }
            ],
        )

        accepted = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            800,
            800,
            self.flat_sample(125),
        )
        rejected = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            800,
            800,
            self.flat_sample(132),
        )

        self.assertIsNone(accepted["expected_source_sample_metrics"]["luma_correlation"])
        self.assertTrue(accepted["sample_similarity_matches"])
        self.assertTrue(accepted["sample_consensus_match"])
        self.assertEqual(accepted["match_policy"], "multi-signal-consensus")
        self.assertFalse(rejected["sample_similarity_matches"])
        self.assertFalse(rejected["valid"])

    def test_sample_consensus_still_requires_dimensions_and_stable_aspect_ratio(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        source_sample = self.patterned_sample()
        expected = uploader.build_source_media_contract(
            [{"path": "/local/wide.png", "expected_anchor": "宽图"}],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                }
            ],
        )

        wrong_ratio = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            1000,
            1000,
            source_sample,
        )
        missing_dimensions = uploader.evaluate_source_visual_match(
            observed_signature,
            expected[0],
            expected,
            0,
            0,
            source_sample,
        )

        self.assertTrue(wrong_ratio["sample_similarity_matches"])
        self.assertFalse(wrong_ratio["aspect_ratio_matches"])
        self.assertFalse(wrong_ratio["valid"])
        self.assertFalse(missing_dimensions["aspect_ratio_available"])
        self.assertFalse(missing_dimensions["valid"])

    def test_seeded_transform_matrix_accepts_unique_small_pixel_perturbations(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/source.png", "expected_anchor": "源图"},
                {"path": "/local/distractor.png", "expected_anchor": "干扰图"},
            ],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": self.patterned_sample(),
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                },
                {
                    "sourceSignature": "visual-dhash-v1:" + "f" * 64,
                    "visualSample": self.patterned_sample(invert=True),
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                },
            ],
        )

        for delta in (-12, -6, -3, 0, 3, 6, 12):
            with self.subTest(delta=delta):
                match = uploader.evaluate_source_visual_match(
                    observed_signature,
                    expected[0],
                    expected,
                    1200,
                    800,
                    self.patterned_sample(delta=delta),
                )
                self.assertTrue(match["expected_source_sample_is_unique_nearest"])
                self.assertTrue(match["sample_consensus_match"])
                self.assertTrue(match["valid"])

    def test_duplicate_source_samples_remain_bound_by_occurrence_anchor_and_order(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        observed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        source_sample = self.patterned_sample()
        observed_sample = self.patterned_sample(delta=4)
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/same.png", "expected_anchor": "第一次"},
                {"path": "/local/same.png", "expected_anchor": "第二次"},
            ],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                },
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                },
            ],
        )
        observed = [
            {
                "sourceSignature": observed_signature,
                "visualSample": observed_sample,
                "naturalWidth": 1200,
                "naturalHeight": 800,
                "mediaIndex": 0,
                "anchorBefore": "第一次",
            },
            {
                "sourceSignature": observed_signature,
                "visualSample": observed_sample,
                "naturalWidth": 1200,
                "naturalHeight": 800,
                "mediaIndex": 1,
                "anchorBefore": "第二次",
            },
        ]

        evidence = uploader.validate_composer_media_evidence(observed, expected)

        self.assertTrue(evidence["valid"])
        self.assertEqual([item["occurrence"] for item in evidence["items"]], [1, 2])
        self.assertTrue(all(item["sample_consensus_match"] for item in evidence["items"]))
        for item in evidence["items"]:
            self.assertEqual(item["distinct_source_sample_group_count"], 1)
            self.assertEqual(len(item["source_sample_distances"]), 1)
            self.assertEqual(
                item["source_sample_distances"][0]["source_sample_id"],
                item["expected_source_sample_id"],
            )
            self.assertIsNotNone(item["nearest_source_sample_distance"])
            self.assertIsNone(item["second_nearest_source_sample_distance"])
            self.assertIsNone(item["nearest_source_sample_margin"])
            self.assertTrue(item["expected_source_sample_is_unique_nearest"])
            self.assertIsNotNone(item["rgb_mean_absolute_error"])
            self.assertIsNotNone(item["luma_mean_absolute_error"])

    def test_reload_can_move_from_strict_match_to_sample_consensus_without_losing_identity(self):
        source_signature = "visual-dhash-v1:" + "0" * 64
        transformed_signature = "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}"
        source_sample = self.patterned_sample()
        expected = uploader.build_source_media_contract(
            [{"path": "/local/reload.png", "expected_anchor": "重载图"}],
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                }
            ],
        )
        before = uploader.validate_composer_media_evidence(
            [
                {
                    "sourceSignature": source_signature,
                    "visualSample": source_sample,
                    "naturalWidth": 1500,
                    "naturalHeight": 1000,
                    "mediaIndex": 0,
                    "anchorBefore": "重载图",
                }
            ],
            expected,
        )
        after = uploader.validate_composer_media_evidence(
            [
                {
                    "sourceSignature": transformed_signature,
                    "visualSample": self.patterned_sample(delta=3),
                    "naturalWidth": 1200,
                    "naturalHeight": 800,
                    "mediaIndex": 0,
                    "anchorBefore": "重载图",
                }
            ],
            expected,
        )

        persisted = uploader.validate_media_phase_persistence(before, after)

        self.assertEqual(before["items"][0]["match_policy"], "strict-radius")
        self.assertEqual(after["items"][0]["match_policy"], "multi-signal-consensus")
        self.assertTrue(persisted["valid"])
        self.assertTrue(persisted["ordered_identities_match"])
        self.assertFalse(persisted["exact_signatures_equal"])

    def test_adaptive_match_rejects_weak_margin_bad_ratio_and_excess_distance(self):
        source = "visual-dhash-v1:" + "0" * 64
        observed_71_int = (1 << 71) - 1
        observed_71 = "visual-dhash-v1:" + f"{observed_71_int:064x}"
        close_distractor = "visual-dhash-v1:" + f"{observed_71_int ^ (((1 << 75) - 1) << 71):064x}"
        expected_with_close_source = uploader.build_source_media_contract(
            [
                {"path": "/local/source.png", "expected_anchor": "源图"},
                {"path": "/local/close.png", "expected_anchor": "近邻图"},
            ],
            [
                {"sourceSignature": source, "naturalWidth": 1500, "naturalHeight": 1000},
                {"sourceSignature": close_distractor, "naturalWidth": 1500, "naturalHeight": 1000},
            ],
        )
        weak_margin = uploader.evaluate_source_visual_match(
            observed_71,
            expected_with_close_source[0],
            expected_with_close_source,
            1200,
            800,
        )
        bad_ratio = uploader.evaluate_source_visual_match(
            observed_71,
            expected_with_close_source[0],
            [expected_with_close_source[0]],
            1000,
            1000,
        )
        observed_81 = "visual-dhash-v1:" + f"{(1 << 81) - 1:064x}"
        over_cap = uploader.evaluate_source_visual_match(
            observed_81,
            expected_with_close_source[0],
            [expected_with_close_source[0]],
            1200,
            800,
        )

        self.assertTrue(weak_margin["expected_source_is_unique_nearest"])
        self.assertEqual(weak_margin["nearest_source_margin"], 4)
        self.assertFalse(weak_margin["valid"])
        self.assertFalse(weak_margin["adaptive_margin_matches"])
        self.assertFalse(bad_ratio["valid"])
        self.assertFalse(bad_ratio["aspect_ratio_matches"])
        self.assertFalse(over_cap["valid"])
        self.assertFalse(over_cap["expected_source_within_adaptive_radius"])

    def test_adaptive_binding_still_requires_anchor_and_preserved_prior_nodes(self):
        source = "visual-dhash-v1:" + "0" * 64
        observed = "visual-dhash-v1:" + f"{(1 << 71) - 1:064x}"
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/prior.png", "expected_anchor": "旧图"},
                {"path": "/local/new.png", "expected_anchor": "新图"},
            ],
            [
                {"sourceSignature": "visual-dhash-v1:" + "f" * 64, "naturalWidth": 1000, "naturalHeight": 1000},
                {"sourceSignature": source, "naturalWidth": 1500, "naturalHeight": 1000},
            ],
        )
        before = [
            {
                "sourceSignature": expected[0]["source_signature"],
                "naturalWidth": 1000,
                "naturalHeight": 1000,
                "runtimeKey": "prior-node-0",
            }
        ]
        rerendered_prior = dict(
            before[0],
            sourceSignature="visual-dhash-v1:" + "f" * 63 + "e",
        )
        candidate = {
            "sourceSignature": observed,
            "naturalWidth": 1200,
            "naturalHeight": 800,
            "runtimeKey": "",
            "anchorBefore": "新图",
        }

        valid = uploader.identify_single_new_media_signature(
            before,
            [rerendered_prior, candidate],
            expected[1],
            expected,
        )
        wrong_anchor = uploader.identify_single_new_media_signature(
            before,
            [rerendered_prior, dict(candidate, anchorBefore="错误位置")],
            expected[1],
            expected,
        )

        self.assertTrue(valid["valid"])
        self.assertTrue(valid["prior_sequence_preserved"])
        self.assertFalse(wrong_anchor["valid"])
        self.assertFalse(wrong_anchor["anchor_matches"])

    def test_nearby_source_groups_reject_swapped_observations(self):
        source_a = "visual-dhash-v1:" + "0" * 64
        source_b = "visual-dhash-v1:" + f"{(1 << 31) - 1:064x}"
        expected = uploader.build_source_media_contract(
            [
                {"path": "/local/a.png", "expected_anchor": "A 图锚点"},
                {"path": "/local/b.png", "expected_anchor": "B 图锚点"},
            ],
            [{"sourceSignature": source_a}, {"sourceSignature": source_b}],
        )
        swapped = [
            {
                "sourceSignature": source_b,
                "naturalWidth": 100,
                "naturalHeight": 100,
                "mediaIndex": 0,
                "anchorBefore": "A 图锚点",
            },
            {
                "sourceSignature": source_a,
                "naturalWidth": 100,
                "naturalHeight": 100,
                "mediaIndex": 1,
                "anchorBefore": "B 图锚点",
            },
        ]
        evidence = uploader.validate_composer_media_evidence(swapped, expected)
        self.assertFalse(evidence["valid"])
        self.assertEqual([item["source_hamming_distance"] for item in evidence["items"]], [31, 31])
        self.assertTrue(all(not item["expected_source_is_unique_nearest"] for item in evidence["items"]))
        self.assertTrue(all(item["source_ambiguous"] for item in evidence["items"]))
        self.assertEqual(evidence["items"][0]["nearest_source_signatures"], [source_b])
        self.assertEqual(evidence["items"][1]["nearest_source_signatures"], [source_a])


class CoverAndAutosaveContractTests(unittest.TestCase):
    def test_body_media_limit_is_independent_from_cover(self):
        allowed = uploader.apply_body_media_limit({"errors": []}, 25)
        self.assertEqual(allowed["errors"], [])

        blocked = uploader.apply_body_media_limit({"errors": []}, 26)
        self.assertEqual(len(blocked["errors"]), 1)
        self.assertEqual(blocked["errors"][0]["type"], "body_media_limit_exceeded")
        self.assertTrue(blocked["errors"][0]["cover_separate"])
        self.assertIn("正文图片有 26 张", blocked["errors"][0]["message"])
        self.assertIn("超过 X 正文上限 1 张", blocked["errors"][0]["message"])
        self.assertIn("图片文件本身没有损坏", blocked["errors"][0]["message"])
        uploader.apply_body_media_limit(blocked, 26)
        self.assertEqual(len(blocked["errors"]), 1)

    def test_hosted_cover_fetch_is_restricted_to_x_media_hosts(self):
        self.assertTrue(uploader.is_allowed_x_media_url("https://pbs.twimg.com/media/example.jpg"))
        self.assertTrue(uploader.is_allowed_x_media_url("https://ton.x.com/i/ton/data/example"))
        self.assertFalse(uploader.is_allowed_x_media_url("http://pbs.twimg.com/media/example.jpg"))
        self.assertFalse(uploader.is_allowed_x_media_url("https://twimg.com.evil.example/cover.jpg"))
        self.assertFalse(uploader.is_allowed_x_media_url("https://example.com/cover.jpg"))

    def test_cover_must_match_local_source_and_be_added_from_zero(self):
        source = {"sourceSignature": "visual-dhash-v1:" + "0" * 64}
        observed = [{"sourceSignature": "visual-dhash-v1:" + "0" * 63 + "1"}]
        evidence = uploader.validate_cover_evidence(observed, True, source, cleared_baseline_count=0)
        self.assertTrue(evidence["valid"])
        self.assertTrue(evidence["signature_match"])
        self.assertTrue(evidence["added_from_cleared_state"])
        self.assertFalse(uploader.validate_cover_evidence(observed, True, source, 1)["valid"])

    def test_recompressed_cover_uses_same_bounded_adaptive_contract(self):
        source = {
            "sourceSignature": "visual-dhash-v1:" + "0" * 64,
            "naturalWidth": 1500,
            "naturalHeight": 1000,
        }
        observed = [
            {
                "sourceSignature": "visual-dhash-v1:" + f"{(1 << 71) - 1:064x}",
                "naturalWidth": 1200,
                "naturalHeight": 800,
            }
        ]

        evidence = uploader.validate_cover_evidence(
            observed,
            True,
            source,
            cleared_baseline_count=0,
        )

        self.assertTrue(evidence["valid"])
        self.assertTrue(evidence["adaptive_source_match"])
        self.assertEqual(evidence["match_policy"], "adaptive-unique-nearest")
        self.assertFalse(
            uploader.validate_cover_evidence(
                [{"sourceSignature": "", "sourceUrlKind": "hosted"}],
                True,
                source,
                0,
            )["valid"]
        )

    def test_heavily_recompressed_cover_uses_pixel_consensus_and_exact_count(self):
        source_sample = ComposerMediaEvidenceTests.patterned_sample()
        source = {
            "sourceSignature": "visual-dhash-v1:" + "0" * 64,
            "visualSample": source_sample,
            "naturalWidth": 1500,
            "naturalHeight": 1000,
        }
        observed = {
            "sourceSignature": "visual-dhash-v1:" + f"{(1 << 120) - 1:064x}",
            "visualSample": ComposerMediaEvidenceTests.patterned_sample(delta=5),
            "naturalWidth": 1200,
            "naturalHeight": 800,
        }

        evidence = uploader.validate_cover_evidence(
            [observed],
            True,
            source,
            cleared_baseline_count=0,
        )
        duplicate = uploader.validate_cover_evidence(
            [observed, observed],
            True,
            source,
            cleared_baseline_count=0,
        )

        self.assertTrue(evidence["valid"])
        self.assertTrue(evidence["sample_consensus_match"])
        self.assertEqual(evidence["match_policy"], "multi-signal-consensus")
        self.assertTrue(evidence["sample_similarity_matches"])
        self.assertTrue(evidence["sample_margin_matches"])
        self.assertEqual(evidence["distinct_source_sample_group_count"], 1)
        self.assertEqual(len(evidence["source_sample_distances"]), 1)
        self.assertEqual(
            evidence["source_sample_distances"][0]["source_sample_id"],
            evidence["expected_source_sample_id"],
        )
        self.assertIsNotNone(evidence["nearest_source_sample_distance"])
        self.assertIsNone(evidence["second_nearest_source_sample_distance"])
        self.assertIsNone(evidence["nearest_source_sample_margin"])
        self.assertTrue(evidence["expected_source_sample_is_unique_nearest"])
        self.assertIsNotNone(evidence["rgb_mean_absolute_error"])
        self.assertIsNotNone(evidence["luma_mean_absolute_error"])
        self.assertEqual(evidence["source_natural_width"], 1500)
        self.assertEqual(evidence["source_natural_height"], 1000)
        self.assertEqual(evidence["observed_natural_width"], 1200)
        self.assertEqual(evidence["observed_natural_height"], 800)
        self.assertFalse(duplicate["valid"])
        self.assertFalse(duplicate["exact_count"])

    def test_autosave_requires_current_epoch_transition_or_changed_saved_token(self):
        transition = {
            "epoch": "epoch-1",
            "mutationCount": 1,
            "lastMutationAt": 1000,
            "lastMutationEventCursor": 0,
            "mutationBaseline": [
                {"channelKey": "testid:save", "token": "old", "nodeInstance": 1}
            ],
            "events": [
                {
                    "channelKey": "testid:save",
                    "state": "saving",
                    "text": "正在保存",
                    "token": "saving",
                    "nodeInstance": 1,
                    "sequence": 1,
                    "observedAt": 1001,
                },
                {
                    "channelKey": "testid:save",
                    "state": "saved",
                    "text": "刚刚最后保存",
                    "token": "new",
                    "nodeInstance": 1,
                    "sequence": 2,
                    "observedAt": 1002,
                },
            ],
            "current": [
                {
                    "channelKey": "testid:save",
                    "state": "saved",
                    "text": "刚刚最后保存",
                    "token": "new",
                    "nodeInstance": 1,
                }
            ],
        }
        self.assertTrue(uploader.validate_autosave_epoch_evidence(transition, "epoch-1")["verified"])

        stale = dict(transition, events=[], current=transition["current"])
        self.assertFalse(uploader.validate_autosave_epoch_evidence(stale, "epoch-1")["verified"])
        changed = dict(transition, events=[transition["events"][1]])
        self.assertTrue(uploader.validate_autosave_epoch_evidence(changed, "epoch-1")["verified"])
        stale_current_binding = dict(
            transition,
            current=[dict(transition["current"][0], token="newer-current-token")],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                stale_current_binding,
                "epoch-1",
            )["verified"]
        )
        self.assertFalse(uploader.validate_autosave_epoch_evidence(transition, "other-epoch")["verified"])

    def test_exact_reload_persistence_can_replace_missing_autosave_ui_only(self):
        fallback = uploader.resolve_autosave_verification(
            {"verified": False, "current": [], "timed_out": True},
            True,
        )
        self.assertTrue(fallback["verified"])
        self.assertFalse(fallback["ui_verified"])
        self.assertTrue(fallback["reload_persistence_fallback"])
        self.assertEqual(fallback["mode"], "reload_persistence_fallback")
        self.assertEqual(
            {warning["type"] for warning in fallback["warnings"]},
            {"autosave_ui_evidence_missing", "autosave_saved_text_missing"},
        )

        failed_reload = uploader.resolve_autosave_verification(
            {"verified": False, "current": []},
            False,
        )
        self.assertFalse(failed_reload["verified"])
        self.assertEqual(failed_reload["mode"], "unverified")

        bounded_ui = uploader.resolve_autosave_verification(
            {
                "verified": True,
                "current": [{"state": "saved", "text": "刚刚最后保存"}],
            },
            False,
        )
        self.assertTrue(bounded_ui["verified"])
        self.assertEqual(bounded_ui["mode"], "bounded_ui_event")
        self.assertEqual(bounded_ui["saved_text"], "刚刚最后保存")

    def test_autosave_accepts_same_token_only_after_explicit_post_mutation_departure(self):
        saved = {
            "epoch": "epoch-live",
            "mutationCount": 1,
            "lastMutationAt": 1000,
            "lastMutationSequence": 22,
            "lastMutationEventCursor": 999,
            "mutationBaseline": [
                {"channelKey": "id:detail-header", "token": "same", "nodeInstance": 1}
            ],
            # This is a trimmed event array. Sequence 23 must not be treated as index 23.
            "events": [
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "text": "",
                    "token": "",
                    "previousToken": "same",
                    "nodeInstance": 1,
                    "sequence": 23,
                    "observedAt": 1001,
                },
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                    "sequence": 24,
                    "observedAt": 1002,
                }
            ],
            "current": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                }
            ],
        }
        evidence = uploader.validate_autosave_epoch_evidence(saved, "epoch-live")
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["last_mutation_sequence"], 22)
        self.assertEqual(
            [item["sequence"] for item in evidence["post_mutation_saved_observations"]],
            [24],
        )
        self.assertEqual(
            evidence["departure_to_saved_transitions"],
            [
                {
                    "channel_key": "id:detail-header",
                    "previous_live_sequence": None,
                    "previous_live_token": "same",
                    "previous_live_node_instance": 1,
                    "departure_sequence": 23,
                    "saved_sequence": 24,
                    "saved_token": "same",
                    "saved_node_instance": 1,
                }
            ],
        )

        stale = dict(
            saved,
            events=[dict(saved["events"][0], observedAt=1000), saved["events"][1]],
        )
        self.assertFalse(uploader.validate_autosave_epoch_evidence(stale, "epoch-live")["verified"])

    def test_autosave_accepts_real_aged_saved_departure_then_current_saved_sequence(self):
        raw = {
            "epoch": "epoch-aged",
            "mutationCount": 1,
            "lastMutationAt": 1000,
            "lastMutationSequence": 34,
            "mutationBaseline": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "current-token",
                    "nodeInstance": 1,
                }
            ],
            "events": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 上一次保存 6秒钟 前",
                    "token": "aged-token",
                    "nodeInstance": 1,
                    "sequence": 35,
                    "observedAt": 1001,
                },
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "text": "",
                    "token": "",
                    "previousToken": "aged-token",
                    "nodeInstance": 1,
                    "sequence": 36,
                    "observedAt": 1002,
                },
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "current-token",
                    "nodeInstance": 1,
                    "sequence": 37,
                    "observedAt": 1003,
                },
            ],
            "current": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "current-token",
                    "nodeInstance": 1,
                }
            ],
        }
        evidence = uploader.validate_autosave_epoch_evidence(raw, "epoch-aged")
        self.assertTrue(evidence["verified"])
        self.assertEqual(
            evidence["departure_to_saved_transitions"],
            [
                {
                    "channel_key": "id:detail-header",
                    "previous_live_sequence": 35,
                    "previous_live_token": "aged-token",
                    "previous_live_node_instance": 1,
                    "departure_sequence": 36,
                    "saved_sequence": 37,
                    "saved_token": "current-token",
                    "saved_node_instance": 1,
                }
            ],
        )
        forged_previous_token = dict(
            raw,
            events=[
                raw["events"][0],
                dict(raw["events"][1], previousToken="current-token"),
                raw["events"][2],
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                forged_previous_token,
                "epoch-aged",
            )["verified"]
        )
        wrong_departed_node = dict(
            raw,
            events=[
                raw["events"][0],
                dict(raw["events"][1], nodeInstance=99),
                raw["events"][2],
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                wrong_departed_node,
                "epoch-aged",
            )["verified"]
        )

    def test_same_saved_replay_without_a_matching_current_departure_is_rejected(self):
        baseline = {
            "epoch": "epoch-strict",
            "mutationCount": 1,
            "lastMutationAt": 1000,
            "lastMutationSequence": 22,
            "mutationBaseline": [
                {"channelKey": "id:detail-header", "token": "same", "nodeInstance": 1}
            ],
            "current": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                }
            ],
        }
        same_saved = {
            "channelKey": "id:detail-header",
            "state": "saved",
            "text": "草稿 · 刚刚最后保存",
            "token": "same",
            "nodeInstance": 1,
            "sequence": 24,
            "observedAt": 1002,
        }
        replay = dict(baseline, events=[same_saved])
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(replay, "epoch-strict")["verified"]
        )

        wrong_channel = dict(
            baseline,
            events=[
                {
                    "channelKey": "role:status|index:1",
                    "state": "departed",
                    "token": "",
                    "previousToken": "same",
                    "nodeInstance": 1,
                    "sequence": 23,
                    "observedAt": 1001,
                },
                same_saved,
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(wrong_channel, "epoch-strict")["verified"]
        )

        pre_cursor_departure = dict(
            baseline,
            events=[
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "token": "",
                    "previousToken": "same",
                    "nodeInstance": 1,
                    "sequence": 22,
                    "observedAt": 1001,
                },
                same_saved,
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                pre_cursor_departure,
                "epoch-strict",
            )["verified"]
        )

        forged_previous_token = dict(
            baseline,
            events=[
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "token": "",
                    "previousToken": "forged-token",
                    "nodeInstance": 1,
                    "sequence": 23,
                    "observedAt": 1001,
                },
                same_saved,
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                forged_previous_token,
                "epoch-strict",
            )["verified"]
        )

        wrong_departed_node = dict(
            baseline,
            events=[
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "token": "",
                    "previousToken": "same",
                    "nodeInstance": 99,
                    "sequence": 23,
                    "observedAt": 1001,
                },
                same_saved,
            ],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                wrong_departed_node,
                "epoch-strict",
            )["verified"]
        )

        wrong_current_binding = dict(
            baseline,
            events=[
                {
                    "channelKey": "id:detail-header",
                    "state": "departed",
                    "token": "",
                    "previousToken": "same",
                    "nodeInstance": 1,
                    "sequence": 23,
                    "observedAt": 1001,
                },
                same_saved,
            ],
            current=[dict(baseline["current"][0], token="current-new")],
        )
        self.assertFalse(
            uploader.validate_autosave_epoch_evidence(
                wrong_current_binding,
                "epoch-strict",
            )["verified"]
        )

    def test_unrelated_status_change_cannot_replay_an_unchanged_saved_channel(self):
        raw = {
            "epoch": "epoch-unrelated",
            "mutationCount": 1,
            "lastMutationAt": 1000,
            "lastMutationSequence": 10,
            "mutationBaseline": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                },
                {
                    "channelKey": "role:status|index:1",
                    "state": "saved",
                    "text": "Saved",
                    "token": "other-old",
                    "nodeInstance": 2,
                },
            ],
            "events": [
                {
                    "channelKey": "role:status|index:1",
                    "state": "saved",
                    "text": "Saved",
                    "token": "other-new",
                    "nodeInstance": 2,
                    "sequence": 11,
                    "observedAt": 1001,
                },
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                    "sequence": 12,
                    "observedAt": 1001,
                },
            ],
            "current": [
                {
                    "channelKey": "id:detail-header",
                    "state": "saved",
                    "text": "草稿 · 刚刚最后保存",
                    "token": "same",
                    "nodeInstance": 1,
                }
            ],
        }
        evidence = uploader.validate_autosave_epoch_evidence(raw, "epoch-unrelated")
        self.assertFalse(evidence["verified"])
        self.assertEqual(evidence["post_mutation_saved_observations"], [])

    def test_resume_images_only_requires_zero_body_media_and_exact_cover(self):
        signature = "visual-dhash-v1:" + "0" * 64
        cover_source = {"sourceSignature": signature}
        valid_state = {
            "bodyMediaCount": 0,
            "bodyMedia": [],
            "coverMediaCount": 1,
            "coverMedia": [{"sourceSignature": signature}],
        }
        self.assertTrue(
            uploader.validate_resume_images_only_state(valid_state, True, cover_source)["verified"]
        )

        body_already_present = dict(
            valid_state,
            bodyMediaCount=1,
            bodyMedia=[{"sourceSignature": signature}],
        )
        self.assertFalse(
            uploader.validate_resume_images_only_state(body_already_present, True, cover_source)["verified"]
        )
        wrong_cover = dict(
            valid_state,
            coverMedia=[{"sourceSignature": "visual-dhash-v1:" + "f" * 64}],
        )
        self.assertFalse(
            uploader.validate_resume_images_only_state(wrong_cover, True, cover_source)["verified"]
        )


class BrowserFlowSourceContractTests(unittest.TestCase):
    def test_result_ok_is_gated_by_reload_persistence(self):
        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        self.assertIn('await page.reload(wait_until="domcontentloaded"', source)
        self.assertIn('"persistence_verified": persistence_evidence["verified"]', source)
        self.assertIn('"verification_contract": VERIFICATION_CONTRACT', source)
        self.assertIn('final["verification_contract"] == VERIFICATION_CONTRACT', source)
        self.assertIn('and final["persistence_verified"]', source)
        self.assertIn(
            'and final["persistence_evidence"]["final_media_contract"]["valid"]',
            source,
        )
        self.assertIn('final["body_media_count"] == final["expected_body_media"]', source)
        self.assertIn('final["tableCount"] == final["expected_table_count"]', source)
        self.assertIn("visible_matrix_matches", source)
        self.assertIn("media_signatures_persisted", source)
        self.assertIn("mediaStripReliable", source)
        self.assertIn("data-x-uploader-verified-media-key", source)
        self.assertIn("page.context.request.get(source_url", source)
        self.assertIn("page.context.new_page()", source)
        self.assertIn('item.pop("sourceUrl", "")', source)
        self.assertIn('"context-fetch"', source)
        self.assertIn('"browser-page-fetch"', source)
        self.assertIn("MEDIA_START_MARKER", source)
        self.assertIn("has_composer_start_media", source)
        self.assertIn("[MEDIA_START_MARKER]", source)
        self.assertIn("ensure_marker_removed(page, MEDIA_START_MARKER)", source)
        self.assertIn("composer_start_marker_removal_observation_uncertain", source)
        self.assertNotIn("Verified media binding keys do not match composer roots", source)
        self.assertNotIn("could not be bound to exactly one hosted media signature", source)
        self.assertIn('"expected_source_sample_id": item["source_visual_sample_id"]', source)
        self.assertIn('"source_natural_width": item["source_natural_width"]', source)
        self.assertIn('"source_natural_height": item["source_natural_height"]', source)
        self.assertNotIn('[role="group"][aria-label="媒体"]', source)

    def test_post_reload_media_failure_reports_media_phase_not_cover_phase(self):
        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        media_phase = source.index('args._last_phase = "verify_post_reload_media_persistence"')
        media_validation = source.index("post_reload_media_evidence = validate_composer_media_evidence(")
        media_failure = source.index("Post-reload composer media persistence verification failed")
        self.assertLess(media_phase, media_validation)
        self.assertLess(media_validation, media_failure)
        self.assertNotIn(
            'args._last_phase = "verify_post_reload_cover"',
            source[media_phase:media_failure],
        )

    def test_embedded_anchor_normalizers_trim_before_outer_pipe_removal(self):
        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        canonical_tail = """.replace(/\\u00a0/g,' ')
                  .normalize('NFC')
                  .trim()"""
        structural_tail = """.replace(/^\\d+[.)、]\\s*/,'')
                  .replace(/^\\|+|\\|+$/g,'');
                return text.replace(/\\s+/g,' ').trim();"""
        # composer_media_items and find_target each carry the DOM-visible
        # normalizer. Both must match the host validator for leading spaces,
        # outer pipes, NFC, and zero-width boundaries.
        self.assertEqual(source.count(canonical_tail), 2)
        self.assertEqual(source.count(structural_tail), 2)
        fixture = json.loads(
            (SKILL_ROOT / "tests/anchor_normalization_vectors.json").read_text(encoding="utf-8")
        )
        vectors = {item["name"]: item for item in fixture["normalization_vectors"]}
        for name in ("outer-pipes-after-leading-space", "zero-width-before-combining-mark"):
            vector = vectors[name]
            self.assertEqual(
                uploader.normalize_visible_media_anchor(vector["actual"]),
                vector["normalized_actual"],
            )

    def test_replacement_clear_precedes_new_writes_and_resume_skips_it(self):
        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        clear_call = source.index("await clear_existing_draft_for_replacement(")
        cover_write = source.index("set_input_files(data[\"cover_image\"])")
        title_write = source.index(".fill(args.title or data[\"title\"])")
        body_write = source.index("editor.dispatchEvent(new ClipboardEvent('paste'", clear_call)
        self.assertLess(clear_call, cover_write)
        self.assertLess(clear_call, title_write)
        self.assertLess(clear_call, body_write)
        self.assertIn('"mode": "resume_images_only"', source)
        resume_guard = source.index("validate_resume_images_only_state(", source.index("if args.resume_images_only:"))
        first_resume_insert = source.index("paste_image_at_current_selection", resume_guard)
        self.assertLess(resume_guard, first_resume_insert)
        self.assertIn("resume_baseline_observation_uncertain", source)
        self.assertIn("replacement_baseline_observation_uncertain", source)
        reload_core = source[
            source.index("reload_core_persistence_verified = bool("):
            source.index("autosave_resolution =", source.index("reload_core_persistence_verified = bool("))
        ]
        final_gate = source[
            source.index('args._last_phase = "final_success_gate"'):
            source.index("if not ok:", source.index('args._last_phase = "final_success_gate"'))
        ]
        for diagnostic_only in (
            "paste_bindings_verified",
            "replacement_baseline_verified",
            "hosted_media_identity_persisted",
        ):
            self.assertNotIn(diagnostic_only, reload_core)
            self.assertNotIn(diagnostic_only, final_gate)

    def test_autosave_is_bounded_and_failure_envelope_is_written(self):
        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        self.assertIn("begin_autosave_epoch", source)
        self.assertIn("'#detail-header'", source)
        self.assertIn("saving_to_saved_transitions", source)
        self.assertIn("post_mutation_saved_observations", source)
        self.assertIn("departure_to_saved_transitions", source)
        self.assertIn("state:'departed'", source)
        self.assertIn("departureReason:'departed_or_unclassified'", source)
        self.assertIn("previousToken:previous.token || ''", source)
        self.assertIn("lastMutationSequence", source)
        self.assertIn('"saveText": save_text', source)
        self.assertIn("reload_persistence_fallback", source)
        self.assertIn("autosave_ui_evidence_missing", source)
        self.assertIn("autosave_epoch_tracking_unavailable", source)
        self.assertIn("body_paste_observation_uncertain", source)
        self.assertIn("cover_upload_observation_uncertain", source)
        self.assertIn("inserted_table_visible_observation_uncertain", source)
        self.assertIn("diagnostic_screenshot_failed", source)
        self.assertNotIn("Verified autosave evidence did not retain its saved-state text", source)
        self.assertNotIn(
            'for table in final["inserted_tables"]',
            source[source.index('args._last_phase = "final_success_gate"'):],
        )
        self.assertLess(
            source.index('args._last_phase = "final_success_gate"'),
            source.index('args._last_phase = "write_success_screenshot"'),
        )
        self.assertLess(
            source.index('args._last_phase = "write_success_screenshot"'),
            source.index('args._last_phase = "write_success_result"'),
        )
        self.assertNotIn("document.body?.innerText", source)
        self.assertNotIn("document.body.innerText", source)
        self.assertIn('"status": "partial"', source)
        self.assertIn('"phase": getattr(args, "_last_phase"', source)
        self.assertIn("UPLOAD_PARTIAL", source)

    def test_result_json_uses_atomic_replace_for_success_and_failure(self):
        handle = mock.MagicMock()
        handle.name = "/virtual/.result.json.unit.tmp"
        handle.fileno.return_value = 41
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        with (
            mock.patch.object(uploader.tempfile, "NamedTemporaryFile", return_value=handle) as temporary,
            mock.patch.object(uploader.os, "fsync") as fsync,
            mock.patch.object(uploader.os, "replace") as replace,
        ):
            uploader.atomic_write_result_json("/virtual/result.json", {"status": "partial"})
        temporary.assert_called_once()
        handle.write.assert_called_once_with('{\n  "status": "partial"\n}')
        fsync.assert_called_once_with(41)
        replace.assert_called_once_with("/virtual/.result.json.unit.tmp", Path("/virtual/result.json"))

        source = (SKILL_ROOT / "scripts/upload_markdown_to_x_article.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("atomic_write_result_json(args.result_json"), 2)
        self.assertNotIn("Path(args.result_json).write_text", source)


if __name__ == "__main__":
    unittest.main()
