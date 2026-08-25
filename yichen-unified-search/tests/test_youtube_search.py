import importlib.util
import json
import os
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "youtube_search", ROOT / "scripts" / "youtube_search.py"
)
YOUTUBE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = YOUTUBE
SPEC.loader.exec_module(YOUTUBE)


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        self.read_limit = limit
        return self.body


class FakeOpener:
    def __init__(self, body=None, error=None):
        self.response = FakeResponse(body) if body is not None else None
        self.error = error

    def open(self, request, timeout):
        if self.error is not None:
            raise self.error
        return self.response


class YouTubeSearchTests(unittest.TestCase):
    def test_api_get_reads_one_bounded_response(self):
        opener = FakeOpener(b'{"items": []}')
        with mock.patch.object(YOUTUBE, "API_OPENER", opener):
            payload = YOUTUBE.api_get("search", {"part": "id"}, key="test", timeout=5)
        self.assertEqual(payload, {"items": []})
        self.assertEqual(
            opener.response.read_limit,
            YOUTUBE.MAX_API_RESPONSE_BYTES + 1,
        )

    def test_api_get_rejects_oversized_response(self):
        opener = FakeOpener(b"x" * (YOUTUBE.MAX_API_RESPONSE_BYTES + 1))
        with (
            mock.patch.object(YOUTUBE, "API_OPENER", opener),
            self.assertRaises(YOUTUBE.SearchError) as raised,
        ):
            YOUTUBE.api_get("search", {"part": "id"}, key="test", timeout=5)
        self.assertEqual(raised.exception.category, "response_too_large")

    def test_api_get_refuses_redirects(self):
        redirected = YOUTUBE.urllib.error.HTTPError(
            "https://www.googleapis.com/youtube/v3/search",
            302,
            "Found",
            {"Location": "https://example.net/"},
            None,
        )
        opener = FakeOpener(error=redirected)
        with (
            mock.patch.object(YOUTUBE, "API_OPENER", opener),
            self.assertRaises(YOUTUBE.SearchError) as raised,
        ):
            YOUTUBE.api_get("search", {"part": "id"}, key="test", timeout=5)
        self.assertEqual(raised.exception.category, "redirect_refused")

    def test_duration_parsers(self):
        self.assertEqual(YOUTUBE.parse_duration("PT1H30M5S"), 5405)
        self.assertEqual(YOUTUBE.parse_duration_input("1h30m"), 5400)
        self.assertEqual(YOUTUBE.parse_duration_input("45"), 2700)

    def test_exact_channel_target_never_guesses_a_name(self):
        self.assertEqual(
            YOUTUBE.channel_target("@example"),
            "https://www.youtube.com/@example/videos",
        )
        with self.assertRaises(YOUTUBE.SearchError):
            YOUTUBE.channel_target("Example Creator")

    def test_flat_results_map_to_candidate_schema(self):
        rows = [
            {
                "id": "abcdefghijk",
                "title": "Example",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "description": "Public result",
                "channel": "Example Channel",
                "channel_id": "UCabcdefghijklmnopqrstuv",
                "published_at": "2026-07-31T00:00:00Z",
                "duration_seconds": 90,
                "views": 123,
                "likes": None,
            }
        ]
        payload = YOUTUBE.envelope(
            query="example",
            mode="search",
            backend=YOUTUBE.BACKEND_YTDLP,
            limit=10,
            rows=rows,
            time_range=None,
        )
        item = payload["candidates"][0]
        self.assertEqual(item["candidate_id"], "youtube:abcdefghijk")
        self.assertEqual(item["platform"], "youtube")
        self.assertFalse(item["access"]["login_state_used"])
        self.assertEqual(item["metrics"]["views"], 123)

    def test_auto_backend_without_key_uses_anonymous_ytdlp(self):
        args = YOUTUBE.parse_args(["search", "example", "--limit", "2"])
        rows = [
            {
                "id": "abcdefghijk",
                "title": "Example",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "description": None,
                "channel": None,
                "channel_id": None,
                "published_at": None,
                "duration_seconds": None,
                "views": None,
                "likes": None,
            }
        ]
        with (
            mock.patch.object(YOUTUBE, "api_key", return_value=None),
            mock.patch.object(YOUTUBE, "run_ytdlp", return_value=rows) as runner,
        ):
            payload = YOUTUBE.execute(args)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["limit"], 6)
        self.assertTrue(runner.call_args.args[0].startswith("ytsearch6:"))
        self.assertEqual(payload["routes"][0]["backend"], YOUTUBE.BACKEND_YTDLP)

    def test_ytdlp_fallback_ignores_user_config_plugins_cache_and_downloads(self):
        runner = mock.Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"entries": []}),
                stderr="",
            )
        )
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": "/private/home",
            "YOUTUBE_API_KEY": "youtube-secret",  # pragma: allowlist secret
            "FIRECRAWL_API_KEY": "firecrawl-secret",  # pragma: allowlist secret
            "ANYSEARCH_API_KEY": "anysearch-secret",  # pragma: allowlist secret
            "BROWSER_COOKIE": "cookie-secret",  # pragma: allowlist secret
        }
        with (
            mock.patch.object(YOUTUBE.shutil, "which", return_value="/opt/yt-dlp"),
            mock.patch.dict(os.environ, environment, clear=True),
        ):
            self.assertEqual(
                YOUTUBE.run_ytdlp("ytsearch5:example", limit=5, timeout=20, runner=runner),
                [],
            )

        command = runner.call_args.args[0]
        for option in (
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-cache-dir",
            "--skip-download",
            "--flat-playlist",
        ):
            self.assertIn(option, command)
        child_env = runner.call_args.kwargs["env"]
        self.assertEqual(child_env, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        self.assertNotIn("HOME", child_env)

    def test_script_contains_no_media_download_or_cookie_command(self):
        source = (ROOT / "scripts" / "youtube_search.py").read_text(encoding="utf-8")
        self.assertNotIn("--audio-format", source)
        self.assertNotIn("--write-subs", source)
        self.assertNotIn("--cookies-from-browser", source)
        self.assertIn('"--ignore-config"', source)
        self.assertIn('"--skip-download"', source)


if __name__ == "__main__":
    unittest.main()
