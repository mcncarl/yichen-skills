import importlib.util
import io
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "x_research_merge", ROOT / "scripts" / "x_research_merge.py"
)
MERGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MERGE
SPEC.loader.exec_module(MERGE)


def candidate(
    status_id,
    *,
    query="alpha",
    rank=1,
    author="Example",
    language="en",
    published_at="2026-08-09T00:00:00Z",
    metrics=None,
    platform_fields=None,
    content_type="x_post",
    provenance=None,
    canonical_url=None,
):
    status_id_text = None if status_id is None else str(status_id)
    if canonical_url is None and status_id_text is not None:
        canonical_url = f"https://x.com/example/status/{status_id_text}"
    return {
        "candidate_id": f"x:{status_id_text}" if status_id_text is not None else "x:url-only",
        "query": query,
        "platform": "x",
        "backend": "fixture",
        "rank": rank,
        "title": f"Post {status_id_text}",
        "url": canonical_url,
        "canonical_url": canonical_url,
        "snippet": "Fixture post",
        "author": author,
        "published_at": published_at,
        "content_type": content_type,
        "language": language,
        "metrics": metrics
        or {
            "likes": 1,
            "comments": 1,
            "collects": None,
            "shares": 1,
            "views": 10,
        },
        "access": {"visibility": "public", "login_state_used": False},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": provenance
        if provenance is not None
        else {"source_id": status_id_text, "retrieved_at": "2026-08-09T01:00:00Z"},
        "platform_fields": platform_fields or {},
        "limitations": [],
    }


def envelope(*candidates, queries=None):
    return {
        "schema_version": "1.0",
        "request": {
            "queries": queries or [item["query"] for item in candidates],
            "platforms": ["x"],
            "time_range": {"hours": 24},
            "requested_limit": 20,
        },
        "routes": [{"platform": "x", "backend": "fixture", "status": "completed"}],
        "candidates": list(candidates),
        "coverage": [{"backend": "fixture", "returned": len(candidates)}],
        "errors": [],
    }


class XResearchMergeTests(unittest.TestCase):
    def test_deduplicates_by_tweet_id_then_canonical_url_and_preserves_sources(self):
        first = candidate(
            "101",
            query="alpha",
            rank=3,
            metrics={"likes": 2, "comments": 1, "shares": 0, "views": 20},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        second = candidate(
            "101",
            query="beta",
            rank=1,
            metrics={"likes": 8, "comments": 1, "shares": 2, "views": 50},
            provenance={"source_id": None, "route_reason": "second backend"},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        second["candidate_id"] = "x:101"

        url_one = candidate(
            None,
            query="gamma",
            canonical_url="https://x.com/example/not-a-status",
            provenance={"source_id": None},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        url_two = candidate(
            None,
            query="delta",
            canonical_url="https://x.com/example/not-a-status#fragment",
            provenance={"source_id": None},
            platform_fields={"is_repost": False, "is_reply": False},
        )

        result = MERGE.merge_envelopes(
            [envelope(first, url_one), envelope(second, url_two)]
        )

        self.assertEqual(len(result["candidates"]), 2)
        merged = next(item for item in result["candidates"] if item["candidate_id"] == "x:101")
        self.assertEqual(merged["queries"], ["alpha", "beta"])
        self.assertEqual(merged["metrics"]["likes"], 8)
        self.assertEqual(len(merged["provenance"]["merged_sources"]), 2)
        self.assertEqual(result["request"]["queries"], ["alpha", "gamma", "beta", "delta"])
        reducer_coverage = result["coverage"][-1]
        self.assertEqual(reducer_coverage["duplicate_observations_merged"], 2)

    def test_default_filters_explicit_reposts_and_replies(self):
        repost = candidate("201", platform_fields={"is_repost": True, "is_reply": False})
        reply = candidate("202", platform_fields={"is_repost": False, "is_reply": True})
        plain = candidate("203", platform_fields={"is_repost": False, "is_reply": False})

        result = MERGE.merge_envelopes([envelope(repost, reply, plain)])
        self.assertEqual([item["candidate_id"] for item in result["candidates"]], ["x:203"])
        self.assertEqual(result["coverage"][-1]["filtered"]["reposts"], 1)
        self.assertEqual(result["coverage"][-1]["filtered"]["replies"], 1)

        included = MERGE.merge_envelopes(
            [envelope(repost, reply, plain)],
            include_reposts=True,
            include_replies=True,
        )
        self.assertEqual(len(included["candidates"]), 3)

    def test_unknown_repost_and_reply_status_are_retained_with_limitations(self):
        unknown = candidate("301", platform_fields={})
        result = MERGE.merge_envelopes([envelope(unknown)])
        self.assertEqual(len(result["candidates"]), 1)
        limitations = result["candidates"][0]["limitations"]
        self.assertIn(MERGE.UNKNOWN_REPOST_LIMITATION, limitations)
        self.assertIn(MERGE.UNKNOWN_REPLY_LIMITATION, limitations)
        self.assertEqual(result["coverage"][-1]["unknown_repost_status"], 1)
        self.assertEqual(result["coverage"][-1]["unknown_reply_status"], 1)

    def test_author_language_and_metric_thresholds_are_deterministic(self):
        passing = candidate(
            "401",
            author="@Alice",
            language="zh",
            metrics={"likes": 10, "comments": 3, "shares": 4, "views": 100},
            platform_fields={
                "screen_name": "alice",
                "is_repost": False,
                "is_reply": False,
            },
        )
        unknown_views = candidate(
            "402",
            author="Alice",
            language="zh",
            metrics={"likes": 10, "comments": 3, "shares": 4, "views": None},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        wrong_author = candidate(
            "403",
            author="Bob",
            language="zh",
            metrics={"likes": 10, "comments": 3, "shares": 4, "views": 100},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        wrong_language = candidate(
            "404",
            author="Alice",
            language="en",
            metrics={"likes": 10, "comments": 3, "shares": 4, "views": 100},
            platform_fields={"is_repost": False, "is_reply": False},
        )

        result = MERGE.merge_envelopes(
            [envelope(passing, unknown_views, wrong_author, wrong_language)],
            authors=["alice"],
            languages=["ZH"],
            min_likes=10,
            min_reposts=4,
            min_replies=3,
            min_views=100,
        )
        self.assertEqual([item["candidate_id"] for item in result["candidates"]], ["x:401"])
        filtered = result["coverage"][-1]["filtered"]
        self.assertEqual(filtered["min_views"], 1)
        self.assertEqual(filtered["author"], 1)
        self.assertEqual(filtered["language"], 1)

    def test_relevance_sort_uses_best_original_rank_and_global_limit(self):
        low = candidate("501", rank=5, platform_fields={"is_repost": False, "is_reply": False})
        high = candidate("502", rank=1, platform_fields={"is_repost": False, "is_reply": False})
        middle = candidate("503", rank=3, platform_fields={"is_repost": False, "is_reply": False})
        result = MERGE.merge_envelopes(
            [envelope(low, high, middle)], sort="relevance", limit=2
        )
        self.assertEqual([item["candidate_id"] for item in result["candidates"]], ["x:502", "x:503"])
        self.assertEqual([item["rank"] for item in result["candidates"]], [1, 2])
        self.assertTrue(result["coverage"][-1]["truncated"])

    def test_recent_sort_places_unknown_time_last(self):
        old = candidate(
            "601",
            published_at="2026-08-07T00:00:00Z",
            platform_fields={"is_repost": False, "is_reply": False},
        )
        new = candidate(
            "602",
            published_at="2026-08-09T00:00:00+00:00",
            platform_fields={"is_repost": False, "is_reply": False},
        )
        unknown = candidate(
            "603",
            published_at=None,
            platform_fields={"is_repost": False, "is_reply": False},
        )
        result = MERGE.merge_envelopes([envelope(old, unknown, new)], sort="recent")
        self.assertEqual(
            [item["candidate_id"] for item in result["candidates"]],
            ["x:602", "x:601", "x:603"],
        )

    def test_engagement_sort_uses_sum_then_views_then_time(self):
        highest = candidate(
            "701",
            published_at="2026-08-01T00:00:00Z",
            metrics={"likes": 4, "comments": 2, "shares": 1, "views": 1},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        lower_views = candidate(
            "702",
            published_at="2026-08-09T00:00:00Z",
            metrics={"likes": 3, "comments": 1, "shares": 1, "views": 10},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        older = candidate(
            "703",
            published_at="2026-08-07T00:00:00Z",
            metrics={"likes": 4, "comments": 1, "shares": 0, "views": 20},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        newer = candidate(
            "704",
            published_at="2026-08-08T00:00:00Z",
            metrics={"likes": 2, "comments": 2, "shares": 1, "views": 20},
            platform_fields={"is_repost": False, "is_reply": False},
        )
        result = MERGE.merge_envelopes(
            [envelope(lower_views, older, newer, highest)], sort="engagement"
        )
        self.assertEqual(
            [item["candidate_id"] for item in result["candidates"]],
            ["x:701", "x:704", "x:703", "x:702"],
        )
        metadata = result["candidates"][0]["platform_fields"]["x_research_merge"]
        self.assertEqual(metadata["engagement_formula"], "likes + reposts + replies")
        self.assertEqual(metadata["engagement_score"], 7)

    def test_input_errors_are_structured_and_cli_returns_nonzero(self):
        with self.assertRaises(MERGE.MergeError) as invalid_json:
            MERGE.load_envelopes(["-"], stdin=io.StringIO("{"))
        self.assertEqual(invalid_json.exception.category, "invalid_json")

        wrong_platform = envelope(candidate("801"))
        wrong_platform["candidates"][0]["platform"] = "web"
        with self.assertRaises(MERGE.MergeError) as invalid_platform:
            MERGE.validate_envelope(wrong_platform, "fixture")
        self.assertEqual(invalid_platform.exception.category, "invalid_platform")

        output = io.StringIO()
        return_code = MERGE.main(
            ["--input", "-"], stdin=io.StringIO("not-json"), stdout=output
        )
        self.assertEqual(return_code, 2)
        error_envelope = json.loads(output.getvalue())
        self.assertEqual(error_envelope["schema_version"], "1.0")
        self.assertEqual(error_envelope["routes"][0]["status"], "failed")
        self.assertEqual(error_envelope["errors"][0]["category"], "invalid_json")

    def test_grok_candidates_require_matched_adapter_provenance(self):
        grok = candidate("901", platform_fields={"is_repost": False, "is_reply": False})
        grok["backend"] = "grok-consult"
        with self.assertRaises(MERGE.MergeError) as missing_gate:
            MERGE.validate_envelope(envelope(grok), "fixture")
        self.assertEqual(
            missing_gate.exception.category, "invalid_grok_provenance"
        )

        grok["provenance"].update(
            {
                "grok_time_verification_bucket": "excluded_outside_window",
                "grok_native_x_search_verified": True,
            }
        )
        with self.assertRaises(MERGE.MergeError) as excluded_gate:
            MERGE.validate_envelope(envelope(grok), "fixture")
        self.assertEqual(
            excluded_gate.exception.category, "invalid_grok_provenance"
        )

        grok["provenance"]["grok_time_verification_bucket"] = "matched"
        MERGE.validate_envelope(envelope(grok), "fixture")

    def test_all_backends_reject_conflicting_tweet_id_sources(self):
        conflicting = candidate("2022453251732574693")
        conflicting["provenance"]["source_id"] = "2022453251732574692"
        conflicting["platform_fields"] = {
            "x": {"tweet_id": "2022453251732574693"}
        }

        with self.assertRaises(MERGE.MergeError) as mismatch:
            MERGE.validate_envelope(envelope(conflicting), "fixture")
        self.assertEqual(mismatch.exception.category, "inconsistent_x_tweet_id")

    def test_rejects_nonpublic_or_non_x_candidate_urls(self):
        local = candidate("902")
        local["url"] = "https://localhost/status/902"
        local["canonical_url"] = local["url"]
        with self.assertRaises(MERGE.MergeError) as invalid_url:
            MERGE.validate_envelope(envelope(local), "fixture")
        self.assertEqual(invalid_url.exception.category, "invalid_x_url")

        private = candidate("903")
        private["access"]["visibility"] = "private"
        with self.assertRaises(MERGE.MergeError) as invalid_visibility:
            MERGE.validate_envelope(envelope(private), "fixture")
        self.assertEqual(
            invalid_visibility.exception.category, "invalid_visibility"
        )


if __name__ == "__main__":
    unittest.main()
