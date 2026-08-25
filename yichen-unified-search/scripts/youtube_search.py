#!/usr/bin/env python3
"""Search public YouTube videos and emit unified-search candidate envelopes.

Search/filter behavior is derived in part from joeseesun/yt-search-download.
Copyright (c) 2026 Joe Sun (@joeseesun), used under the MIT License.
See references/THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


API_BASE = "https://www.googleapis.com/youtube/v3"
API_KEY_NAMES = ("YT_BROWSE_API_KEY", "YOUTUBE_API_KEY")
MAX_API_RESPONSE_BYTES = 4_000_000
SAFE_YTDLP_ENV_NAMES = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)
MAX_LIMIT = 50
BACKEND_API = "youtube-data-api-v3"
BACKEND_YTDLP = "yt-dlp-flat-search"
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class SearchError(RuntimeError):
    """A safe, user-facing search failure."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent a fixed Google API request from forwarding its API key."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


API_OPENER = urllib.request.build_opener(RejectRedirects())


def api_key() -> str | None:
    for name in API_KEY_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def anonymous_ytdlp_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal non-credential environment for anonymous discovery."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name.upper() in SAFE_YTDLP_ENV_NAMES
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_duration(value: str | None) -> int | None:
    """Convert an ISO-8601 YouTube duration to seconds."""
    if not value:
        return None
    match = re.fullmatch(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value
    )
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_duration_input(value: str | None) -> int | None:
    """Parse 30m, 1h, 1h30m, or a bare number interpreted as minutes."""
    if value is None:
        return None
    normalized = value.strip().lower()
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", normalized)
    if match and any(match.groups()):
        return int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
    if normalized.isdigit():
        return int(normalized) * 60
    raise ValueError(f"invalid duration: {value}")


def published_at_from_flat(entry: dict[str, Any]) -> str | None:
    timestamp = int_or_none(entry.get("timestamp") or entry.get("release_timestamp"))
    if timestamp is not None:
        try:
            return iso_z(datetime.fromtimestamp(timestamp, timezone.utc))
        except (OSError, OverflowError, ValueError):
            pass
    upload_date = text_or_none(entry.get("upload_date"))
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"
    return None


def api_get(endpoint: str, params: dict[str, Any], *, key: str, timeout: int) -> dict:
    query = dict(params)
    query["key"] = key
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "yichen-unified-search/1.0 (public YouTube search)",
        },
    )
    try:
        with API_OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_API_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            category = "redirect_refused"
        elif exc.code in {403, 429}:
            category = "quota_or_rate_limited"
        else:
            category = "upstream_http_error"
        raise SearchError(category, f"YouTube Data API returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError):
        raise SearchError("network_error", "YouTube Data API could not be reached.") from None

    if len(body) > MAX_API_RESPONSE_BYTES:
        raise SearchError("response_too_large", "YouTube Data API response exceeded 4 MB.")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SearchError("invalid_response", "YouTube Data API returned invalid JSON.") from None
    if not isinstance(payload, dict):
        raise SearchError("invalid_response", "YouTube Data API returned a non-object response.")
    return payload


def resolve_channel_api(channel: str, *, key: str, timeout: int) -> str:
    normalized = channel.strip()
    if CHANNEL_ID_RE.fullmatch(normalized):
        return normalized

    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme in {"http", "https"}:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "channel" and CHANNEL_ID_RE.fullmatch(parts[1]):
            return parts[1]
        if parts and parts[0].startswith("@"):
            normalized = parts[0]

    handle = normalized.lstrip("@").strip("/")
    if handle and re.fullmatch(r"[A-Za-z0-9._-]+", handle):
        payload = api_get(
            "channels",
            {"part": "id", "forHandle": handle, "maxResults": 1},
            key=key,
            timeout=timeout,
        )
        items = payload.get("items") or []
        if items:
            return items[0]["id"]

    payload = api_get(
        "search",
        {"part": "id", "type": "channel", "q": channel, "maxResults": 1},
        key=key,
        timeout=timeout,
    )
    items = payload.get("items") or []
    if items:
        channel_id = items[0].get("id", {}).get("channelId")
        if channel_id:
            return channel_id
    raise SearchError("channel_not_found", f"Could not resolve YouTube channel: {channel}")


def api_search(
    *,
    query: str,
    channel: str | None,
    limit: int,
    order: str,
    after: str | None,
    before: str | None,
    key: str,
    timeout: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": "id",
        "type": "video",
        "maxResults": limit,
        "order": order,
    }
    if query:
        params["q"] = query
    if channel:
        params["channelId"] = resolve_channel_api(channel, key=key, timeout=timeout)
    if after:
        params["publishedAfter"] = after
    if before:
        params["publishedBefore"] = before

    search_payload = api_get("search", params, key=key, timeout=timeout)
    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_payload.get("items") or []
        if isinstance(item, dict)
    ]
    video_ids = [video_id for video_id in video_ids if VIDEO_ID_RE.fullmatch(video_id or "")]
    if not video_ids:
        return []

    details_payload = api_get(
        "videos",
        {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
        },
        key=key,
        timeout=timeout,
    )
    details_by_id = {
        item.get("id"): item
        for item in details_payload.get("items") or []
        if isinstance(item, dict) and item.get("id")
    }
    results: list[dict[str, Any]] = []
    for video_id in video_ids:
        item = details_by_id.get(video_id)
        if not item:
            continue
        snippet = item.get("snippet") or {}
        statistics = item.get("statistics") or {}
        content_details = item.get("contentDetails") or {}
        results.append(
            {
                "id": video_id,
                "title": text_or_none(snippet.get("title")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "description": text_or_none(snippet.get("description")),
                "channel": text_or_none(snippet.get("channelTitle")),
                "channel_id": text_or_none(snippet.get("channelId")),
                "published_at": text_or_none(snippet.get("publishedAt")),
                "duration_seconds": parse_duration(content_details.get("duration")),
                "views": int_or_none(statistics.get("viewCount")),
                "likes": int_or_none(statistics.get("likeCount")),
            }
        )
    return results


def channel_target(channel: str) -> str:
    """Turn an exact public channel ID, handle, or URL into a /videos URL."""
    value = channel.strip()
    if CHANNEL_ID_RE.fullmatch(value):
        return f"https://www.youtube.com/channel/{value}/videos"
    if value.startswith("@") and re.fullmatch(r"@[A-Za-z0-9._-]+", value):
        return f"https://www.youtube.com/{value}/videos"

    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parsed.scheme not in {"http", "https"} or host not in {
        "youtube.com",
        "m.youtube.com",
    }:
        raise SearchError(
            "invalid_channel",
            "Anonymous channel browsing requires an exact YouTube @handle, channel ID, or channel URL.",
        )
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        raise SearchError("invalid_channel", "The YouTube channel URL is incomplete.")
    if parts[0].startswith("@") and re.fullmatch(r"@[A-Za-z0-9._-]+", parts[0]):
        base = f"https://www.youtube.com/{parts[0]}"
    elif len(parts) >= 2 and parts[0] == "channel" and CHANNEL_ID_RE.fullmatch(parts[1]):
        base = f"https://www.youtube.com/channel/{parts[1]}"
    else:
        raise SearchError(
            "invalid_channel",
            "Anonymous channel browsing supports @handle and /channel/UC... URLs only.",
        )
    return f"{base}/videos"


def run_ytdlp(
    target: str,
    *,
    limit: int,
    timeout: int,
    runner: Callable[..., Any] = subprocess.run,
) -> list[dict[str, Any]]:
    binary = shutil.which("yt-dlp")
    if not binary:
        raise SearchError("missing_dependency", "yt-dlp is not installed.")
    command = [
        binary,
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-cache-dir",
        "--skip-download",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--playlist-end",
        str(limit),
        target,
    ]
    try:
        result = runner(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=anonymous_ytdlp_environment(),
        )
    except subprocess.TimeoutExpired:
        raise SearchError("timeout", "yt-dlp YouTube discovery timed out.") from None
    if result.returncode:
        raise SearchError(
            "upstream_error",
            "yt-dlp could not read the requested public YouTube listing.",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SearchError("invalid_response", "yt-dlp returned invalid JSON.") from None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise SearchError("invalid_response", "yt-dlp response is missing an entries list.")

    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = text_or_none(entry.get("id"))
        if not video_id or not VIDEO_ID_RE.fullmatch(video_id):
            continue
        normalized.append(
            {
                "id": video_id,
                "title": text_or_none(entry.get("title")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "description": text_or_none(entry.get("description")),
                "channel": text_or_none(entry.get("channel") or entry.get("uploader")),
                "channel_id": text_or_none(entry.get("channel_id") or entry.get("uploader_id")),
                "published_at": published_at_from_flat(entry),
                "duration_seconds": int_or_none(entry.get("duration")),
                "views": int_or_none(entry.get("view_count")),
                "likes": int_or_none(entry.get("like_count")),
            }
        )
    return normalized


def filter_and_sort(
    rows: list[dict[str, Any]],
    *,
    query: str | None,
    min_duration: int | None,
    max_duration: int | None,
    after: datetime | None,
    before: datetime | None,
    sort_by: str | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    query_lower = query.casefold() if query else None
    for row in rows:
        if query_lower:
            haystack = " ".join(
                str(row.get(key) or "") for key in ("title", "description")
            ).casefold()
            if query_lower not in haystack:
                continue
        duration = int_or_none(row.get("duration_seconds"))
        if min_duration is not None and (duration is None or duration < min_duration):
            continue
        if max_duration is not None and (duration is None or duration > max_duration):
            continue
        published = text_or_none(row.get("published_at"))
        parsed_published = None
        if published:
            try:
                parsed_published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                pass
        if after and (parsed_published is None or parsed_published < after):
            continue
        if before and (parsed_published is None or parsed_published > before):
            continue
        filtered.append(row)

    if sort_by == "views":
        filtered.sort(key=lambda row: int_or_none(row.get("views")) or -1, reverse=True)
    elif sort_by == "duration-asc":
        filtered.sort(key=lambda row: int_or_none(row.get("duration_seconds")) or sys.maxsize)
    elif sort_by == "duration-desc":
        filtered.sort(key=lambda row: int_or_none(row.get("duration_seconds")) or -1, reverse=True)
    return filtered


def candidate(
    row: dict[str, Any], *, query: str, rank: int, backend: str, retrieved_at: str
) -> dict[str, Any]:
    video_id = row["id"]
    title = row.get("title") or f"YouTube video {video_id}"
    url = row["url"]
    snippet = row.get("description")
    if snippet and len(snippet) > 500:
        snippet = f"{snippet[:497]}..."
    return {
        "candidate_id": f"youtube:{video_id}",
        "query": query,
        "platform": "youtube",
        "backend": backend,
        "rank": rank,
        "title": title,
        "url": url,
        "canonical_url": url,
        "snippet": snippet,
        "author": row.get("channel"),
        "published_at": row.get("published_at"),
        "content_type": "youtube_video",
        "language": None,
        "metrics": {
            "likes": row.get("likes"),
            "comments": None,
            "collects": None,
            "shares": None,
            "views": row.get("views"),
        },
        "access": {"visibility": "public", "login_state_used": False},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": video_id,
            "retrieved_at": retrieved_at,
            "route_reason": "public_youtube_discovery",
        },
        "platform_fields": {
            "youtube": {
                "channel_id": row.get("channel_id"),
                "duration_seconds": row.get("duration_seconds"),
            }
        },
        "limitations": [
            "This is a public discovery candidate; the original watch page was not opened.",
            "YouTube search and channel listings are not guaranteed to be exhaustive.",
        ],
    }


def envelope(
    *,
    query: str,
    mode: str,
    backend: str,
    limit: int,
    rows: list[dict[str, Any]],
    time_range: dict[str, Any] | None,
    extra_limitations: list[str] | None = None,
) -> dict[str, Any]:
    limitations = [
        "Public YouTube discovery is not exhaustive and can vary by backend or region.",
        "Search results are candidates only; open the original URL before citing facts.",
    ]
    limitations.extend(extra_limitations or [])
    retrieved_at = iso_z(utc_now())
    candidates = [
        candidate(row, query=query, rank=index, backend=backend, retrieved_at=retrieved_at)
        for index, row in enumerate(rows[:limit], 1)
    ]
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["youtube"],
            "time_range": time_range,
            "requested_limit": limit,
        },
        "routes": [
            {
                "platform": "youtube",
                "backend": backend,
                "mode": mode,
                "login_state_used": False,
                "status": "completed",
                "limitations": limitations,
            }
        ],
        "candidates": candidates,
        "coverage": [
            {
                "backend": backend,
                "query_count": 1,
                "returned_count": len(candidates),
                "truncated": len(rows) > limit,
                "login_state_used": False,
                "limitations": limitations,
            }
        ],
        "errors": [],
    }


def error_envelope(query: str, mode: str, category: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["youtube"],
            "time_range": None,
            "requested_limit": None,
        },
        "routes": [
            {
                "platform": "youtube",
                "backend": None,
                "mode": mode,
                "login_state_used": False,
                "status": "failed",
                "limitations": [],
            }
        ],
        "candidates": [],
        "coverage": [],
        "errors": [{"category": category, "message": message}],
    }


def parse_day(value: str, *, end: bool = False) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def add_common_arguments(parser: argparse.ArgumentParser, *, default_order: str) -> None:
    parser.add_argument("-n", "--limit", type=int, default=20)
    parser.add_argument(
        "-o",
        "--order",
        choices=("relevance", "date", "viewCount", "rating"),
        default=default_order,
    )
    parser.add_argument("--sort-by", choices=("views", "duration-asc", "duration-desc"))
    parser.add_argument("--min-duration")
    parser.add_argument("--max-duration")
    parser.add_argument("--after", help="YYYY-MM-DD")
    parser.add_argument("--before", help="YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="Relative public time window")
    parser.add_argument("--backend", choices=("auto", "api", "yt-dlp"), default="auto")
    parser.add_argument("--timeout", type=int, default=30)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search public YouTube listings and emit unified candidate JSON."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search public YouTube videos")
    search.add_argument("query")
    search.add_argument("-c", "--channel", help="Exact channel handle, ID, URL, or API-resolvable name")
    add_common_arguments(search, default_order="relevance")

    channel = subparsers.add_parser("channel", help="Browse one exact public channel")
    channel.add_argument("channel")
    channel.add_argument("-q", "--query", default="", help="Optional local/API title query")
    add_common_arguments(channel, default_order="date")

    args = parser.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_LIMIT}")
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120")
    if args.days is not None and not 1 <= args.days <= 3650:
        parser.error("--days must be between 1 and 3650")
    try:
        args.min_duration_seconds = parse_duration_input(args.min_duration)
        args.max_duration_seconds = parse_duration_input(args.max_duration)
    except ValueError as exc:
        parser.error(str(exc))
    if (
        args.min_duration_seconds is not None
        and args.max_duration_seconds is not None
        and args.min_duration_seconds > args.max_duration_seconds
    ):
        parser.error("--min-duration cannot exceed --max-duration")
    try:
        args.after_dt = parse_day(args.after) if args.after else None
        args.before_dt = parse_day(args.before, end=True) if args.before else None
    except ValueError:
        parser.error("--after and --before must use YYYY-MM-DD")
    if args.days is not None:
        relative_after = utc_now() - timedelta(days=args.days)
        args.after_dt = max(filter(None, (args.after_dt, relative_after)), default=None)
    if args.after_dt and args.before_dt and args.after_dt > args.before_dt:
        parser.error("the effective start date is after the end date")
    return args


def execute(args: argparse.Namespace) -> dict[str, Any]:
    mode = args.command
    original_query = args.query if mode == "search" else args.channel
    channel = args.channel if mode in {"search", "channel"} else None
    search_query = args.query if mode in {"search", "channel"} else ""
    selected_key = api_key()
    use_api = args.backend == "api" or (args.backend == "auto" and selected_key is not None)
    fallback_limitations: list[str] = []
    local_query: str | None = None

    rows: list[dict[str, Any]]
    backend: str
    if use_api:
        if selected_key is None:
            raise SearchError(
                "missing_api_key",
                "YouTube Data API mode requires YT_BROWSE_API_KEY or YOUTUBE_API_KEY.",
            )
        try:
            rows = api_search(
                query=search_query,
                channel=channel,
                limit=args.limit,
                order=args.order,
                after=iso_z(args.after_dt) if args.after_dt else None,
                before=iso_z(args.before_dt) if args.before_dt else None,
                key=selected_key,
                timeout=args.timeout,
            )
            backend = BACKEND_API
        except SearchError as exc:
            if args.backend == "api":
                raise
            fallback_limitations.append(
                f"YouTube Data API was unavailable ({exc.category}); anonymous yt-dlp fallback was used."
            )
            use_api = False

    if not use_api:
        fetch_limit = min(MAX_LIMIT, max(args.limit * 3, 5))
        if mode == "search" and not args.channel:
            # Current yt-dlp/YouTube search can interleave channel cards with
            # videos. Fetch a small bounded surplus, then keep video IDs only.
            target = f"ytsearch{fetch_limit}:{args.query}"
            local_query = None
        else:
            target = channel_target(args.channel)
            local_query = search_query or None
        rows = run_ytdlp(target, limit=fetch_limit, timeout=args.timeout)
        backend = BACKEND_YTDLP
        if args.order not in {"relevance", "date"} and not args.sort_by:
            fallback_limitations.append(
                f"Anonymous yt-dlp does not guarantee API-level {args.order} ordering."
            )

    rows = filter_and_sort(
        rows,
        query=local_query,
        min_duration=args.min_duration_seconds,
        max_duration=args.max_duration_seconds,
        after=args.after_dt,
        before=args.before_dt,
        sort_by=args.sort_by,
    )
    time_range = (
        {
            "after": iso_z(args.after_dt) if args.after_dt else None,
            "before": iso_z(args.before_dt) if args.before_dt else None,
            "days": args.days,
        }
        if any((args.after_dt, args.before_dt, args.days))
        else None
    )
    return envelope(
        query=original_query,
        mode=mode,
        backend=backend,
        limit=args.limit,
        rows=rows,
        time_range=time_range,
        extra_limitations=fallback_limitations,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = execute(args)
        code = 0
    except SearchError as exc:
        query = args.query if args.command == "search" else args.channel
        payload = error_envelope(query, args.command, exc.category, exc.message)
        code = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
