import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import traceback
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "anysearch_adapter", ROOT / "scripts" / "anysearch_adapter.py"
)
ADAPTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)

TEST_RECEIPT_SECRET = b"unit-test-receipt-secret-32-bytes-minimum"
TEST_NOW = datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc)


SEARCH_MARKDOWN = """## Search Results (2 results, 31ms)

### 1. First result
- **URL**: https://example.com/first?x=1
- First discovery snippet.

### 2. Second result
- **URL**: <https://example.org/second>
- Second discovery snippet.
"""


def candidate_fixture():
    url = "https://example.com/original"
    candidate = {
        "candidate_id": ADAPTER._candidate_id(url),
        "query": "original query",
        "platform": "web",
        "backend": "anysearch",
        "rank": 2,
        "title": "Original title",
        "url": url,
        "canonical_url": url,
        "snippet": "Original snippet",
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
        "limitations": ["existing limitation"],
    }
    ADAPTER.issue_candidate_receipt(
        candidate,
        secret=TEST_RECEIPT_SECRET,
        run_id="0123456789abcdef0123456789abcdef",
    )
    return candidate


class SearchMarkdownTests(unittest.TestCase):
    def test_search_results_map_to_candidate_envelope(self):
        result = ADAPTER.normalize_search_markdown(
            SEARCH_MARKDOWN,
            query="test query",
            requested_limit=10,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "completed")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"][0]["backend_reported_count"], 2)
        self.assertEqual(result["coverage"][0]["elapsed_ms"], 31)
        first = result["candidates"][0]
        self.assertEqual(first["query"], "test query")
        self.assertEqual(first["backend"], "anysearch")
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["title"], "First result")
        self.assertEqual(first["url"], "https://example.com/first?x=1")
        self.assertEqual(first["snippet"], "First discovery snippet.")
        self.assertTrue(first["candidate_id"].startswith("web:"))
        self.assertEqual(first["verification"]["status"], "candidate")
        self.assertFalse(first["verification"]["opened_original"])
        self.assertEqual(
            first["provenance"]["route_reason"], "public_web_default"
        )
        receipt = first["provenance"]["anysearch_receipt"]
        self.assertEqual(receipt["version"], 1)
        self.assertRegex(receipt["run_id"], r"^[0-9a-f]{32}$")
        self.assertRegex(receipt["signature"], r"^[A-Za-z0-9_-]{43}$")

    def test_only_explicit_zero_header_is_successful_empty_search(self):
        result = ADAPTER.normalize_search_markdown(
            "## Search Results (0 results, 8ms)\n",
            query="nothing",
            requested_limit=3,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "completed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"][0]["backend_reported_count"], 0)

    def test_zero_header_with_unexpected_text_is_failed_parse(self):
        result = ADAPTER.normalize_search_markdown(
            "## Search Results (0 results, 8ms)\n\nUPSTREAM FORMAT ERROR\n",
            query="nothing",
            requested_limit=3,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_nonempty_unrecognized_output_is_failed_parse_not_zero_results(self):
        result = ADAPTER.normalize_search_markdown(
            "The service changed its response format.",
            query="query",
            requested_limit=10,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_reported_result_without_url_is_failed_parse_not_zero_results(self):
        result = ADAPTER.normalize_search_markdown(
            "## Search Results (1 results, 9ms)\n\n### 1. Missing URL\n- text",
            query="query",
            requested_limit=10,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(
            all(error["category"] == "parse_error" for error in result["errors"])
        )

    def test_count_mismatch_with_one_valid_result_is_partial(self):
        result = ADAPTER.normalize_search_markdown(
            "## Search Results (2 results, 9ms)\n\n"
            "### 1. Valid\n- **URL**: https://example.com/valid\n- snippet\n",
            query="query",
            requested_limit=10,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "partial")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_numbered_heading_inside_snippet_is_not_a_result_boundary(self):
        markdown = """## Search Results (2 results, 15ms)

### 1. Documentation
- **URL**: https://example.com/docs
- Intro

### 2. Installation
This is a heading inside the page snippet, not a search card.

### 2. Actual second card
- **URL**: https://example.com/second
- second
"""
        section = ADAPTER.parse_search_section(markdown)
        self.assertEqual(section.status, "completed")
        self.assertEqual(len(section.rows), 2)
        self.assertIn("### 2. Installation", section.rows[0].snippet)

    def test_search_parser_rejects_nonpublic_http_hosts(self):
        urls = (
            "http://localhost/private",
            "https://service.local/private",
            "http://127.0.0.1/private",
            "http://10.0.0.1/private",
            "http://169.254.1.2/private",
            "http://192.168.1.2/private",
            "http://[::1]/private",
            "http://[fe80::1]/private",
            "http://[fc00::1]/private",
        )
        for url in urls:
            with self.subTest(url=url):
                section = ADAPTER.parse_search_section(
                    "## Search Results (1 result, 1ms)\n\n"
                    f"### 1. Internal\n- **URL**: {url}\n- private\n"
                )
                self.assertEqual(section.status, "failed")
                self.assertEqual(section.rows, ())
                self.assertTrue(section.errors)

    def test_vertical_search_records_distinct_route_reason(self):
        args = ADAPTER.parse_args(
            [
                "search",
                "AAPL",
                "--domain",
                "finance",
                "--sub-domain",
                "finance.us_stock",
                "--sub-domain-params",
                '{"ticker":"AAPL"}',
                "--limit",
                "1",
            ]
        )
        seen = {}

        def runner(runtime_conf, argv, timeout):
            seen["argv"] = argv
            return (
                "## Search Results (1 results, 1ms)\n\n"
                "### 1. Apple\n- **URL**: https://example.com/apple\n- result\n"
            )

        result = ADAPTER.execute(
            args, runner=runner, receipt_secret=TEST_RECEIPT_SECRET
        )
        self.assertIn("--sub_domain_params", seen["argv"])
        self.assertEqual(
            result["candidates"][0]["provenance"]["route_reason"],
            "anysearch_vertical_domain",
        )


class BatchMarkdownTests(unittest.TestCase):
    def test_batch_sections_retain_each_submitted_query_and_rank(self):
        markdown = """## Query 1: response label one

## Search Results (1 results, 4ms)

### 1. Alpha
- **URL**: https://example.com/alpha
- alpha snippet

---

## Query 2: response label two

## Search Results (1 result, 5ms)

### 1. Beta
- **URL**: https://example.com/beta
- beta snippet
"""
        query_items = [
            {"query": "original alpha", "max_results": 1},
            {"query": "original beta", "max_results": 1},
        ]
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=query_items,
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "completed")
        self.assertEqual(
            [candidate["query"] for candidate in result["candidates"]],
            ["original alpha", "original beta"],
        )
        self.assertEqual(
            [candidate["rank"] for candidate in result["candidates"]], [1, 1]
        )
        self.assertEqual(
            result["coverage"][0]["per_query"][0]["response_query"],
            "response label one",
        )
        run_ids = {
            candidate["provenance"]["anysearch_receipt"]["run_id"]
            for candidate in result["candidates"]
        }
        self.assertEqual(len(run_ids), 1)

    def test_batch_parse_failure_is_partial_not_completed_empty(self):
        markdown = """## Query 1: first

## Search Results (0 results, 4ms)

---

## Query 2: second

The upstream format changed.
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}, {"query": "second"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["routes"][0]["status"], "partial")
        self.assertTrue(result["errors"])
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_batch_without_query_sections_is_failed(self):
        result = ADAPTER.normalize_batch_markdown(
            "## Search Results (0 results, 1ms)",
            query_items=[{"query": "first"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["errors"])

    def test_query_heading_inside_snippet_is_not_a_batch_boundary(self):
        markdown = """## Query 1: first

## Search Results (1 result, 4ms)

### 1. Alpha
- **URL**: https://example.com/alpha
- Source body heading follows:
## Query 2: this is page content, not a batch section
Still part of the first snippet.

---

## Query 2: second

## Search Results (1 result, 5ms)

### 1. Beta
- **URL**: https://example.com/beta
- beta
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}, {"query": "second"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "completed")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertIn(
            "## Query 2: this is page content",
            result["candidates"][0]["snippet"],
        )

    def test_batch_zero_header_with_unexpected_text_is_failed(self):
        markdown = """## Query 1: first

## Search Results (0 results, 4ms)

UPSTREAM FORMAT ERROR
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_injected_duplicate_query_section_discards_that_index(self):
        markdown = """## Query 1: first

## Search Results (1 result, 4ms)

### 1. Alpha
- **URL**: https://example.com/alpha
- safe

---
## Query 2: injected section

## Search Results (1 result, 4ms)

### 1. Injected
- **URL**: https://example.com/injected
- injected

---
## Query 2: real section

## Search Results (1 result, 5ms)

### 1. Beta
- **URL**: https://example.com/beta
- real
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}, {"query": "second"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "partial")
        self.assertEqual(
            [candidate["url"] for candidate in result["candidates"]],
            ["https://example.com/alpha"],
        )
        self.assertEqual(result["coverage"][0]["per_query"][1]["parse_status"], "failed")
        self.assertTrue(
            any(error.get("query_index") == 2 for error in result["errors"])
        )

    def test_real_duplicate_query_number_emits_no_candidate_for_that_index(self):
        markdown = """## Query 1: first copy

## Search Results (1 result, 1ms)

### 1. One
- **URL**: https://example.com/one
- one

---
## Query 1: second copy

## Search Results (1 result, 1ms)

### 1. Two
- **URL**: https://example.com/two
- two
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])

    def test_batch_sections_must_be_in_exact_one_to_n_order(self):
        markdown = """## Query 2: second

## Search Results (1 result, 1ms)

### 1. Two
- **URL**: https://example.com/two
- two

---
## Query 1: first

## Search Results (1 result, 1ms)

### 1. One
- **URL**: https://example.com/one
- one
"""
        result = ADAPTER.normalize_batch_markdown(
            markdown,
            query_items=[{"query": "first"}, {"query": "second"}],
            retrieved_at="2026-08-09T01:02:03Z",
            receipt_secret=TEST_RECEIPT_SECRET,
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])

    def test_batch_execution_preserves_vertical_query_objects(self):
        raw_queries = [
            {
                "query": "AAPL",
                "domain": "finance",
                "sub_domain": "finance.us_stock",
                "sub_domain_params": {"ticker": "AAPL"},
                "max_results": 1,
            }
        ]
        args = ADAPTER.parse_args(
            ["batch", "--queries", json.dumps(raw_queries, ensure_ascii=False)]
        )
        seen = {}

        def runner(runtime_conf, argv, timeout):
            seen["argv"] = argv
            return """## Query 1: AAPL

## Search Results (1 result, 3ms)

### 1. Apple
- **URL**: https://example.com/apple
- result
"""

        result = ADAPTER.execute(
            args, runner=runner, receipt_secret=TEST_RECEIPT_SECRET
        )
        self.assertEqual(seen["argv"][:2], ["batch_search", "--queries"])
        self.assertEqual(json.loads(seen["argv"][2]), raw_queries)
        self.assertEqual(
            result["candidates"][0]["provenance"]["route_reason"],
            "anysearch_vertical_domain_batch",
        )

    def test_batch_rejects_fields_that_could_bypass_cli_contract(self):
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.parse_batch_queries(
                '[{"query":"safe","api_key":"must-not-be-forwarded"}]'  # pragma: allowlist secret
            )


class VerificationTests(unittest.TestCase):
    def test_verify_preserves_candidate_and_attaches_extract_markdown(self):
        original = candidate_fixture()
        result = ADAPTER.verification_envelope(
            original,
            extract_markdown="# Original page\n\nBody text",
            checked_at="2026-08-09T02:03:04Z",
            receipt_secret=TEST_RECEIPT_SECRET,
            now=TEST_NOW,
        )
        verified = result["candidates"][0]
        for field in (
            "candidate_id",
            "query",
            "backend",
            "rank",
            "title",
            "url",
            "snippet",
        ):
            self.assertEqual(verified[field], original[field])
        self.assertTrue(verified["verification"]["opened_original"])
        self.assertEqual(verified["verification"]["status"], "candidate")
        self.assertEqual(
            verified["platform_fields"]["anysearch"]["extract_markdown"],
            "# Original page\n\nBody text",
        )
        verification_provenance = verified["provenance"]["verification"]
        self.assertEqual(verification_provenance["source_query"], "original query")
        self.assertEqual(
            verification_provenance["candidate_id"], original["candidate_id"]
        )
        self.assertEqual(
            verification_provenance["route_reason"],
            "verify_candidate_from_current_search",
        )
        self.assertEqual(result["routes"][0]["mode"], "verify")
        self.assertEqual(original["verification"]["opened_original"], False)

    def test_verify_requires_anysearch_candidate_status(self):
        wrong_backend = candidate_fixture()
        wrong_backend["backend"] = "aihot"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                wrong_backend, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

        already_verified = candidate_fixture()
        already_verified["verification"]["status"] = "verified"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                already_verified, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

    def test_structurally_complete_known_url_without_receipt_is_rejected(self):
        forged = candidate_fixture()
        url = "https://example.net/known-url"
        forged["candidate_id"] = ADAPTER._candidate_id(url)
        forged["query"] = "known URL"
        forged["url"] = url
        forged["canonical_url"] = url
        forged["provenance"].pop("anysearch_receipt")
        with self.assertRaisesRegex(ADAPTER.AdapterError, "receipt"):
            ADAPTER.validate_candidate_from_search(
                forged, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

    def test_receipt_binds_query_url_id_and_retrieval_timestamp(self):
        mutations = (
            ("query", "different query"),
            ("url", "https://example.com/different"),
            ("candidate_id", "web:" + "0" * 20),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                tampered = candidate_fixture()
                tampered[field] = value
                if field == "url":
                    tampered["canonical_url"] = value
                    tampered["candidate_id"] = ADAPTER._candidate_id(value)
                with self.assertRaises(ADAPTER.AdapterError):
                    ADAPTER.validate_candidate_from_search(
                        tampered,
                        receipt_secret=TEST_RECEIPT_SECRET,
                        now=TEST_NOW,
                    )

        tampered_time = candidate_fixture()
        tampered_time["provenance"]["retrieved_at"] = "2026-08-09T01:01:00Z"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                tampered_time,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )

    def test_receipt_rejects_wrong_signature_key_and_expiration(self):
        bad_signature = candidate_fixture()
        bad_signature["provenance"]["anysearch_receipt"]["signature"] = "A" * 43
        with self.assertRaisesRegex(ADAPTER.AdapterError, "signature"):
            ADAPTER.validate_candidate_from_search(
                bad_signature,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )

        with self.assertRaisesRegex(ADAPTER.AdapterError, "signature"):
            ADAPTER.validate_candidate_from_search(
                candidate_fixture(),
                receipt_secret=b"different-unit-test-receipt-key-32-bytes",
                now=TEST_NOW,
            )

        expired_at = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ADAPTER.AdapterError, "expired"):
            ADAPTER.validate_candidate_from_search(
                candidate_fixture(),
                receipt_secret=TEST_RECEIPT_SECRET,
                now=expired_at,
            )

    def test_verify_rejects_private_or_local_url(self):
        local = candidate_fixture()
        local["url"] = "http://127.0.0.1/private"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                local, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

    def test_public_url_validation_rejects_normalized_and_legacy_loopback_hosts(self):
        unsafe_urls = (
            "https://%31%32%37.0.0.1/private",
            "https://１２７。０。０。１/private",
            "https://0x7f.1/private",
            "https://0177.0.0.1/private",
            "https://2130706433/private",
            "https://127.1/private",
            "https://intranet/private",
            "https://example.com:invalid/private",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    ADAPTER.validate_public_http_url(url)

        self.assertEqual(
            ADAPTER.validate_public_http_url("https://8.8.8.8/public"),
            "https://8.8.8.8/public",
        )

    def test_public_host_uses_modern_uts46_without_legacy_target_changes(self):
        self.assertEqual(ADAPTER._normalize_host_uts46("faß.de"), "xn--fa-hia.de")
        self.assertEqual(ADAPTER._normalize_host_uts46("ς.gr"), "xn--3xa.gr")
        self.assertEqual(
            ADAPTER._normalize_host_uts46("Bücher.de"), "xn--bcher-kva.de"
        )
        with self.assertRaises(ValueError):
            ADAPTER._normalize_host_uts46("ab\u200ccd.com")
        with mock.patch.object(ADAPTER, "_idna_uts46", None):
            self.assertEqual(ADAPTER._normalize_host_uts46("example.com"), "example.com")
            with self.assertRaises(ValueError):
                ADAPTER._normalize_host_uts46("Bücher.de")

    def test_verify_rejects_forged_or_inconsistent_candidate(self):
        mismatched_id = candidate_fixture()
        mismatched_id["candidate_id"] = "web:forged"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                mismatched_id, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

        missing_provenance = candidate_fixture()
        missing_provenance.pop("provenance")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                missing_provenance, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

        nonpublic = candidate_fixture()
        nonpublic["access"]["visibility"] = "authenticated_public"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                nonpublic, receipt_secret=TEST_RECEIPT_SECRET, now=TEST_NOW
            )

        mismatched_canonical = candidate_fixture()
        mismatched_canonical["canonical_url"] = "https://example.net/other"
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                mismatched_canonical,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )

        minimal_forgery = {
            "backend": "anysearch",
            "candidate_id": "web:forged",
            "query": "known URL",
            "url": "https://example.com/known",
            "verification": {"status": "candidate"},
        }
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_candidate_from_search(
                minimal_forgery,
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )

    def test_candidate_from_search_can_be_loaded_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "candidate.json"
            path.write_text(json.dumps(candidate_fixture()), encoding="utf-8")
            loaded = ADAPTER.load_candidate_argument(
                f"@{path}",
                receipt_secret=TEST_RECEIPT_SECRET,
                now=TEST_NOW,
            )
        self.assertEqual(loaded["candidate_id"], candidate_fixture()["candidate_id"])

    def test_verify_cli_has_no_url_or_candidate_json_bypass(self):
        parser = ADAPTER.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["verify", "--url", "https://example.com"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["verify", "--candidate-json", "{}"])


class RuntimeSafetyTests(unittest.TestCase):
    def test_runtime_conf_override_must_be_absolute(self):
        args = ADAPTER.build_parser().parse_args(
            ["search", "public query", "--runtime-conf", "relative/runtime.conf"]
        )
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.execute(args, runner=lambda *_: "")
        self.assertEqual(caught.exception.category, "configuration_error")

    def test_search_receipt_verifies_across_cli_processes_with_private_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            fake_cli = root / "fake_anysearch.py"
            search_output = (
                "## Search Results (1 result, 1ms)\n\n"
                "### 1. Cross-process result\n"
                "- **URL**: https://example.com/cross-process\n"
                "- result\n"
            )
            fake_cli.write_text(
                "import sys\n\n"
                "if sys.argv[1] == 'search':\n"
                f"    print({search_output!r})\n"
                "elif sys.argv[1] == 'extract':\n"
                "    print('# Original page\\n\\nBody')\n"
                "else:\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            runtime_conf = root / "runtime.conf"
            runtime_conf.write_text(
                f'Command: {sys.executable} "{fake_cli}"\n', encoding="utf-8"
            )
            key_file = root / "receipt.key"
            environment = dict(os.environ)
            environment.pop(ADAPTER.RECEIPT_KEY_ENV, None)
            environment[ADAPTER.RECEIPT_KEY_FILE_ENV] = str(key_file)
            adapter_path = ROOT / "scripts" / "anysearch_adapter.py"

            searched = subprocess.run(
                [
                    sys.executable,
                    str(adapter_path),
                    "search",
                    "cross process",
                    "--runtime-conf",
                    str(runtime_conf),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(searched.returncode, 0, searched.stderr)
            candidate = json.loads(searched.stdout)["candidates"][0]
            self.assertTrue(key_file.exists())
            self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)

            verified = subprocess.run(
                [
                    sys.executable,
                    str(adapter_path),
                    "verify",
                    "--candidate-from-search",
                    json.dumps(candidate, ensure_ascii=False),
                    "--runtime-conf",
                    str(runtime_conf),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            opened = json.loads(verified.stdout)["candidates"][0]
            self.assertTrue(opened["verification"]["opened_original"])

    def test_runtime_command_is_split_with_shlex(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                'Runtime: Python\nCommand: env MODE=test python3 "/tmp/path with space/cli.py"\n',
                encoding="utf-8",
            )
            command = ADAPTER.read_runtime_command(conf)
        self.assertEqual(
            command,
            ["env", "MODE=test", "python3", "/tmp/path with space/cli.py"],
        )

    def test_runtime_executes_argv_without_shell_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                "Command: env MODE=test python3 /tmp/cli.py\n", encoding="utf-8"
            )
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr="warning"
            )
            with mock.patch.object(
                ADAPTER.subprocess, "run", return_value=completed
            ) as run:
                output = ADAPTER.run_anysearch(
                    conf, ["search", "literal;not-a-command"], 10
                )
        self.assertEqual(output, "ok")
        argv = run.call_args.args[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:2], ["python3", "/tmp/cli.py"])
        self.assertEqual(argv[-2:], ["search", "literal;not-a-command"])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["env"]["MODE"], "test")

    def test_failed_runtime_output_is_classified_without_leaking_key(self):
        secret = "supersecret-api-key"  # pragma: allowlist secret
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                f"Command: env ANYSEARCH_API_KEY={secret} python3 /tmp/cli.py\n",
                encoding="utf-8",
            )
            failed = SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=f"HTTP 401 Authorization Bearer {secret}",
            )
            with mock.patch.object(ADAPTER.subprocess, "run", return_value=failed):
                with self.assertRaises(ADAPTER.AdapterError) as caught:
                    ADAPTER.run_anysearch(conf, ["search", "query"], 10)
        self.assertEqual(caught.exception.category, "authentication_error")
        self.assertNotIn(secret, caught.exception.message)
        envelope = ADAPTER.error_envelope(
            queries=["query"],
            mode="search",
            category=caught.exception.category,
            message=caught.exception.message,
            requested_limit=10,
        )
        self.assertNotIn(secret, json.dumps(envelope))

    def test_runtime_secret_is_environment_only_not_process_argv(self):
        secret = "environment-only-secret"  # pragma: allowlist secret
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                f"Command: env ANYSEARCH_API_KEY={secret} python3 /tmp/cli.py\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            with mock.patch.object(
                ADAPTER.subprocess, "run", return_value=completed
            ) as run:
                ADAPTER.run_anysearch(conf, ["search", "query"], 10)
        process_argv = run.call_args.args[0]
        self.assertNotIn(secret, " ".join(process_argv))
        self.assertEqual(
            run.call_args.kwargs["env"]["ANYSEARCH_API_KEY"], secret
        )

    def test_receipt_key_environment_is_not_forwarded_to_anysearch(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text("Command: python3 /tmp/cli.py\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            with mock.patch.dict(
                os.environ,
                {ADAPTER.RECEIPT_KEY_ENV: "x" * 40},  # pragma: allowlist secret
                clear=False,
            ), mock.patch.object(
                ADAPTER.subprocess, "run", return_value=completed
            ) as run:
                ADAPTER.run_anysearch(conf, ["search", "query"], 10)
        child_environment = run.call_args.kwargs["env"]
        self.assertNotIn(ADAPTER.RECEIPT_KEY_ENV, child_environment)
        self.assertNotIn(ADAPTER.RECEIPT_KEY_FILE_ENV, child_environment)

    def test_unrelated_secrets_are_not_forwarded_to_anysearch(self):
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                "Command: env ANYSEARCH_API_KEY=runtime-key python3 /tmp/cli.py\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": "/usr/bin:/bin",
                    "OPENAI_API_KEY": "openai-secret",  # pragma: allowlist secret
                    "GITHUB_TOKEN": "github-secret",  # pragma: allowlist secret
                    "FIRECRAWL_API_KEY": "firecrawl-secret",  # pragma: allowlist secret
                    "YOUTUBE_API_KEY": "youtube-secret",  # pragma: allowlist secret
                },
                clear=True,
            ), mock.patch.object(
                ADAPTER.subprocess, "run", return_value=completed
            ) as run:
                ADAPTER.run_anysearch(conf, ["search", "query"], 10)
        child_environment = run.call_args.kwargs["env"]
        self.assertEqual(child_environment["ANYSEARCH_API_KEY"], "runtime-key")
        self.assertEqual(child_environment["PATH"], "/usr/bin:/bin")
        for name in (
            "OPENAI_API_KEY", "GITHUB_TOKEN", "FIRECRAWL_API_KEY", "YOUTUBE_API_KEY"
        ):
            self.assertNotIn(name, child_environment)

    def test_timeout_does_not_chain_raw_command_or_captured_output(self):
        secret = "must-not-appear-in-traceback"  # pragma: allowlist secret
        with tempfile.TemporaryDirectory() as directory:
            conf = pathlib.Path(directory) / "runtime.conf"
            conf.write_text(
                f"Command: env ANYSEARCH_API_KEY={secret} python3 /tmp/cli.py\n",
                encoding="utf-8",
            )
            timeout = subprocess.TimeoutExpired(
                cmd=["env", f"ANYSEARCH_API_KEY={secret}"],
                timeout=10,
                output=secret,
                stderr=secret,
            )
            with mock.patch.object(
                ADAPTER.subprocess, "run", side_effect=timeout
            ) as run:
                with self.assertRaises(ADAPTER.AdapterError) as caught:
                    ADAPTER.run_anysearch(conf, ["search", "query"], 10)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(caught.exception), caught.exception, caught.exception.__traceback__
            )
        )
        self.assertNotIn(secret, rendered)
        self.assertNotIn(secret, " ".join(run.call_args.args[0]))

    def test_runtime_rejects_api_key_cli_flag(self):
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.prepare_runtime_invocation(
                ["python3", "/tmp/cli.py", "--api_key", "secret"]
            )

    def test_source_never_requests_shell_execution(self):
        source = (ROOT / "scripts" / "anysearch_adapter.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("shell" + "=True", source)


if __name__ == "__main__":
    unittest.main()
