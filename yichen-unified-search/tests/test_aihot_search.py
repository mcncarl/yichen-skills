import importlib.util
import pathlib
import sys
import unittest
from datetime import datetime, timezone
from urllib.request import Request


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "aihot_search", ROOT / "scripts" / "aihot_search.py"
)
ADAPTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.payload[:limit]


class FakeOpener:
    def __init__(self, payload: bytes) -> None:
        self.response = FakeResponse(payload)
        self.requests = []

    def open(self, request, timeout: int):
        self.requests.append((request, timeout))
        return self.response


class AihotAdapterTests(unittest.TestCase):
    def test_fetch_json_rejects_redirects_before_following_them(self):
        handler = ADAPTER.RejectRedirects()
        redirected = handler.redirect_request(
            Request(f"{ADAPTER.BASE_URL}/api/public/items"),
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/private",
        )
        self.assertIsNone(redirected)

    def test_fetch_json_reads_one_bounded_response(self):
        opener = FakeOpener(b'{"items": []}')
        payload = ADAPTER.fetch_json(
            f"{ADAPTER.BASE_URL}/api/public/items",
            7,
            opener=opener,
        )
        self.assertEqual(payload, {"items": []})
        self.assertEqual(
            opener.response.read_limit,
            ADAPTER.MAX_RESPONSE_BYTES + 1,
        )
        self.assertEqual(opener.requests[0][1], 7)

    def test_fetch_json_rejects_oversized_response(self):
        opener = FakeOpener(b"x" * (ADAPTER.MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "maximum allowed size"):
            ADAPTER.fetch_json(
                f"{ADAPTER.BASE_URL}/api/public/items",
                7,
                opener=opener,
            )

    def test_items_are_mapped_to_unified_candidates(self):
        payload = {
            "count": 1,
            "hasNext": False,
            "items": [
                {
                    "id": "cm9abc456def789ghi012jkl3",
                    "title": "模型更新",
                    "title_en": "Model update",
                    "url": "https://example.com/model",
                    "source": "Example Lab",
                    "publishedAt": "2026-07-31T00:00:00.000Z",
                    "summary": "AI 生成摘要",
                    "category": "ai-models",
                }
            ],
        }
        result = ADAPTER.normalize_items(
            payload,
            query="今天 AI 圈有什么",
            limit=10,
            days=1,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        item = result["candidates"][0]
        self.assertEqual(item["candidate_id"], "aihot:cm9abc456def789ghi012jkl3")
        self.assertEqual(item["platform"], "web")
        self.assertEqual(item["backend"], "aihot")
        self.assertEqual(
            item["platform_fields"]["aihot"]["source_name"], "Example Lab"
        )
        self.assertEqual(item["verification"]["status"], "candidate")
        self.assertIn("AI-generated", item["limitations"][0])

    def test_paper_category_maps_content_type(self):
        payload = {
            "items": [
                {
                    "id": "paper-id",
                    "title": "New paper",
                    "url": "https://example.com/paper",
                    "source": "arXiv",
                    "category": "paper",
                }
            ]
        }
        result = ADAPTER.normalize_items(
            payload,
            query="最新 AI 论文",
            limit=5,
            days=7,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(result["candidates"][0]["content_type"], "ai_paper")

    def test_items_reject_non_public_or_unsafe_urls(self):
        unsafe_urls = [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "http://127.0.0.1/private",
            "http://10.0.0.1/private",
            "http://localhost/private",
            "https://intranet/private",
            "https://user:password@example.com/private",  # pragma: allowlist secret
        ]
        payload = {
            "items": [
                {"title": f"unsafe {index}", "url": url}
                for index, url in enumerate(unsafe_urls)
            ]
        }
        result = ADAPTER.normalize_items(
            payload,
            query="AI news",
            limit=20,
            days=1,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["coverage"][0]["rejected_count"], len(unsafe_urls))
        self.assertEqual(result["errors"][0]["category"], "invalid_candidate")

    def test_all_invalid_nonempty_items_fail_instead_of_claiming_zero_results(self):
        payload = {
            "items": [
                {"url": "https://example.com/missing-title"},
                {"title": "missing URL"},
            ]
        }
        result = ADAPTER.normalize_items(
            payload,
            query="AI news",
            limit=20,
            days=1,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["coverage"][0]["raw_result_count"], 2)
        self.assertEqual(result["coverage"][0]["rejected_count"], 2)
        self.assertEqual(result["candidates"], [])

    def test_mixed_valid_and_invalid_items_are_partial(self):
        payload = {
            "items": [
                {"title": "valid", "url": "https://example.com/valid"},
                {"title": 123, "url": "https://example.com/invalid-title"},
                {
                    "title": "invalid timestamp",
                    "url": "https://example.com/invalid-time",
                    "publishedAt": "2026-07-31T01:00:00",
                },
            ]
        }
        result = ADAPTER.normalize_items(
            payload,
            query="AI news",
            limit=20,
            days=1,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(result["routes"][0]["status"], "partial")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["coverage"][0]["rejected_count"], 2)
        self.assertEqual(result["errors"][0]["category"], "invalid_candidate")

    def test_valid_timestamp_is_normalized_and_language_is_not_guessed(self):
        payload = {
            "items": [
                {
                    "title": "Model release",
                    "url": "https://example.com/model",
                    "publishedAt": "2026-07-31T09:00:00+08:00",
                }
            ]
        }
        result = ADAPTER.normalize_items(
            payload,
            query="AI news",
            limit=20,
            days=1,
            feed="selected",
            retrieved_at="2026-07-31T01:00:00Z",
        )
        item = result["candidates"][0]
        self.assertEqual(item["published_at"], "2026-07-31T01:00:00Z")
        self.assertIsNone(item["language"])

    def test_daily_sections_and_flashes_are_flattened_and_deduplicated(self):
        payload = {
            "date": "2026-07-30",
            "windowStart": "2026-07-29T00:00:00.000Z",
            "windowEnd": "2026-07-30T00:00:00.000Z",
            "sections": [
                {
                    "label": "论文研究",
                    "items": [
                        {
                            "title": "Paper",
                            "summary": "Summary",
                            "sourceUrl": "https://example.com/paper",
                            "sourceName": "arXiv",
                        }
                    ],
                }
            ],
            "flashes": [
                {
                    "title": "Paper duplicate",
                    "sourceUrl": "https://example.com/paper",
                    "sourceName": "arXiv",
                },
                {
                    "title": "Flash",
                    "sourceUrl": "https://example.com/flash",
                    "sourceName": "News",
                    "publishedAt": "2026-07-30T00:30:00.000Z",
                },
            ],
        }
        result = ADAPTER.normalize_daily(
            payload,
            query="AI 日报",
            limit=10,
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["candidates"][0]["content_type"], "ai_paper")
        self.assertEqual(
            result["request"]["time_range"]["date"], "2026-07-30"
        )
        self.assertEqual(result["coverage"][0]["duplicate_count"], 1)

    def test_nonempty_malformed_daily_rows_fail_closed(self):
        payload = {
            "date": "2026-07-30",
            "sections": [
                "not-an-object",
                {"label": "论文研究", "items": [{"title": "missing URL"}]},
            ],
            "flashes": [{"title": "private", "sourceUrl": "http://127.0.0.1"}],
        }
        result = ADAPTER.normalize_daily(
            payload,
            query="AI 日报",
            limit=10,
            retrieved_at="2026-07-31T01:00:00Z",
        )
        self.assertEqual(result["routes"][0]["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["coverage"][0]["rejected_count"], 3)
        self.assertEqual(result["errors"][0]["category"], "invalid_candidate")

    def test_daily_rejects_invalid_top_level_shapes_and_time_metadata(self):
        with self.assertRaises(ValueError):
            ADAPTER.normalize_daily(
                {"sections": {}, "flashes": []},
                query="AI 日报",
                limit=10,
                retrieved_at="2026-07-31T01:00:00Z",
            )
        with self.assertRaises(ValueError):
            ADAPTER.normalize_daily(
                {
                    "date": "30-07-2026",
                    "sections": [],
                    "flashes": [],
                },
                query="AI 日报",
                limit=10,
                retrieved_at="2026-07-31T01:00:00Z",
            )

    def test_items_url_contains_browser_api_parameters(self):
        url = ADAPTER.build_url(
            feed="selected",
            days=3,
            limit=20,
            keyword="OpenAI",
            category="ai-models",
            date=None,
            now=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        self.assertIn("/api/public/items?", url)
        self.assertIn("mode=selected", url)
        self.assertIn("q=OpenAI", url)
        self.assertIn("category=ai-models", url)

    def test_daily_url_can_target_a_date(self):
        url = ADAPTER.build_url(
            feed="daily",
            days=1,
            limit=20,
            keyword=None,
            category=None,
            date="2026-07-30",
            now=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        self.assertEqual(url, "https://aihot.virxact.com/api/public/daily/2026-07-30")


if __name__ == "__main__":
    unittest.main()
