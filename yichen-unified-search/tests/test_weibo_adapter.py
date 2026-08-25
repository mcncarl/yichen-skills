import importlib.util
import json
import os
import pathlib
import sys
import unittest
import urllib.request
from datetime import datetime
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "weibo_adapter", ROOT / "scripts" / "weibo_adapter.py"
)
WEIBO = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = WEIBO
SPEC.loader.exec_module(WEIBO)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


class FakeOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payloads.pop(0))


class StubClient:
    def __init__(self, pages=None, error=None):
        self.pages = pages or {}
        self.error = error
        self.request_count = 0

    def search_page(self, query, page):
        self.request_count += 1
        if self.error:
            raise self.error
        return self.pages.get(page, [])


class FakeCompleted:
    def __init__(self, *, returncode=0, stdout="[]", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, completed):
        self.completed = completed
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.completed


def raw_post(
    post_id,
    *,
    text="公开微博内容",
    created_at="2小时前",
    likes=0,
    comments=1,
    reposts=None,
):
    return {
        "id": post_id,
        "text": text,
        "created_at": created_at,
        "attitudes_count": likes,
        "comments_count": comments,
        "reposts_count": reposts,
        "source": "iPhone客户端",
        "user": {
            "id": "998877",
            "screen_name": "测试用户",
            "verified": False,
            "followers_count": 42,
        },
        "pics": [{"url": "https://example.invalid/not-exposed.jpg"}],
        "page_info": {"type": "video"},
    }


class WeiboAdapterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 24, 14, 30, tzinfo=WEIBO.TZ)

    def test_offline_self_test(self):
        self.assertEqual(WEIBO.self_test()["status"], "passed")
        self.assertFalse(WEIBO.self_test()["network_used"])

    def test_public_client_reuses_one_ephemeral_cookie(self):
        visitor = b'visitor_callback({"data":{"sub":"anon-sub","subp":"anon-subp"}});'
        result = json.dumps({"ok": 1, "data": {"cards": []}}).encode()
        opener = FakeOpener([visitor, result, result])
        client = WEIBO.WeiboPublicClient(
            opener=opener,
            delay_min=0,
            delay_max=0,
            sleeper=lambda _: None,
        )

        self.assertEqual(client.search_page("iPhone 18", 1), [])
        self.assertEqual(client.search_page("iPhone 18", 2), [])

        self.assertEqual(client.request_count, 3)
        self.assertEqual(opener.requests[0][0].get_method(), "POST")
        self.assertNotIn("Cookie", opener.requests[0][0].headers)
        for request, _ in opener.requests[1:]:
            self.assertEqual(request.headers["Cookie"], "SUB=anon-sub; SUBP=anon-subp")

    def test_search_page_extracts_top_level_and_group_posts(self):
        visitor = b'visitor_callback({"data":{"sub":"anon","subp":"anonp"}});'
        payload = {
            "ok": 1,
            "data": {
                "cards": [
                    {"card_type": 9, "mblog": raw_post("1234567890123456")},
                    {
                        "card_type": 11,
                        "card_group": [
                            {
                                "card_type": 9,
                                "mblog": raw_post("2234567890123456"),
                            }
                        ],
                    },
                ]
            },
        }
        opener = FakeOpener([visitor, json.dumps(payload).encode()])
        client = WEIBO.WeiboPublicClient(
            opener=opener,
            delay_min=0,
            delay_max=0,
            sleeper=lambda _: None,
        )
        posts = client.search_page("iPhone 18", 1)
        self.assertEqual([str(post["id"]) for post in posts], [
            "1234567890123456",
            "2234567890123456",
        ])

    def test_ephemeral_cookie_is_never_emitted_in_envelope(self):
        visitor = b'visitor_callback({"data":{"sub":"secret-sub","subp":"secret-subp"}});'
        payload = {
            "ok": 1,
            "data": {
                "cards": [
                    {"card_type": 9, "mblog": raw_post("1234567890123456")}
                ]
            },
        }
        opener = FakeOpener([visitor, json.dumps(payload).encode()])
        client = WEIBO.WeiboPublicClient(
            opener=opener,
            delay_min=0,
            delay_max=0,
            sleeper=lambda _: None,
        )
        result = WEIBO.run_search(
            query="iPhone 18",
            limit=1,
            max_pages=1,
            days=None,
            client=client,
            now=self.now,
        )
        rendered = json.dumps(result)
        self.assertNotIn("secret-sub", rendered)
        self.assertNotIn("secret-subp", rendered)

    def test_normalization_deduplicates_filters_and_preserves_unknowns(self):
        pages = {
            1: [
                raw_post(
                    "1234567890123456",
                    text="<b>iPhone 18</b><br>公开讨论 &amp; 线索",
                    reposts=None,
                ),
                raw_post("1234567890123456"),
                raw_post("2234567890123456", created_at="2026-07-01 08:00"),
                raw_post("bad-id"),
                raw_post("3234567890123456", created_at="未知时间"),
            ],
            2: [],
        }
        client = StubClient(pages)
        result = WEIBO.run_search(
            query="iPhone 18",
            limit=10,
            max_pages=3,
            days=7,
            client=client,
            now=self.now,
        )

        self.assertEqual(result["routes"][0]["status"], "partial")
        self.assertEqual(len(result["candidates"]), 2)
        first = result["candidates"][0]
        self.assertEqual(first["candidate_id"], "weibo:1234567890123456")
        self.assertEqual(first["title"], "iPhone 18 公开讨论 & 线索")
        self.assertEqual(first["metrics"]["likes"], 0)
        self.assertIsNone(first["metrics"]["shares"])
        self.assertEqual(first["verification"]["status"], "candidate")
        self.assertFalse(first["verification"]["opened_original"])
        self.assertNotIn("picture_urls", first["platform_fields"]["weibo"])
        coverage = result["coverage"][0]
        self.assertEqual(coverage["duplicate_count"], 1)
        self.assertEqual(coverage["rejected_count"], 1)
        self.assertEqual(coverage["filtered_outside_window"], 1)
        self.assertEqual(coverage["unknown_time_count"], 1)

    def test_malformed_or_rejected_upstream_is_not_zero_results(self):
        visitor = b'visitor_callback({"data":{"sub":"anon","subp":"anonp"}});'
        scenarios = (
            (b"<html>verification</html>", "access_gate_response"),
            (json.dumps({"ok": 0, "msg": "访问受限"}).encode(), "access_gate_rejected"),
        )
        for payload, category in scenarios:
            with self.subTest(category=category):
                opener = FakeOpener([visitor, payload])
                client = WEIBO.WeiboPublicClient(
                    opener=opener,
                    delay_min=0,
                    delay_max=0,
                    sleeper=lambda _: None,
                )
                result = WEIBO.run_search(
                    query="iPhone 18",
                    limit=10,
                    max_pages=1,
                    days=None,
                    client=client,
                    now=self.now,
                )
                self.assertEqual(result["routes"][0]["status"], "failed")
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["category"], category)
                self.assertTrue(result["coverage"][0]["truncated"])

    def test_explicit_network_failure_is_reported(self):
        client = StubClient(
            error=WEIBO.AdapterError("network_error", "public endpoint unavailable")
        )
        result = WEIBO.run_search(
            query="iPhone 18",
            limit=10,
            max_pages=3,
            days=None,
            client=client,
            now=self.now,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["errors"][0]["category"], "network_error")

    def test_browser_search_is_allowlisted_bounded_and_never_emits_logs(self):
        rows = [
            {
                "rank": 1,
                "author": "测试作者",
                "id": "ReGT8un2O",
                "time": "08月23日 09:54",
                "title": "iPhone 18 公开帖子",
                "url": "https://weibo.com/1563458343/ReGT8un2O?refer_flag=secret",
            }
        ]
        runner = FakeRunner(FakeCompleted(stdout=json.dumps(rows), stderr="Cookie=browser-secret"))
        with mock.patch.dict(
            os.environ,
                {
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/private/home",
                    "OPENCLI_HOME": "/private/opencli-state",
                    "FIRECRAWL_API_KEY": "firecrawl-secret",  # pragma: allowlist secret
                    "BROWSER_COOKIE": "cookie-secret",  # pragma: allowlist secret
                    "OPENAI_API_KEY": "openai-secret",  # pragma: allowlist secret
                    "ANTHROPIC_API_KEY": "anthropic-secret",  # pragma: allowlist secret
                    "GOOGLE_API_KEY": "google-secret",  # pragma: allowlist secret
                    "GITHUB_API_KEY": "github-secret",  # pragma: allowlist secret
                    "AWS_ACCESS_KEY_ID": "aws-secret",  # pragma: allowlist secret
                },
            clear=True,
        ):
            result = WEIBO.run_browser_search(
                query="iPhone 18",
                limit=3,
                days=7,
                timeout=30,
                now=self.now,
                runner=runner,
                opencli_path="/safe/opencli",
            )

        self.assertEqual(result["routes"][0]["backend"], WEIBO.BROWSER_BACKEND)
        self.assertTrue(result["routes"][0]["login_state_used"])
        self.assertEqual(result["candidates"][0]["access"]["visibility"], "authenticated_public")
        self.assertEqual(
            result["candidates"][0]["canonical_url"],
            "https://weibo.com/1563458343/ReGT8un2O",
        )
        rendered = json.dumps(result)
        self.assertNotIn("browser-secret", rendered)
        command, kwargs = runner.calls[0]
        self.assertEqual(command[:4], ["/safe/opencli", "weibo", "search", "iPhone 18"])
        self.assertIn("ephemeral", command)
        self.assertIn("false", command)
        for forbidden in ("publish", "delete", "favorites", "feed", "comments", "me"):
            self.assertNotIn(forbidden, command)
        self.assertFalse(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin:/bin")
        self.assertEqual(kwargs["env"]["OPENCLI_HOME"], "/private/opencli-state")
        for secret_name in (
            "FIRECRAWL_API_KEY",
            "BROWSER_COOKIE",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GITHUB_API_KEY",
            "AWS_ACCESS_KEY_ID",
        ):
            self.assertNotIn(secret_name, kwargs["env"])
        self.assertEqual(
            kwargs["env"],
            {
                "PATH": "/usr/bin:/bin",
                "HOME": "/private/home",
                "OPENCLI_HOME": "/private/opencli-state",
            },
        )

    def test_auto_mode_uses_browser_only_after_access_gate_and_recovers(self):
        client = StubClient(
            error=WEIBO.AdapterError("access_gate_redirect", "verification redirect")
        )
        rows = [
            {
                "author": "测试作者",
                "id": "ReGT8un2O",
                "time": "08月23日 09:54",
                "title": "iPhone 18 公开帖子",
                "url": "https://weibo.com/1563458343/ReGT8un2O",
            }
        ]
        runner = FakeRunner(FakeCompleted(stdout=json.dumps(rows)))
        result = WEIBO.run_search_auto(
            query="iPhone 18",
            limit=3,
            max_pages=3,
            days=7,
            timeout=30,
            now=self.now,
            session_mode="auto",
            client=client,
            runner=runner,
            opencli_path="/safe/opencli",
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(
            [route["backend"] for route in result["routes"]],
            [WEIBO.ANONYMOUS_BACKEND, WEIBO.BROWSER_BACKEND],
        )
        self.assertTrue(result["routes"][0]["browser_fallback_recovered"])
        self.assertEqual(len(runner.calls), 1)

    def test_auto_mode_does_not_use_browser_for_network_failure(self):
        client = StubClient(
            error=WEIBO.AdapterError("network_error", "network unavailable")
        )

        def forbidden_runner(*_args, **_kwargs):
            self.fail("browser fallback must not run for a generic network failure")

        result = WEIBO.run_search_auto(
            query="iPhone 18",
            limit=3,
            max_pages=3,
            days=None,
            timeout=30,
            now=self.now,
            session_mode="auto",
            client=client,
            runner=forbidden_runner,
            opencli_path="/safe/opencli",
        )
        self.assertEqual(result["errors"][0]["category"], "network_error")
        self.assertEqual(len(result["routes"]), 1)

    def test_auto_mode_does_not_use_browser_for_generic_protocol_drift(self):
        client = StubClient(
            error=WEIBO.AdapterError("invalid_response", "unexpected response shape")
        )

        def forbidden_runner(*_args, **_kwargs):
            self.fail("browser fallback must not run for generic protocol drift")

        result = WEIBO.run_search_auto(
            query="iPhone 18",
            limit=3,
            max_pages=3,
            days=None,
            timeout=30,
            now=self.now,
            session_mode="auto",
            client=client,
            runner=forbidden_runner,
            opencli_path="/safe/opencli",
        )
        self.assertEqual(result["errors"][0]["category"], "invalid_response")
        self.assertEqual(len(result["routes"]), 1)

    def test_browser_mode_cannot_be_selected_directly(self):
        with self.assertRaises(SystemExit):
            WEIBO.parse_args(
                ["search", "--query", "public query", "--session-mode", "browser"]
            )
        with self.assertRaises(WEIBO.AdapterError) as caught:
            WEIBO.run_search_auto(
                query="public query",
                limit=3,
                max_pages=1,
                days=None,
                timeout=30,
                now=self.now,
                session_mode="browser",
                client=StubClient(),
                runner=lambda *_args, **_kwargs: self.fail(
                    "direct browser mode must not execute"
                ),
                opencli_path="/safe/opencli",
            )
        self.assertEqual(caught.exception.category, "invalid_session_mode")

    def test_auto_mode_does_not_use_browser_for_non_access_http_failure(self):
        client = StubClient(
            error=WEIBO.AdapterError("http_error", "upstream server error")
        )

        def forbidden_runner(*_args, **_kwargs):
            self.fail("browser fallback must not run for a non-access HTTP failure")

        result = WEIBO.run_search_auto(
            query="iPhone 18",
            limit=3,
            max_pages=3,
            days=None,
            timeout=30,
            now=self.now,
            session_mode="auto",
            client=client,
            runner=forbidden_runner,
            opencli_path="/safe/opencli",
        )
        self.assertEqual(result["errors"][0]["category"], "http_error")
        self.assertEqual(len(result["routes"]), 1)

    def test_browser_row_rejects_mismatched_id_or_unsafe_user_path(self):
        base = {
            "author": "测试作者",
            "id": "ReGT8un2O",
            "time": "08月23日 09:54",
            "title": "iPhone 18 公开帖子",
        }
        mismatched = {
            **base,
            "url": "https://weibo.com/1563458343/DifferentId",
        }
        unsafe = {
            **base,
            "url": "https://weibo.com/../ReGT8un2O",
        }
        self.assertIsNone(
            WEIBO.normalize_browser_row(
                mismatched,
                query="iPhone 18",
                retrieved_at=self.now.isoformat(),
                now=self.now,
            )
        )
        self.assertIsNone(
            WEIBO.normalize_browser_row(
                unsafe,
                query="iPhone 18",
                retrieved_at=self.now.isoformat(),
                now=self.now,
            )
        )

    def test_browser_failure_does_not_echo_stderr_or_cookie(self):
        runner = FakeRunner(
            FakeCompleted(returncode=9, stderr="Cookie=browser-secret Authorization=secret")
        )
        result = WEIBO.run_browser_search(
            query="iPhone 18",
            limit=3,
            days=None,
            timeout=30,
            now=self.now,
            runner=runner,
            opencli_path="/safe/opencli",
        )
        rendered = json.dumps(result)
        self.assertEqual(result["errors"][0]["category"], "browser_search_error")
        self.assertNotIn("browser-secret", rendered)
        self.assertNotIn("Authorization=secret", rendered)

    def test_parser_enforces_query_result_page_and_time_bounds(self):
        invalid_argv = (
            ["search", "--query", "", "--limit", "10"],
            ["search", "--query", "q", "--limit", "21"],
            ["search", "--query", "q", "--max-pages", "4"],
            ["search", "--query", "q", "--days", "0"],
        )
        for argv in invalid_argv:
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                WEIBO.parse_args(argv)

    def test_source_has_no_comment_cookie_store_shell_or_persistence_surface(self):
        source = (ROOT / "scripts" / "weibo_adapter.py").read_text(encoding="utf-8")
        for forbidden in (
            "api/comments/show",
            "HTTPCookieProcessor",
            "MozillaCookieJar",
            "CookieJar",
            "use_env_proxy",
            "pathlib",
            "write_text",
            "shell=True",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("urllib.request.ProxyHandler({})", source)
        self.assertIn("RejectRedirects", source)
        self.assertIn('"search"', source)
        self.assertIn('"--site-session"', source)
        self.assertIn('"--keep-tab"', source)


if __name__ == "__main__":
    unittest.main()
