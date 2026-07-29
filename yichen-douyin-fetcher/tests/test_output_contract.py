import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import artifacts
import download
import download_author
from download import get_best_video_stream


class OutputContractTests(unittest.TestCase):
    def test_browser_launch_falls_back_to_installed_chrome(self):
        playwright = Mock()
        browser = Mock()
        playwright.chromium.launch.side_effect = [
            download.PlaywrightError("Executable doesn't exist"),
            browser,
        ]

        launched = download.launch_compatible_browser(playwright, headless=True)

        self.assertIs(browser, launched)
        self.assertEqual(
            [
                unittest.mock.call(headless=True),
                unittest.mock.call(channel="chrome", headless=True),
            ],
            playwright.chromium.launch.call_args_list,
        )

    def test_direct_browser_launch_bypasses_system_proxy(self):
        playwright = Mock()
        browser = Mock()
        playwright.chromium.launch.return_value = browser

        launched = download.launch_compatible_browser(
            playwright,
            headless=True,
            direct=True,
        )

        self.assertIs(browser, launched)
        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            args=["--no-proxy-server"],
        )

    def test_playwright_temp_environment_is_isolated_and_restored(self):
        keys = ("TMPDIR", "TMP", "TEMP")
        previous = {key: os.environ.get(key) for key in keys}
        runtime_path = None

        with patch.object(download, "sync_playwright") as factory:
            expected = factory.return_value.__enter__.return_value
            with download.isolated_sync_playwright() as playwright:
                self.assertIs(expected, playwright)
                runtime_path = Path(os.environ["TMPDIR"])
                self.assertTrue(runtime_path.is_dir())
                self.assertEqual({os.environ[key] for key in keys}, {str(runtime_path)})

        self.assertIsNotNone(runtime_path)
        self.assertFalse(runtime_path.exists())
        self.assertEqual(previous, {key: os.environ.get(key) for key in keys})

    def test_selects_highest_compatible_1080p_stream(self):
        aweme = {
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 1_900_000,
                        "is_h265": 0,
                        "play_addr": {"width": 576, "height": 1024, "url_list": ["540"]},
                    },
                    {
                        "bit_rate": 2_600_000,
                        "is_h265": 0,
                        "play_addr": {"width": 1080, "height": 1920, "url_list": ["1080"]},
                    },
                    {
                        "bit_rate": 2_200_000,
                        "is_h265": 0,
                        "play_addr": {
                            "width": 1080,
                            "height": 1920,
                            "url_list": ["1080-alternative"],
                        },
                    },
                    {
                        "bit_rate": 5_000_000,
                        "is_h265": 1,
                        "play_addr": {"width": 2160, "height": 3840, "url_list": ["4k-h265"]},
                    },
                ]
            }
        }

        stream = get_best_video_stream(aweme)

        self.assertEqual("1080", stream["url"])
        self.assertEqual(["1080", "1080-alternative"], stream["urls"])
        self.assertTrue(artifacts.is_at_least_1080p(stream["width"], stream["height"]))

    def test_720p_does_not_satisfy_default_quality_gate(self):
        self.assertFalse(artifacts.is_at_least_1080p(720, 1280))
        self.assertTrue(artifacts.is_at_least_1080p(1080, 1920))
        self.assertTrue(artifacts.is_at_least_1080p(1920, 1080))
        self.assertTrue(artifacts.is_known_below_1080p(720, 1280))
        self.assertFalse(artifacts.is_known_below_1080p(0, 0))

    def test_1080p_h265_file_does_not_satisfy_h264_contract(self):
        with patch.object(
            artifacts,
            "probe_video",
            return_value={"width": 1080, "height": 1920, "codec_name": "hevc"},
        ):
            with self.assertRaisesRegex(ValueError, "H.264"):
                artifacts.require_1080p_file(Path("video.mp4"))

    def test_untrusted_page_url_is_rejected_before_browser_use(self):
        with self.assertRaisesRegex(ValueError, "不受信任"):
            download.normalize_url("http://127.0.0.1:8765/video/12345678")

    def test_media_referer_drops_query_secrets(self):
        referer = download.safe_douyin_referer(
            "https://www.douyin.com/video/12345678?token=secret#fragment"
        )

        self.assertEqual("https://www.douyin.com/video/12345678", referer)
        self.assertNotIn("secret", referer)

    def test_direct_http_ignores_environment_proxy_settings(self):
        session = Mock()
        response = Mock()
        session.get.return_value = response

        with (
            patch.object(download.requests, "Session", return_value=session),
            patch.object(download.requests, "get") as environment_request,
        ):
            with download.http_response(
                "https://example.invalid/media",
                direct=True,
                timeout=10,
            ) as actual:
                self.assertIs(response, actual)

        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with("https://example.invalid/media", timeout=10)
        environment_request.assert_not_called()
        response.close.assert_called_once_with()
        session.close.assert_called_once_with()

    def test_private_metadata_persists_only_canonical_public_url(self):
        metadata = download.build_metadata(
            {"aweme_id": "12345678", "aweme_data": {"aweme_id": "12345678"}},
            "https://www.douyin.com/video/12345678?token=secret#fragment",
        )

        self.assertEqual("https://www.douyin.com/video/12345678", metadata["source_url"])
        self.assertNotIn("secret", str(metadata))

    def test_fallback_stream_selection_still_chooses_highest_resolution(self):
        aweme = {
            "video": {
                "play_addr": {"width": 720, "height": 1280, "url_list": ["720"]},
                "play_addr_h264": {
                    "width": 1080,
                    "height": 1920,
                    "url_list": ["1080-primary", "1080-backup"],
                },
            }
        }

        stream = get_best_video_stream(aweme)

        self.assertEqual("1080-primary", stream["url"])
        self.assertEqual(["1080-primary", "1080-backup"], stream["urls"])

    def test_string_video_url_is_not_split_into_characters(self):
        aweme = {
            "video": {
                "play_addr_h264": {
                    "width": 1080,
                    "height": 1920,
                    "url_list": "https://example.invalid/video.mp4",
                }
            }
        }

        stream = get_best_video_stream(aweme)

        self.assertEqual(["https://example.invalid/video.mp4"], stream["urls"])

    def test_explicit_1080p_h264_fallback_beats_generic_4k_address(self):
        aweme = {
            "video": {
                "play_addr": {"width": 2160, "height": 3840, "url_list": ["generic-4k"]},
                "play_addr_h264": {
                    "width": 1080,
                    "height": 1920,
                    "url_list": ["h264-1080"],
                },
            }
        }

        stream = get_best_video_stream(aweme)

        self.assertEqual("h264-1080", stream["url"])

    def test_video_folder_is_human_readable_and_unique(self):
        item = {
            "aweme_id": "7667067131854327082",
            "create_time": 1785148680,
            "desc": '贵州/海鲜：真的好吃吗？',
        }

        folder = artifacts.readable_video_folder(item)

        self.assertRegex(folder, r"^\d{4}-\d{2}-\d{2}_贵州／海鲜：真的好吃吗？_\[54327082\]$")

    def test_custom_batch_root_still_contains_creator_directory(self):
        author = {"nickname": "测试博主", "uid": "12345678"}

        resolved = download_author.resolve_output_dir("/tmp/download-root", author, [])

        self.assertEqual(
            Path("/tmp/download-root/抖音_博主_测试博主_[12345678]"), resolved
        )

    def test_missing_publish_time_stays_human_readable(self):
        item = {"aweme_id": "12345678", "desc": "没有发布时间的视频"}

        self.assertEqual(
            "未知日期_没有发布时间的视频_[12345678]",
            artifacts.readable_video_folder(item),
        )

    def test_asr_output_becomes_plain_chinese_script(self):
        source = "【完整文字】\n第一句。第二句！\n【分段时间戳】\n[0:00 - 0:03] 第一句。"

        self.assertEqual("第一句。第二句！\n", artifacts.clean_chinese_transcript(source))

    def test_native_chinese_caption_is_preferred_and_has_no_timestamps(self):
        aweme = {
            "video": {
                "subtitle_infos": [
                    {"language_code": "en", "url_list": ["https://example.invalid/en.srt"]},
                    {
                        "languageCode": "zh-CN",
                        "captionDownloadAddr": {
                            "urlList": ["https://example.invalid/zh.srt"]
                        },
                    },
                ]
            }
        }
        response = Mock()
        response.text = (
            "1\n00:00:00,000 --> 00:00:02,000\n第一句。\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n第二句！\n"
        )
        response.raise_for_status.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript_path = root / "内容" / artifacts.TRANSCRIPT_FILENAME
            with (
                patch.object(download, "STATE_ROOT", root / "机器状态"),
                patch.object(download.requests, "get", return_value=response) as request,
            ):
                source, saved = download.create_chinese_transcript(
                    aweme,
                    root / "内容" / artifacts.VIDEO_FILENAME,
                    transcript_path,
                    "12345678",
                    "https://www.douyin.com/video/12345678",
                )

            self.assertEqual("平台字幕", source)
            self.assertEqual(transcript_path, saved)
            self.assertEqual("第一句。\n第二句！\n", saved.read_text(encoding="utf-8"))
            self.assertEqual("https://example.invalid/zh.srt", request.call_args.args[0])
            self.assertTrue((root / "机器状态" / "captions" / "12345678" / "平台字幕.txt").is_file())

    def test_native_json_caption_becomes_plain_transcript(self):
        body = '{"utterances":[{"text":"第一句。","start_time":0},{"text":"第二句！","start_time":2}]}'

        self.assertEqual("第一句。\n第二句！\n", download.caption_body_to_transcript(body))

    def test_non_chinese_platform_caption_does_not_masquerade_as_chinese_script(self):
        aweme = {
            "video": {
                "subtitle_infos": [
                    {"language_code": "en", "url_list": ["https://example.invalid/en.srt"]}
                ]
            }
        }
        response = Mock()
        response.headers = {"Content-Type": "text/plain"}
        response.text = "1\n00:00:00,000 --> 00:00:02,000\nEnglish only.\n"
        response.raise_for_status.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / artifacts.TRANSCRIPT_FILENAME
            with (
                patch.object(download.requests, "get", return_value=response),
                patch.object(
                    download,
                    "require_asr_backend",
                    side_effect=RuntimeError("中文口播稿转写缺少私有配置"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "待转写"):
                    download.create_chinese_transcript(
                        aweme,
                        Path(temp_dir) / artifacts.VIDEO_FILENAME,
                        transcript_path,
                        "12345678",
                        "https://www.douyin.com/video/12345678",
                    )

            self.assertFalse(transcript_path.exists())

    def test_missing_native_caption_defers_to_asr_without_blocking_video_download(self):
        with (
            patch.object(download, "download_native_transcript", return_value=None),
            patch.object(
                download,
                "require_asr_backend",
                side_effect=RuntimeError("中文口播稿转写缺少私有配置"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "待转写"):
                download.create_chinese_transcript(
                    {},
                    Path("视频.mp4"),
                    Path("中文口播稿.txt"),
                    "12345678",
                    "https://www.douyin.com/video/12345678",
                )

    def test_batch_keeps_1080p_video_when_transcript_is_pending(self):
        item = {
            "aweme_id": "12345678",
            "create_time": 1785148680,
            "desc": "等待口播稿",
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 2_600_000,
                        "is_h265": 0,
                        "play_addr": {
                            "width": 1080,
                            "height": 1920,
                            "url_list": ["https://example.invalid/video"],
                        },
                    }
                ],
                "subtitle_infos": [
                    {
                        "language_code": "zh-CN",
                        "url_list": ["https://example.invalid/stale-caption"],
                    }
                ],
            },
        }

        def fake_download(_urls, output_path, referer, validator=None, direct=False):
            Path(output_path).write_bytes(b"test-video")
            if validator:
                validator(Path(output_path))
            return output_path

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "用户目录"
            with (
                patch.object(download_author, "download_video", side_effect=fake_download),
                patch.object(
                    download_author,
                    "require_1080p_file",
                    return_value={"width": 1080, "height": 1920},
                ),
                patch.object(
                    download_author,
                    "create_chinese_transcript",
                    side_effect=RuntimeError("未发现可用平台字幕，中文口播稿待转写"),
                ),
                patch.object(
                    download_author,
                    "fetch_video_info",
                    return_value={"aweme_data": item},
                ) as fetch_detail,
                patch.object(
                    download_author,
                    "download_native_transcript",
                    return_value=None,
                ),
            ):
                result = download_author.download_batch(
                    [item],
                    output_root,
                    "https://www.douyin.com/user/test",
                    delay=0,
                    storage_state="authorized-state.json",
                )

            video_dir = output_root / artifacts.readable_video_folder(item)
            self.assertTrue((video_dir / artifacts.VIDEO_FILENAME).is_file())
            self.assertFalse((video_dir / artifacts.TRANSCRIPT_FILENAME).exists())
            self.assertEqual(1, len(result["pending_transcript"]))
            self.assertEqual([], result["failed"])
            self.assertEqual(
                "authorized-state.json", fetch_detail.call_args.kwargs["storage_state"]
            )

    def test_low_resolution_failure_does_not_leave_empty_title_folder(self):
        item = {
            "aweme_id": "87654321",
            "create_time": 1785148680,
            "desc": "低画质",
            "video": {
                "play_addr_h264": {
                    "width": 720,
                    "height": 1280,
                    "url_list": ["https://example.invalid/720"],
                }
            },
        }
        detail = {
            "video_url": "https://example.invalid/720",
            "video_stream": get_best_video_stream(item),
            "aweme_data": item,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "用户目录"
            with patch.object(download_author, "fetch_video_info", return_value=detail):
                result = download_author.download_batch(
                    [item], output_root, "https://www.douyin.com/user/test", delay=0
                )

            self.assertEqual(1, len(result["failed"]))
            self.assertFalse((output_root / artifacts.readable_video_folder(item)).exists())

    def test_video_download_tries_backup_url_and_removes_partial_failure(self):
        response = Mock()
        response.headers = {"Content-Length": "5"}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"video"]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "视频.mp4.part"
            with patch.object(
                download.requests,
                "get",
                side_effect=[download.requests.ConnectionError("temporary"), response],
            ) as request:
                saved = download.download_video(
                    ["https://example.invalid/primary", "https://example.invalid/backup"],
                    str(output),
                )

            self.assertEqual(str(output), saved)
            self.assertEqual(b"video", output.read_bytes())
            self.assertEqual(2, request.call_count)

    def test_video_download_rejects_html_and_content_length_mismatch(self):
        html_response = Mock()
        html_response.headers = {"Content-Type": "text/html", "Content-Length": "18"}
        html_response.raise_for_status.return_value = None
        html_response.iter_content.return_value = [b"<html>error</html>"]
        short_response = Mock()
        short_response.headers = {"Content-Type": "video/mp4", "Content-Length": "10"}
        short_response.raise_for_status.return_value = None
        short_response.iter_content.return_value = [b"short"]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "视频.mp4.part"
            with patch.object(
                download.requests,
                "get",
                side_effect=[html_response, short_response],
            ):
                with self.assertRaisesRegex(RuntimeError, "所有视频地址均下载失败"):
                    download.download_video(
                        ["https://example.invalid/html", "https://example.invalid/short"],
                        str(output),
                    )

            self.assertFalse(output.exists())

    def test_post_download_media_validation_can_fall_back_to_backup(self):
        primary = Mock()
        primary.headers = {"Content-Type": "video/mp4", "Content-Length": "7"}
        primary.raise_for_status.return_value = None
        primary.iter_content.return_value = [b"primary"]
        backup = Mock()
        backup.headers = {"Content-Type": "video/mp4", "Content-Length": "6"}
        backup.raise_for_status.return_value = None
        backup.iter_content.return_value = [b"backup"]
        validator = Mock(side_effect=[ValueError("bad primary"), None])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "视频.mp4.part"
            with patch.object(download.requests, "get", side_effect=[primary, backup]):
                download.download_video(
                    ["https://example.invalid/primary", "https://example.invalid/backup"],
                    str(output),
                    validator=validator,
                )

            self.assertEqual(b"backup", output.read_bytes())
            self.assertEqual(2, validator.call_count)

    def test_scan_timeout_is_partial_but_explicit_limit_is_not_an_error(self):
        self.assertTrue(download_author.scan_result_is_partial("timeout"))
        self.assertTrue(download_author.scan_result_is_partial("idle"))
        self.assertFalse(download_author.scan_result_is_partial("complete"))
        self.assertFalse(download_author.scan_result_is_partial("limit"))
        self.assertFalse(download_author.scan_result_is_partial("targets"))

    def test_resume_manifest_preserves_confirmed_video_set_and_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "抖音_博主_测试_[12345678]"
            state_root = root / "机器状态"
            state_dir = (
                state_root
                / "jobs"
                / f"author_{artifacts.output_state_key(output)}"
            )
            state_dir.mkdir(parents=True)
            manifest_path = state_dir / "抓取清单.json"
            manifest_path.write_text(
                '{"profile_url":"https://www.douyin.com/user/test","stopped_reason":"limit",'
                '"videos":[{"aweme_id":"2","title":"第二条"},{"aweme_id":"1","title":"第一条"}]}',
                encoding="utf-8",
            )

            with patch.object(download_author, "STATE_ROOT", state_root):
                found_path, _manifest, items = download_author.load_resume_manifest(output)

            self.assertEqual(manifest_path, found_path)
            self.assertEqual(["2", "1"], [item["aweme_id"] for item in items])

            discovered = [
                {"aweme_id": "1", "desc": "变化后的标题", "video": {"marker": "first"}},
                {"aweme_id": "2", "desc": "变化后的标题", "video": {"marker": "second"}},
            ]
            ordered = download_author.order_confirmed_items(items, discovered)
            self.assertEqual(["2", "1"], [item["aweme_id"] for item in ordered])
            self.assertEqual(["第二条", "第一条"], [item["desc"] for item in ordered])

    def test_corrupt_resume_manifest_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "抖音_博主_测试_[12345678]"
            state_root = root / "机器状态"
            state_dir = (
                state_root
                / "jobs"
                / f"author_{artifacts.output_state_key(output)}"
            )
            state_dir.mkdir(parents=True)
            manifest_path = state_dir / "抓取清单.json"
            manifest_path.write_text("{broken", encoding="utf-8")

            with patch.object(download_author, "STATE_ROOT", state_root):
                with self.assertRaisesRegex(RuntimeError, "损坏"):
                    download_author.load_resume_manifest(output)

            self.assertEqual("{broken", manifest_path.read_text(encoding="utf-8"))

    def test_machine_state_is_outside_visible_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "抖音_博主_测试"
            state = artifacts.job_state_dir("author-1", output)

        self.assertNotEqual(output, state)
        self.assertNotIn(output, state.parents)

    def test_batch_output_contains_only_video_and_chinese_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_root = root / "用户目录"
            state_root = root / "机器状态"
            fake_asr = root / "fake_asr.py"
            fake_asr.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[1] + '.txt').write_text("
                "'【完整文字】\\n这是中文口播稿。\\n【分段时间戳】\\n[0:00] 这是中文口播稿。', "
                "encoding='utf-8')\n",
                encoding="utf-8",
            )
            item = {
                "aweme_id": "7667067131854327082",
                "create_time": 1785148680,
                "desc": "标题创建文件夹",
                "author": {"nickname": "测试博主"},
                "video": {
                    "bit_rate": [
                        {
                            "bit_rate": 2_600_000,
                            "is_h265": 0,
                            "play_addr": {
                                "width": 1080,
                                "height": 1920,
                                "url_list": ["https://example.invalid/video"],
                            },
                        }
                    ]
                },
            }

            def fake_download(_url, output_path, referer, validator=None, direct=False):
                Path(output_path).write_bytes(b"test-video")
                if validator:
                    validator(Path(output_path))
                return output_path

            def fake_audio(_video_path, state_dir):
                artifacts.ensure_private_dir(state_dir)
                audio_path = state_dir / "转写音频.m4a"
                audio_path.write_bytes(b"test-audio")
                return audio_path

            with (
                patch.object(artifacts, "STATE_ROOT", state_root),
                patch.object(artifacts, "extract_audio_for_asr", side_effect=fake_audio),
                patch.object(download_author, "download_video", side_effect=fake_download),
                patch.object(
                    download_author,
                    "require_1080p_file",
                    return_value={"width": 1080, "height": 1920, "codec_name": "h264"},
                ),
            ):
                result = download_author.download_batch(
                    [item],
                    output_root,
                    "https://www.douyin.com/user/test",
                    delay=0,
                    asr_script=fake_asr,
                )

            video_dir = output_root / artifacts.readable_video_folder(item)
            self.assertEqual(1, result["completed"])
            self.assertEqual([], result["failed"])
            self.assertEqual(
                {artifacts.VIDEO_FILENAME, artifacts.TRANSCRIPT_FILENAME},
                {path.name for path in video_dir.iterdir()},
            )
            self.assertEqual(
                "这是中文口播稿。\n",
                (video_dir / artifacts.TRANSCRIPT_FILENAME).read_text(encoding="utf-8"),
            )
            self.assertTrue(
                (state_root / "asr" / item["aweme_id"] / "转写音频.m4a.txt").is_file()
            )


if __name__ == "__main__":
    unittest.main()
