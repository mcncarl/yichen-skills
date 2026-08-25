import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIRECRAWL = load_module("firecrawl_adapter", "scripts/firecrawl_adapter.py")
ANYSEARCH = load_module("firecrawl_test_anysearch", "scripts/anysearch_adapter.py")
TEST_RECEIPT_SECRET = b"firecrawl-test-receipt-secret-32-bytes-minimum"
TEST_NOW = datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc)


def current_candidate():
    url = "https://example.com/docs/current"
    candidate = {
        "candidate_id": ANYSEARCH._candidate_id(url),
        "query": "example documentation",
        "platform": "web",
        "backend": "anysearch",
        "rank": 1,
        "title": "Current result",
        "url": url,
        "canonical_url": url,
        "snippet": "Discovery snippet",
        "author": None,
        "published_at": None,
        "content_type": "web_page",
        "language": None,
        "metrics": {
            "likes": None,
            "comments": None,
            "collects": None,
            "shares": None,
            "views": None,
        },
        "access": {"visibility": "public", "login_state_used": False},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": None,
            "retrieved_at": "2026-08-09T01:00:00Z",
            "route_reason": "public_web_default",
        },
        "limitations": ["search snippet only"],
    }
    ANYSEARCH.issue_candidate_receipt(
        candidate,
        secret=TEST_RECEIPT_SECRET,
        run_id="abcdef0123456789abcdef0123456789",
    )
    return candidate


class FirecrawlMapTests(unittest.TestCase):
    def test_map_uses_fixed_v2_endpoint_and_filters_origin_and_path(self):
        args = FIRECRAWL.parse_args(
            ["map", "--url", "https://example.com/docs/", "--limit", "10"]
        )
        seen = {}

        def transport(endpoint, payload, api_key, timeout):
            seen.update(
                endpoint=endpoint,
                payload=payload,
                api_key=api_key,
                timeout=timeout,
            )
            return {
                "success": True,
                "links": [
                    {
                        "url": "https://example.com/docs/start",
                        "title": "Start",
                        "description": "Guide",
                    },
                    "https://example.com/docs/nested/page?x=1#section",
                    "https://example.com/docs/nested/page?x=1",
                    "https://example.com/admin",
                    "https://other.example/docs/external",
                    "http://127.0.0.1/docs/private",
                    "https://example.com/docs/%2e%2e/secret",
                ],
            }

        with mock.patch.dict(
            os.environ, {FIRECRAWL.API_KEY_ENV: "fc-test-key"}, clear=False  # pragma: allowlist secret
        ):
            result = FIRECRAWL.execute(
                args, transport=transport, now=TEST_NOW
            )
        self.assertEqual(seen["endpoint"], FIRECRAWL.MAP_ENDPOINT)
        self.assertEqual(
            seen["payload"],
            {
                "url": "https://example.com/docs/",
                "limit": 10,
                "includeSubdomains": False,
                "ignoreQueryParameters": True,
            },
        )
        self.assertEqual(
            [candidate["canonical_url"] for candidate in result["candidates"]],
            [
                "https://example.com/docs/start",
                "https://example.com/docs/nested/page?x=1",
            ],
        )
        coverage = result["coverage"][0]
        self.assertEqual(coverage["excluded_non_public"], 1)
        self.assertEqual(coverage["excluded_cross_origin"], 1)
        self.assertEqual(coverage["excluded_outside_path"], 2)
        self.assertEqual(coverage["duplicate_links"], 1)
        self.assertIsNone(result["candidates"][1]["title"])

    def test_map_rejects_private_seed_before_key_or_transport(self):
        args = FIRECRAWL.parse_args(
            ["map", "--url", "http://127.0.0.1/docs", "--limit", "5"]
        )
        transport = mock.Mock()
        with self.assertRaises(FIRECRAWL.AdapterError):
            FIRECRAWL.execute(args, transport=transport)
        transport.assert_not_called()

    def test_map_rejects_browser_normalized_loopback_spellings_before_key(self):
        unsafe_urls = (
            "https://%31%32%37.0.0.1/docs",
            "https://１２７。０。０。１/docs",
            "https://0x7f.1/docs",
            "https://0177.0.0.1/docs",
            "https://2130706433/docs",
            "https://127.1/docs",
            "https://intranet/docs",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                args = FIRECRAWL.parse_args(
                    ["map", "--url", url, "--limit", "5"]
                )
                transport = mock.Mock()
                with mock.patch.object(FIRECRAWL, "load_api_key") as load_key:
                    with self.assertRaises(FIRECRAWL.AdapterError):
                        FIRECRAWL.execute(args, transport=transport)
                load_key.assert_not_called()
                transport.assert_not_called()

    def test_map_origin_uses_modern_uts46_and_rejects_contextual_joiners(self):
        self.assertEqual(
            FIRECRAWL._normalized_hostname("https://faß.de/docs"),
            "xn--fa-hia.de",
        )
        self.assertEqual(
            FIRECRAWL._normalized_hostname("https://ς.gr/docs"),
            "xn--3xa.gr",
        )
        self.assertEqual(
            FIRECRAWL._normalized_hostname("https://Bücher.de/docs"),
            "xn--bcher-kva.de",
        )
        with self.assertRaises(FIRECRAWL.AdapterError):
            FIRECRAWL.validate_public_http_url("https://ab\u200ccd.com/docs")

    def test_map_limit_is_hard_capped_at_one_hundred(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                FIRECRAWL.parse_args(
                    ["map", "--url", "https://example.com/", "--limit", "101"]
                )

    def test_execute_revalidates_map_limit_and_timeout_before_key_or_transport(self):
        invalid_namespaces = (
            SimpleNamespace(
                command="map", url="https://example.com/", limit=101, timeout=45
            ),
            SimpleNamespace(
                command="map", url="https://example.com/", limit=0, timeout=45
            ),
            SimpleNamespace(
                command="map", url="https://example.com/", limit=True, timeout=45
            ),
            SimpleNamespace(
                command="map", url="https://example.com/", limit=10, timeout=0
            ),
            SimpleNamespace(
                command="map", url="https://example.com/", limit=10, timeout=121
            ),
            SimpleNamespace(
                command="map", url="https://example.com/", limit=10, timeout=True
            ),
        )
        for args in invalid_namespaces:
            with self.subTest(limit=args.limit, timeout=args.timeout):
                transport = mock.Mock()
                with mock.patch.object(FIRECRAWL, "load_api_key") as load_key:
                    with self.assertRaises(FIRECRAWL.AdapterError):
                        FIRECRAWL.execute(args, transport=transport)
                load_key.assert_not_called()
                transport.assert_not_called()

    def test_map_malformed_response_fails_closed(self):
        bad_responses = (
            {"success": False, "links": []},
            {"success": True, "links": "not-a-list"},
            {"success": True, "links": [{"title": "missing URL"}]},
            {"success": True, "links": [42]},
        )
        for response in bad_responses:
            with self.subTest(response=response):
                with self.assertRaises(FIRECRAWL.AdapterError):
                    FIRECRAWL.normalize_map_response(
                        response,
                        seed_url="https://example.com/docs/",
                        limit=10,
                        retrieved_at="2026-08-09T01:30:00Z",
                    )


class FirecrawlScrapeTests(unittest.TestCase):
    def test_scrape_accepts_only_receipted_candidate_and_uses_safe_payload(self):
        candidate = current_candidate()
        args = FIRECRAWL.parse_args(
            [
                "scrape",
                "--candidate-from-search",
                json.dumps(candidate, ensure_ascii=False),
            ]
        )
        seen = {}

        def transport(endpoint, payload, api_key, timeout):
            seen.update(endpoint=endpoint, payload=payload, api_key=api_key)
            return {"success": True, "data": {"markdown": "# Page\n\nBody"}}

        with mock.patch.dict(
            os.environ,
            {FIRECRAWL.API_KEY_ENV: "fc-secret-test-key"},  # pragma: allowlist secret
            clear=False,
        ):
            result = FIRECRAWL.execute(
                args,
                transport=transport,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )
        self.assertEqual(seen["endpoint"], FIRECRAWL.SCRAPE_ENDPOINT)
        self.assertEqual(
            seen["payload"],
            {
                "url": candidate["url"],
                "formats": ["markdown"],
                "storeInCache": False,
                "proxy": "basic",
                "skipTlsVerification": False,
            },
        )
        self.assertNotIn("actions", seen["payload"])
        self.assertNotIn("headers", seen["payload"])
        self.assertNotIn("cookies", seen["payload"])
        self.assertNotIn("zeroDataRetention", seen["payload"])
        opened = result["candidates"][0]
        self.assertEqual(opened["backend"], "anysearch")
        self.assertTrue(opened["verification"]["opened_original"])
        self.assertEqual(opened["verification"]["status"], "candidate")
        self.assertEqual(
            opened["platform_fields"]["firecrawl"]["scrape_markdown"],
            "# Page\n\nBody",
        )
        self.assertEqual(
            opened["provenance"]["verification"]["backend"], "firecrawl"
        )
        self.assertNotIn("fc-secret-test-key", json.dumps(result))

    def test_scrape_rejects_structural_candidate_without_receipt_before_transport(self):
        candidate = current_candidate()
        candidate["provenance"].pop("anysearch_receipt")
        args = FIRECRAWL.parse_args(
            ["scrape", "--candidate-from-search", json.dumps(candidate)]
        )
        transport = mock.Mock()
        with self.assertRaisesRegex(FIRECRAWL.AdapterError, "receipt"):
            FIRECRAWL.execute(
                args,
                transport=transport,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )
        transport.assert_not_called()

    def test_scrape_revalidates_candidate_url_before_key_or_transport(self):
        unsafe_candidate = {"url": "https://%31%32%37.0.0.1/private"}
        fake_anysearch = SimpleNamespace(
            AdapterError=type("FakeAnySearchError", (RuntimeError,), {}),
            load_candidate_argument=mock.Mock(return_value=unsafe_candidate),
        )
        args = FIRECRAWL.parse_args(
            ["scrape", "--candidate-from-search", "opaque-current-candidate"]
        )
        transport = mock.Mock()
        with mock.patch.object(
            FIRECRAWL, "_load_anysearch_adapter", return_value=fake_anysearch
        ), mock.patch.object(FIRECRAWL, "load_api_key") as load_key:
            with self.assertRaises(FIRECRAWL.AdapterError):
                FIRECRAWL.execute(args, transport=transport)
        load_key.assert_not_called()
        transport.assert_not_called()

    def test_scrape_cli_has_no_bare_url_or_payload_escape_hatches(self):
        parser = FIRECRAWL.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["scrape", "--url", "https://example.com/"])
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "scrape",
                        "--candidate-from-search",
                        "{}",
                        "--headers",
                        "{}",
                    ]
                )

    def test_scrape_missing_markdown_fails_closed(self):
        candidate = current_candidate()
        for response in (
            {"success": False, "data": {}},
            {"success": True, "data": {}},
            {"success": True, "data": {"markdown": ""}},
            {"success": True, "data": {"markdown": 42}},
        ):
            with self.subTest(response=response):
                with self.assertRaises(FIRECRAWL.AdapterError):
                    FIRECRAWL.normalize_scrape_response(
                        response,
                        candidate=candidate,
                        checked_at="2026-08-09T01:30:00Z",
                    )


class FirecrawlRuntimeTests(unittest.TestCase):
    def test_api_key_loads_only_from_environment_or_private_file(self):
        self.assertEqual(
            FIRECRAWL.load_api_key(
                environ={FIRECRAWL.API_KEY_ENV: "fc-environment-key"}  # pragma: allowlist secret
            ),
            "fc-environment-key",
        )
        with tempfile.TemporaryDirectory() as directory:
            key_file = pathlib.Path(directory) / "firecrawl-api-key"
            key_file.write_text("fc-file-key\n", encoding="utf-8")  # pragma: allowlist secret
            key_file.chmod(0o600)
            self.assertEqual(
                FIRECRAWL.load_api_key(environ={}, key_file=key_file),
                "fc-file-key",
            )
            self.assertEqual(
                FIRECRAWL.load_api_key(
                    environ={FIRECRAWL.API_KEY_FILE_ENV: str(key_file)}
                ),
                "fc-file-key",
            )
            key_file.chmod(0o644)
            with self.assertRaises(FIRECRAWL.AdapterError):
                FIRECRAWL.load_api_key(environ={}, key_file=key_file)

    def test_api_key_file_override_must_be_absolute(self):
        with self.assertRaises(FIRECRAWL.AdapterError) as caught:
            FIRECRAWL.load_api_key(
                environ={FIRECRAWL.API_KEY_FILE_ENV: "relative/firecrawl-api-key"}  # pragma: allowlist secret
            )
        self.assertEqual(caught.exception.category, "configuration_error")

    def test_http_and_json_failures_are_redacted_and_fail_closed(self):
        secret = "fc-must-not-leak"  # pragma: allowlist secret
        denied = urllib_error.HTTPError(
            FIRECRAWL.MAP_ENDPOINT,
            401,
            f"Bearer {secret}",
            hdrs=None,
            fp=None,
        )
        with mock.patch.object(FIRECRAWL, "_open_without_redirect", side_effect=denied):
            with self.assertRaises(FIRECRAWL.AdapterError) as caught:
                FIRECRAWL.post_json(
                    FIRECRAWL.MAP_ENDPOINT,
                    {"url": "https://example.com/"},
                    secret,
                    10,
                )
        self.assertEqual(caught.exception.category, "authentication_error")
        self.assertNotIn(secret, caught.exception.message)

        class InvalidJsonResponse:
            status = 200

            def getcode(self):
                return self.status

            def read(self, size):
                return b"not-json"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        with mock.patch.object(
            FIRECRAWL,
            "_open_without_redirect",
            return_value=InvalidJsonResponse(),
        ):
            with self.assertRaises(FIRECRAWL.AdapterError) as caught:
                FIRECRAWL.post_json(
                    FIRECRAWL.SCRAPE_ENDPOINT,
                    {"url": "https://example.com/"},
                    secret,
                    10,
                )
        self.assertEqual(caught.exception.category, "invalid_response")
        self.assertNotIn(secret, caught.exception.message)

    def test_redirects_are_never_followed_with_bearer_authorization(self):
        original = FIRECRAWL.urllib_request.Request(
            FIRECRAWL.MAP_ENDPOINT,
            headers={"Authorization": "Bearer unit-test-sentinel"},
        )
        handler = FIRECRAWL._NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                original,
                None,
                302,
                "Found",
                {},
                "https://attacker.invalid/collect",
            )
        )

        redirected = urllib_error.HTTPError(
            FIRECRAWL.MAP_ENDPOINT, 302, "Found", hdrs=None, fp=None
        )
        opener = mock.Mock()
        opener.open.side_effect = redirected
        with mock.patch.object(
            FIRECRAWL.urllib_request, "build_opener", return_value=opener
        ) as build_opener:
            with self.assertRaises(FIRECRAWL.AdapterError) as caught:
                FIRECRAWL.post_json(
                    FIRECRAWL.MAP_ENDPOINT,
                    {"url": "https://example.com/"},
                    "unit-test-sentinel",
                    10,
                )
        self.assertEqual(caught.exception.category, "upstream_error")
        self.assertIsInstance(build_opener.call_args.args[0], FIRECRAWL._NoRedirectHandler)
        sent_request = opener.open.call_args.args[0]
        self.assertEqual(sent_request.full_url, FIRECRAWL.MAP_ENDPOINT)
        self.assertEqual(
            sent_request.get_header("Authorization"), "Bearer unit-test-sentinel"
        )
        self.assertEqual(opener.open.call_count, 1)

    def test_post_json_rejects_non_official_endpoint_before_opening(self):
        with mock.patch.object(FIRECRAWL, "_open_without_redirect") as opener:
            with self.assertRaises(FIRECRAWL.AdapterError):
                FIRECRAWL.post_json(
                    "https://attacker.invalid/collect",
                    {"url": "https://example.com/"},
                    "unit-test-sentinel",
                    10,
                )
        opener.assert_not_called()

    def test_official_v2_endpoints_are_not_configurable(self):
        self.assertEqual(
            FIRECRAWL.MAP_ENDPOINT, "https://api.firecrawl.dev/v2/map"
        )
        self.assertEqual(
            FIRECRAWL.SCRAPE_ENDPOINT, "https://api.firecrawl.dev/v2/scrape"
        )
        parser_actions = {
            option
            for action in FIRECRAWL.build_parser()._actions
            for option in action.option_strings
        }
        self.assertNotIn("--endpoint", parser_actions)
        self.assertNotIn("--api-key", parser_actions)


if __name__ == "__main__":
    unittest.main()
