import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "zhihu_adapter", ROOT / "scripts" / "zhihu_adapter.py"
)
ZHIHU = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ZHIHU
SPEC.loader.exec_module(ZHIHU)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def search_item(**overrides):
    item = {
        "Title": "RAG 评测方法综述",
        "ContentType": "Article",
        "ContentID": "123456789",
        "ContentText": "搜索摘要，不是原文。",
        "Url": (
            "https://zhuanlan.zhihu.com/p/123456789"
            "?utm_medium=openapi_platform&utm_source=test&foo=bar"
        ),
        "CommentCount": 15,
        "VoteUpCount": 128,
        "AuthorName": "张三",
        "EditTime": 1710000000,
        "CommentInfoList": [{"Content": "一条精选评论"}],
        "AuthorityLevel": "2",
        "RankingScore": 0.98,
    }
    item.update(overrides)
    return item


def response(items, **data_overrides):
    data = {"HasMore": False, "Items": items}
    data.update(data_overrides)
    return json.dumps({"Code": 0, "Message": "success", "Data": data})


class ZhihuAdapterTests(unittest.TestCase):
    def normalize_search(self, items, limit=10):
        return ZHIHU.normalize_response(
            command="search",
            query="RAG",
            limit=limit,
            stdout=response(items),
            now=NOW,
        )

    def normalize_hot(self, items, limit=30):
        return ZHIHU.normalize_response(
            command="hot",
            query=ZHIHU.HOT_QUERY,
            limit=limit,
            stdout=response(items, Total=len(items)),
            now=NOW,
        )

    def test_cli_path_can_be_overridden_without_a_personal_absolute_path(self):
        module_name = "zhihu_adapter_portability_test"
        spec = importlib.util.spec_from_file_location(
            module_name, ROOT / "scripts" / "zhihu_adapter.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        with mock.patch.dict(os.environ, {"ZHIHU_CLI": "/opt/zhihu-cli"}):
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            finally:
                sys.modules.pop(module_name, None)
        self.assertEqual(module.ZHIHU_CLI, pathlib.Path("/opt/zhihu-cli"))

    def test_relative_cli_override_is_rejected(self):
        with mock.patch.object(ZHIHU, "ZHIHU_CLI", pathlib.Path("zhihu-cli")):
            with self.assertRaises(ZHIHU.AdapterError) as caught:
                ZHIHU._cli_argv(
                    "search", query="public query", limit=1, timeout=10
                )
        self.assertEqual(caught.exception.category, "configuration_error")

    def test_search_maps_cli_fields_without_faking_publication_time(self):
        envelope = self.normalize_search([search_item()])
        candidate = envelope["candidates"][0]
        self.assertEqual(candidate["candidate_id"], "zhihu:article:123456789")
        self.assertEqual(candidate["backend"], "zhihu-open-platform-cli")
        self.assertEqual(candidate["platform"], "zhihu")
        self.assertEqual(candidate["content_type"], "zhihu_article")
        self.assertEqual(candidate["metrics"]["likes"], 128)
        self.assertEqual(candidate["metrics"]["comments"], 15)
        self.assertIsNone(candidate["published_at"])
        fields = candidate["platform_fields"]["zhihu"]
        self.assertEqual(fields["updated_at"], "2024-03-09T16:00:00Z")
        self.assertEqual(fields["authority_level"], "2")
        self.assertEqual(fields["ranking_score"], 0.98)
        self.assertEqual(fields["featured_comments"], ["一条精选评论"])
        self.assertEqual(candidate["verification"]["status"], "candidate")
        self.assertFalse(candidate["verification"]["opened_original"])
        self.assertEqual(candidate["access"]["visibility"], "authenticated_public")
        self.assertTrue(candidate["access"]["login_state_used"])
        self.assertTrue(envelope["routes"][0]["login_state_used"])
        self.assertTrue(envelope["coverage"][0]["login_state_used"])

    def test_url_allowlist_is_exact_and_canonical_removes_only_utm(self):
        envelope = self.normalize_search(
            [
                search_item(),
                search_item(
                    ContentID="2",
                    Url="http://www.zhihu.com/question/2",
                ),
                search_item(
                    ContentID="3",
                    Url="https://www.zhihu.com.evil.example/question/3",
                ),
                search_item(
                    ContentID="4",
                    Url="https://user@www.zhihu.com/question/4",
                ),
            ]
        )
        self.assertEqual(len(envelope["candidates"]), 1)
        candidate = envelope["candidates"][0]
        self.assertEqual(
            candidate["canonical_url"],
            "https://zhuanlan.zhihu.com/p/123456789?foo=bar",
        )
        self.assertIn("utm_medium", candidate["url"])
        self.assertEqual(envelope["routes"][0]["status"], "partial")
        self.assertEqual(envelope["coverage"][0]["rejected_count"], 3)

    def test_url_rejects_whitespace_backslash_and_unsafe_percent_encoding(self):
        unsafe_urls = [
            "https://www.zhihu.com/question/1 evil",
            "https://www.zhihu.com/question/1\u00a0evil",
            "https://www.zhihu.com/question/1\\evil",
            "https://www.zhihu.com/question/1%0aevil",
            "https://www.zhihu.com/question/1%0Devil",
            "https://www.zhihu.com/question/1%00evil",
            "https://www.zhihu.com/question/1%5cevil",
            "https://www.zhihu.com/question/1%250aevil",
            "https://www.zhihu.com/question/1%25250devil",
            "https://www.zhihu.com/question/1%",
            "https://www.zhihu.com/question/1%2",
            "https://www.zhihu.com/question/1%zz",
            "https://www.zhihu.com/question/1?q=%255c",
        ]
        for url in unsafe_urls:
            with self.subTest(url=url):
                self.assertIsNone(ZHIHU.canonicalize_zhihu_url(url))

        self.assertEqual(
            ZHIHU.canonicalize_zhihu_url(
                "https://www.zhihu.com/question/1?q=%E4%B8%AD%E6%96%87"
            ),
            (
                "https://www.zhihu.com/question/1?q=%E4%B8%AD%E6%96%87",
                "https://www.zhihu.com/question/1?q=%E4%B8%AD%E6%96%87",
            ),
        )

    def test_utm_variants_are_deduplicated_by_canonical_url(self):
        envelope = self.normalize_search(
            [
                search_item(ContentID="1", Url="https://www.zhihu.com/question/9?utm_source=a"),
                search_item(ContentID="2", Url="https://www.zhihu.com/question/9?utm_medium=b"),
            ]
        )
        self.assertEqual(len(envelope["candidates"]), 1)
        self.assertEqual(envelope["coverage"][0]["duplicate_count"], 1)
        self.assertEqual(envelope["errors"], [])

    def test_explicit_empty_items_is_a_successful_zero_result(self):
        envelope = self.normalize_search([])
        self.assertEqual(envelope["candidates"], [])
        self.assertEqual(envelope["routes"][0]["status"], "completed")
        self.assertEqual(envelope["errors"], [])
        limitations = envelope["coverage"][0]["limitations"]
        self.assertTrue(any("no pagination" in item for item in limitations))
        self.assertTrue(any("does not expose a time filter" in item for item in limitations))

    def test_nonempty_unparseable_items_cannot_become_successful_zero_results(self):
        envelope = self.normalize_search([{"Title": "missing required fields"}])
        self.assertEqual(envelope["candidates"], [])
        self.assertEqual(envelope["routes"][0]["status"], "failed")
        self.assertEqual(envelope["errors"][0]["category"], "invalid_candidate")

    def test_malformed_or_missing_items_fail_closed(self):
        samples = [
            "not json",
            json.dumps({"Code": 0, "Data": {}}),
            json.dumps({"Code": 0, "Data": {"Items": {}}}),
            json.dumps({"Code": 0, "Data": {"Items": None}}),
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                with self.assertRaises(ZHIHU.AdapterError) as raised:
                    ZHIHU.normalize_response(
                        command="search",
                        query="q",
                        limit=10,
                        stdout=sample,
                        now=NOW,
                    )
                self.assertEqual(raised.exception.category, "invalid_response")

    def test_documented_error_codes_are_sanitized_and_fail_closed(self):
        categories = {
            10001: "invalid_request",
            20001: "authentication_failed",
            30001: "rate_limited",
            90001: "upstream_error",
        }
        for code, category in categories.items():
            raw = json.dumps(
                {
                    "Code": code,
                    "Message": "Bearer TOP-SECRET must never be echoed",
                    "Data": {"Items": [search_item()]},
                }
            )
            with self.subTest(code=code):
                with self.assertRaises(ZHIHU.AdapterError) as raised:
                    ZHIHU.parse_cli_json(raw)
                self.assertEqual(raised.exception.category, category)
                self.assertNotIn("TOP-SECRET", raised.exception.message)

    def test_hot_preserves_order_and_infers_stable_ids_from_public_urls(self):
        envelope = self.normalize_hot(
            [
                {
                    "Title": "问题热榜",
                    "Url": "https://www.zhihu.com/question/111?utm_source=openapi",
                    "Summary": "问题摘要",
                },
                {
                    "Title": "文章热榜",
                    "Url": "https://zhuanlan.zhihu.com/p/222",
                    "Summary": "",
                },
            ]
        )
        candidates = envelope["candidates"]
        self.assertEqual([item["title"] for item in candidates], ["问题热榜", "文章热榜"])
        self.assertEqual([item["rank"] for item in candidates], [1, 2])
        self.assertEqual(candidates[0]["candidate_id"], "zhihu:question:111")
        self.assertEqual(candidates[1]["candidate_id"], "zhihu:article:222")
        self.assertEqual(candidates[0]["platform_fields"]["zhihu"]["hot_rank"], 1)

    def test_subprocess_uses_fixed_binary_and_removes_environment_secret(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=response([]), stderr=""
        )
        with (
            mock.patch.dict(
                os.environ,
                {
                    "PATH": "/usr/bin:/bin",
                    "ZHIHU_ACCESS_SECRET": "TOP-SECRET",  # pragma: allowlist secret
                    "OPENAI_API_KEY": "openai-secret",  # pragma: allowlist secret
                    "GITHUB_TOKEN": "github-secret",  # pragma: allowlist secret
                    "FIRECRAWL_API_KEY": "firecrawl-secret",  # pragma: allowlist secret
                    "YOUTUBE_API_KEY": "youtube-secret",  # pragma: allowlist secret
                },
                clear=True,
            ),
            mock.patch.object(ZHIHU.subprocess, "run", return_value=completed) as runner,
        ):
            stdout = ZHIHU.run_cli(
                "search", query="公开查询", limit=5, timeout=20
            )
        self.assertEqual(stdout, response([]))
        argv = runner.call_args.args[0]
        self.assertEqual(argv[0], str(ZHIHU.ZHIHU_CLI))
        self.assertEqual(
            argv[1:],
            [
                "search",
                "zhihu",
                "--query",
                "公开查询",
                "--count",
                "5",
                "--timeout",
                "20s",
            ],
        )
        self.assertNotIn("ZHIHU_ACCESS_SECRET", runner.call_args.kwargs["env"])
        self.assertEqual(runner.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin"})
        self.assertFalse(runner.call_args.kwargs["check"])

    def test_hot_subprocess_shape_is_fixed(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=response([], Total=0), stderr=""
        )
        with mock.patch.object(ZHIHU.subprocess, "run", return_value=completed) as runner:
            ZHIHU.run_cli("hot", query=None, limit=7, timeout=15)
        self.assertEqual(
            runner.call_args.args[0],
            [
                str(ZHIHU.ZHIHU_CLI),
                "hot",
                "--limit",
                "7",
                "--timeout",
                "15s",
            ],
        )

    def test_timeout_missing_binary_and_nonzero_exit_do_not_leak_process_output(self):
        failures = [
            (subprocess.TimeoutExpired(["binary", "SECRET"], 1, output="SECRET"), "timeout"),
            (FileNotFoundError("SECRET path"), "missing_binary"),
        ]
        for side_effect, category in failures:
            with self.subTest(category=category):
                with mock.patch.object(ZHIHU.subprocess, "run", side_effect=side_effect):
                    with self.assertRaises(ZHIHU.AdapterError) as raised:
                        ZHIHU.run_cli("hot", query=None, limit=1, timeout=1)
                self.assertEqual(raised.exception.category, category)
                self.assertNotIn("SECRET", raised.exception.message)
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

        completed = subprocess.CompletedProcess(
            args=["SECRET"], returncode=9, stdout="Bearer SECRET", stderr="SECRET"
        )
        with mock.patch.object(ZHIHU.subprocess, "run", return_value=completed):
            with self.assertRaises(ZHIHU.AdapterError) as raised:
                ZHIHU.run_cli("hot", query=None, limit=1, timeout=1)
        self.assertEqual(raised.exception.category, "cli_error")
        self.assertNotIn("SECRET", raised.exception.message)

    def test_search_and_hot_bounds(self):
        valid = [
            ("search", "--query", "q", "--limit", "1"),
            ("search", "--query", "q", "--limit", "10"),
            ("hot", "--limit", "1"),
            ("hot", "--limit", "30"),
        ]
        for argv in valid:
            with self.subTest(argv=argv):
                ZHIHU.parse_args(list(argv))

        invalid = [
            ["search", "--query", "q", "--limit", "0"],
            ["search", "--query", "q", "--limit", "11"],
            ["hot", "--limit", "0"],
            ["hot", "--limit", "31"],
            ["answer", "--query", "q"],
        ]
        for argv in invalid:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ZHIHU.parse_args(argv)

    def test_endpoint_binary_and_key_options_are_rejected_without_echoing_values(self):
        for option in ("--endpoint", "--binary", "--key"):
            stderr = io.StringIO()
            with self.subTest(option=option), redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    ZHIHU.parse_args(
                        ["search", "--query", "q", option, "DO-NOT-ECHO"]
                    )
            self.assertNotIn("DO-NOT-ECHO", stderr.getvalue())

    def test_main_returns_failure_envelope_without_raw_stdout_or_stderr(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="Bearer TOP-SECRET", stderr="TOP-SECRET"
        )
        output = io.StringIO()
        with (
            mock.patch.object(ZHIHU.subprocess, "run", return_value=completed),
            redirect_stdout(output),
        ):
            code = ZHIHU.main(["hot", "--limit", "1"])
        self.assertEqual(code, 2)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["routes"][0]["status"], "failed")
        self.assertEqual(parsed["errors"][0]["category"], "cli_error")
        self.assertNotIn("TOP-SECRET", output.getvalue())


if __name__ == "__main__":
    unittest.main()
