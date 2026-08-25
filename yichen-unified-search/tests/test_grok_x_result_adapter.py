import importlib.util
import io
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "grok_x_result_adapter", ROOT / "scripts" / "grok_x_result_adapter.py"
)
ADAPTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)

MERGE_SPEC = importlib.util.spec_from_file_location(
    "x_research_merge_for_adapter_test",
    ROOT / "scripts" / "x_research_merge.py",
)
MERGER = importlib.util.module_from_spec(MERGE_SPEC)
assert MERGE_SPEC.loader is not None
sys.modules[MERGE_SPEC.name] = MERGER
MERGE_SPEC.loader.exec_module(MERGER)


MATCHED_ID = "2022453251732574692"
EXCLUDED_ID = "2011111111111111111"


def native_verification(**overrides):
    value = {
        "verified": True,
        "x_search_completed_call_count": 3,
        "completed_tool_call_count": 4,
        "completed_tool_names": ["XSearch", "XSearch", "XSearch", "WebSearch"],
    }
    value.update(overrides)
    return value


def matched_post(tweet_id=MATCHED_ID, **overrides):
    value = {
        "url": f"https://x.com/aiedge_/status/{tweet_id}",
        "author": "@aiedge_",
        "tweet_id": tweet_id,
        "created_at_utc": "2026-08-09T01:02:03.000Z",
        "created_at_local": "2026-08-09T09:02:03+08:00",
        "timezone": "Asia/Shanghai",
        "date_match": None,
        "window_match": True,
        "url_provenance": "grok_final_answer_after_verified_native_x_search",
    }
    value.update(overrides)
    return value


def excluded_post():
    return {
        "url": f"https://x.com/old/status/{EXCLUDED_ID}",
        "author": "@old",
        "tweet_id": EXCLUDED_ID,
        "created_at_utc": "2026-08-01T01:02:03.000Z",
        "created_at_local": "2026-08-01T09:02:03+08:00",
        "timezone": "Asia/Shanghai",
        "date_match": None,
        "window_match": False,
        "url_provenance": "grok_final_answer_after_verified_native_x_search",
    }


def time_verification(**overrides):
    value = {
        "verification_method": "fixture snowflake decode",
        "requested_date": None,
        "requested_hours": 24,
        "timezone": "Asia/Shanghai",
        "matched_count": 1,
        "matched": [matched_post()],
        "excluded_outside_window": [excluded_post()],
        "as_of_utc": "2026-08-09T02:00:00.000Z",
    }
    value.update(overrides)
    return value


def tagged_text(native=None, time=None):
    native = native_verification() if native is None else native
    time = time_verification() if time is None else time
    return "\n".join(
        [
            "Grok advisory fixture",
            "<native_search_verification>",
            json.dumps(native),
            "</native_search_verification>",
            "<x_post_time_verification>",
            json.dumps(time),
            "</x_post_time_verification>",
        ]
    )


def fallback_text(route="fxtwitter-public", *, source_candidates=None):
    local = {"route": route, "read_only": True, "exit_code": 0}
    parts = ["X read-only fallback fixture"]
    if source_candidates is not None:
        parts.extend(
            [
                "<fxtwitter-public_output>",
                json.dumps({"schema_version": "1.0", "candidates": source_candidates}),
                "</fxtwitter-public_output>",
            ]
        )
    parts.extend(
        [
            "<local_reader_verification>",
            json.dumps(local),
            "</local_reader_verification>",
            "<x_post_time_verification>",
            json.dumps(time_verification()),
            "</x_post_time_verification>",
        ]
    )
    return "\n".join(parts)


def run_main(raw, *extra_args):
    stdout = io.StringIO()
    status = ADAPTER.main(
        ["--input", "-", "--query", "AI agent releases", *extra_args],
        stdin=io.StringIO(raw),
        stdout=stdout,
    )
    return status, json.loads(stdout.getvalue())


class GrokXResultAdapterTests(unittest.TestCase):
    def test_plain_text_maps_only_structured_matched_fields(self):
        result = ADAPTER.normalize_grok_result(
            tagged_text(),
            query="AI agent releases",
            call_index=7,
            phase="supplementary",
        )

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["routes"][0]["status"], "completed")
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_id"], f"x:{MATCHED_ID}")
        self.assertEqual(candidate["backend"], "grok-consult")
        self.assertEqual(candidate["author"], "@aiedge_")
        self.assertEqual(candidate["published_at"], "2026-08-09T01:02:03.000Z")
        self.assertIsNone(candidate["title"])
        self.assertIsNone(candidate["snippet"])
        self.assertIsNone(candidate["language"])
        self.assertIsNone(candidate["content_type"])
        self.assertTrue(all(value is None for value in candidate["metrics"].values()))
        provenance = candidate["provenance"]
        self.assertEqual(provenance["source_id"], MATCHED_ID)
        self.assertEqual(provenance["grok_time_verification_bucket"], "matched")
        self.assertEqual(provenance["call_index"], 7)
        self.assertEqual(provenance["phase"], "supplementary")
        self.assertEqual(provenance["native_x_search_completed_call_count"], 3)
        self.assertTrue(provenance["grok_native_x_search_verified"])
        self.assertEqual(candidate["platform_fields"]["x"]["reply_status"], "unknown")
        self.assertEqual(candidate["platform_fields"]["x"]["repost_status"], "unknown")
        MERGER.validate_envelope(result, "adapter output")

    def test_accepts_mcp_json_content_text_wrapper(self):
        wrapper = json.dumps(
            {
                "content": [
                    {"type": "image", "data": "ignored"},
                    {"type": "text", "text": tagged_text()},
                ]
            }
        )
        status, result = run_main(wrapper, "--call-index", "2")
        self.assertEqual(status, 0)
        self.assertEqual(result["candidates"][0]["provenance"]["call_index"], 2)

    def test_excluded_outside_window_is_coverage_only(self):
        result = ADAPTER.normalize_grok_result(
            tagged_text(), query="AI agent releases"
        )
        self.assertEqual(result["coverage"][0]["matched_count"], 1)
        self.assertEqual(
            result["coverage"][0]["excluded_outside_window_count"], 1
        )
        serialized_candidates = json.dumps(result["candidates"])
        self.assertNotIn(EXCLUDED_ID, serialized_candidates)

    def test_missing_or_duplicate_verification_blocks_fail_closed(self):
        valid = tagged_text()
        missing = valid.split("<native_search_verification>", 1)[0]
        duplicate = valid + "\n" + valid
        for raw in (missing, duplicate):
            with self.subTest(raw_length=len(raw)):
                status, result = run_main(raw)
                self.assertEqual(status, 2)
                self.assertEqual(result["routes"][0]["status"], "failed")
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_matched_count_mismatch_fails_closed(self):
        payload = time_verification(matched_count=2)
        status, result = run_main(tagged_text(time=payload))
        self.assertEqual(status, 2)
        self.assertEqual(result["errors"][0]["category"], "contract_error")
        self.assertIn("matched_count", result["errors"][0]["message"])

    def test_false_window_match_inside_matched_fails_closed(self):
        payload = time_verification(matched=[matched_post(window_match=False)])
        status, result = run_main(tagged_text(time=payload))
        self.assertEqual(status, 2)
        self.assertEqual(result["candidates"], [])
        self.assertIn("window_match", result["errors"][0]["message"])

    def test_status_url_and_tweet_id_mismatch_fails_closed(self):
        bad = matched_post(url="https://x.com/aiedge_/status/2022453251732574693")
        payload = time_verification(matched=[bad])
        status, result = run_main(tagged_text(time=payload))
        self.assertEqual(status, 2)
        self.assertIn("does not match tweet_id", result["errors"][0]["message"])

    def test_author_must_match_status_url_handle(self):
        bad = matched_post(author="@victim")
        payload = time_verification(matched=[bad])
        status, result = run_main(tagged_text(time=payload))
        self.assertEqual(status, 2)
        self.assertEqual(result["candidates"], [])
        self.assertIn("does not match", result["errors"][0]["message"])

    def test_native_verification_must_be_true_and_have_completed_search(self):
        invalid_native_values = [
            native_verification(verified=False),
            native_verification(x_search_completed_call_count=0),
        ]
        for native in invalid_native_values:
            with self.subTest(native=native):
                status, result = run_main(tagged_text(native=native))
                self.assertEqual(status, 2)
                self.assertEqual(result["routes"][0]["status"], "failed")
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["category"], "contract_error")

    def test_read_only_fxtwitter_fallback_preserves_only_matched_structured_candidate(self):
        matched_source = {
            "candidate_id": f"x:{MATCHED_ID}",
            "backend": "fxtwitter-public",
            "title": "Structured public result",
            "snippet": "Public result text",
            "author": "AI Edge",
            "content_type": "x_post",
            "language": "en",
            "metrics": {
                "likes": 12,
                "comments": 3,
                "collects": 2,
                "shares": 4,
                "views": 500,
            },
            "provenance": {"source_id": MATCHED_ID},
            "platform_fields": {"screen_name": "aiedge_"},
            "limitations": ["FxTwitter fixture limitation."],
        }
        excluded_source = {
            "candidate_id": f"x:{EXCLUDED_ID}",
            "snippet": "Must not enter candidates",
            "provenance": {"source_id": EXCLUDED_ID},
        }
        status, result = run_main(
            fallback_text(source_candidates=[matched_source, excluded_source]),
            "--phase",
            "supplementary",
        )
        self.assertEqual(status, 0)
        self.assertEqual(result["routes"][0]["backend"], "fxtwitter-public")
        self.assertFalse(result["routes"][0]["login_state_used"])
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_id"], f"x:{MATCHED_ID}")
        self.assertEqual(candidate["backend"], "fxtwitter-public")
        self.assertEqual(candidate["snippet"], "Public result text")
        self.assertEqual(candidate["metrics"]["likes"], 12)
        self.assertIn(
            ADAPTER.FXTWITTER_FIELDS_LIMITATION,
            candidate["limitations"],
        )
        self.assertNotIn(ADAPTER.UNKNOWN_FIELDS_LIMITATION, candidate["limitations"])
        self.assertIn(
            ADAPTER.FXTWITTER_FIELDS_LIMITATION,
            result["routes"][0]["limitations"],
        )
        self.assertTrue(candidate["provenance"]["local_reader_verified"])
        self.assertEqual(
            candidate["provenance"]["local_reader_route"], "fxtwitter-public"
        )
        self.assertEqual(
            candidate["provenance"]["grok_time_verification_bucket"], "matched"
        )
        self.assertNotIn(EXCLUDED_ID, json.dumps(result["candidates"]))
        self.assertEqual(result["coverage"][0]["excluded_outside_window_count"], 1)

    def test_unapproved_or_non_read_only_local_reader_is_rejected(self):
        cases = [
            fallback_text(route="browser"),
            fallback_text().replace('"read_only": true', '"read_only": false'),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                status, result = run_main(raw)
                self.assertEqual(status, 2)
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["category"], "contract_error")

    def test_native_and_local_verification_are_mutually_exclusive(self):
        local_block = "\n".join(
            [
                "<local_reader_verification>",
                json.dumps({"route": "xreach", "read_only": True}),
                "</local_reader_verification>",
            ]
        )
        status, result = run_main(tagged_text() + "\n" + local_block)
        self.assertEqual(status, 2)
        self.assertEqual(result["errors"][0]["category"], "parse_error")

    def test_duplicate_single_tag_is_rejected_even_when_other_tag_is_unique(self):
        native_block = "\n".join(
            [
                "<native_search_verification>",
                json.dumps(native_verification()),
                "</native_search_verification>",
            ]
        )
        raw = tagged_text() + "\n" + native_block
        status, result = run_main(raw)
        self.assertEqual(status, 2)
        self.assertIn("at most one", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
