#!/usr/bin/env python3
"""Read AI HOT's public API and emit unified-search candidate envelopes."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    import idna as _idna_uts46
except ImportError:  # Fail closed for non-ASCII hosts when the helper is absent.
    _idna_uts46 = None


BASE_URL = "https://aihot.virxact.com"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
CATEGORIES = ("ai-models", "ai-products", "industry", "paper", "tip")
CATEGORY_BY_DAILY_LABEL = {
    "模型发布/更新": "ai-models",
    "产品发布/更新": "ai-products",
    "行业动态": "industry",
    "论文研究": "paper",
    "技巧与观点": "tip",
}
AI_SUMMARY_LIMITATION = (
    "AI HOT summaries may be AI-generated discovery text; verify the original URL "
    "before citing facts."
)
MAX_RESPONSE_BYTES = 4_000_000


class RejectRedirects(HTTPRedirectHandler):
    """Keep the fixed AI HOT origin from redirecting requests elsewhere."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


AIHOT_OPENER = build_opener(RejectRedirects())


def _normalize_host_uts46(raw_host: str) -> str:
    """Normalize a URL host without legacy IDNA2003 target changes."""

    host_input = raw_host.rstrip(".")
    if not host_input or "%" in host_input:
        raise ValueError("URL host is malformed")
    try:
        literal = ipaddress.ip_address(host_input)
    except ValueError:
        literal = None
    if literal is not None:
        return str(literal).lower()
    if _idna_uts46 is None:
        if any(ord(character) > 0x7F for character in host_input):
            raise ValueError("URL host is malformed")
        try:
            return host_input.encode("ascii").decode("ascii").lower()
        except UnicodeError:
            raise ValueError("URL host is malformed") from None
    try:
        return _idna_uts46.encode(
            host_input,
            uts46=True,
            transitional=False,
            std3_rules=True,
        ).decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise ValueError("URL host is malformed") from None


def validate_public_http_url(value: object) -> str:
    """Return a literal public HTTP(S) URL without performing DNS resolution."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("a public HTTP(S) URL is required")
    cleaned = value.strip()
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in cleaned):
        raise ValueError("URL contains unsafe whitespace or control characters")
    try:
        parsed = urlsplit(cleaned)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("URL is malformed") from None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("URL is not HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL contains user information")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("URL port is invalid")

    host = _normalize_host_uts46(hostname)
    if not host or len(host) > 253:
        raise ValueError("URL host is malformed")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("URL does not identify a public host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("URL does not identify a public host")
    if address is None:
        if "." not in host:
            raise ValueError("URL host must be a fully qualified public name")
        labels = host.split(".")
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
            raise ValueError("URL contains an ambiguous numeric host")
        if any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            is None
            for label in labels
        ):
            raise ValueError("URL host is malformed")
    return cleaned


def optional_text(value: object, *, field: str) -> str | None:
    """Normalize one optional upstream string, rejecting type confusion."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    return cleaned or None


def required_text(value: object, *, field: str) -> str:
    cleaned = optional_text(value, field=field)
    if cleaned is None:
        raise ValueError(f"{field} is required")
    return cleaned


def optional_timestamp(value: object, *, field: str) -> str | None:
    """Normalize an optional timezone-aware ISO-8601 timestamp."""

    cleaned = optional_text(value, field=field)
    if cleaned is None:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return iso_z(parsed)


def optional_source_id(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("id must be a string or integer")
    cleaned = str(value).strip()
    return cleaned or None


def normalize_raw_candidate(
    raw: object, *, category: str | None = None
) -> dict[str, object]:
    """Validate one AI HOT row before it can enter a public candidate envelope."""

    if not isinstance(raw, dict):
        raise ValueError("candidate must be an object")
    url = validate_public_http_url(raw.get("url") or raw.get("sourceUrl"))
    title = required_text(raw.get("title"), field="title")
    raw_category = raw.get("category", category)
    resolved_category = optional_text(raw_category, field="category")
    if resolved_category is not None and resolved_category not in CATEGORIES:
        raise ValueError("category is not recognized")
    return {
        "id": optional_source_id(raw.get("id")),
        "title": title,
        "title_en": optional_text(raw.get("title_en"), field="title_en"),
        "url": url,
        "summary": optional_text(raw.get("summary"), field="summary"),
        "source": optional_text(
            raw.get("source") if raw.get("source") is not None else raw.get("sourceName"),
            field="source",
        ),
        "published_at": optional_timestamp(raw.get("publishedAt"), field="publishedAt"),
        "category": resolved_category,
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def stable_id(source_id: str | None, url: str) -> str:
    if source_id:
        return f"aihot:{source_id}"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"aihot:{digest}"


def content_type(category: str | None) -> str:
    return "ai_paper" if category == "paper" else "ai_news"


def candidate(
    *,
    raw: dict,
    query: str,
    rank: int,
    retrieved_at: str,
    category: str | None = None,
    daily_date: str | None = None,
) -> dict:
    url = raw["url"]
    resolved_category = raw.get("category") or category
    return {
        "candidate_id": stable_id(raw.get("id"), url),
        "query": query,
        "platform": "web",
        "backend": "aihot",
        "rank": rank,
        "title": raw["title"],
        "url": url,
        "canonical_url": url,
        "snippet": raw.get("summary"),
        "author": None,
        "published_at": raw.get("published_at"),
        "content_type": content_type(resolved_category),
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
            "source_id": raw.get("id"),
            "retrieved_at": retrieved_at,
            "route_reason": "ai_realtime_discovery",
        },
        "platform_fields": {
            "aihot": {
                "source_name": raw.get("source"),
                "category": resolved_category,
                "title_en": raw.get("title_en"),
                "daily_date": daily_date,
            }
        },
        "limitations": [AI_SUMMARY_LIMITATION],
    }


def normalize_items(
    payload: dict,
    *,
    query: str,
    limit: int,
    days: int,
    feed: str,
    retrieved_at: str,
) -> dict:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("AI HOT items response is missing an items list")
    has_next = payload.get("hasNext", False)
    if not isinstance(has_next, bool):
        raise ValueError("AI HOT items response has an invalid hasNext value")

    candidates: list[dict] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    rejected_count = 0
    duplicate_count = 0
    accepted_count = 0
    for raw in raw_items:
        try:
            normalized = normalize_raw_candidate(raw)
        except ValueError:
            rejected_count += 1
            continue
        candidate_id = stable_id(normalized.get("id"), normalized["url"])
        if candidate_id in seen_ids or normalized["url"] in seen_urls:
            duplicate_count += 1
            continue
        seen_ids.add(candidate_id)
        seen_urls.add(normalized["url"])
        accepted_count += 1
        if len(candidates) >= limit:
            continue
        candidates.append(
            candidate(
                raw=normalized,
                query=query,
                rank=len(candidates) + 1,
                retrieved_at=retrieved_at,
            )
        )
    return envelope(
        query=query,
        requested_limit=limit,
        time_range={"days": days},
        mode=feed,
        candidates=candidates,
        raw_result_count=len(raw_items),
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        truncated=has_next or accepted_count > limit,
        limitations=[
            "AI HOT is a curated discovery index, not an exhaustive web index.",
            AI_SUMMARY_LIMITATION,
            "The AI HOT items endpoint covers at most the latest 7 days.",
        ],
    )


def normalize_daily(
    payload: dict, *, query: str, limit: int, retrieved_at: str
) -> dict:
    if "sections" not in payload and "flashes" not in payload:
        raise ValueError("AI HOT daily response is missing sections and flashes")
    sections = payload.get("sections", [])
    flashes = payload.get("flashes", [])
    if not isinstance(sections, list) or not isinstance(flashes, list):
        raise ValueError("AI HOT daily sections and flashes must be lists")

    daily_date = optional_text(payload.get("date"), field="date")
    if daily_date is not None:
        try:
            datetime.strptime(daily_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("AI HOT daily date must use YYYY-MM-DD") from None
    window_start = optional_timestamp(payload.get("windowStart"), field="windowStart")
    window_end = optional_timestamp(payload.get("windowEnd"), field="windowEnd")

    raw_candidates: list[tuple[object, str | None]] = []
    structural_rejected_count = 0
    for section in sections:
        if not isinstance(section, dict):
            structural_rejected_count += 1
            continue
        label = section.get("label")
        if label is not None and not isinstance(label, str):
            structural_rejected_count += 1
            label = None
        category = CATEGORY_BY_DAILY_LABEL.get(label)
        section_items = section.get("items", [])
        if not isinstance(section_items, list):
            structural_rejected_count += 1
            continue
        raw_candidates.extend((raw, category) for raw in section_items)
    raw_candidates.extend((raw, None) for raw in flashes)

    candidates: list[dict] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    rejected_count = structural_rejected_count
    duplicate_count = 0
    accepted_count = 0
    for raw, category in raw_candidates:
        try:
            normalized = normalize_raw_candidate(raw, category=category)
        except ValueError:
            rejected_count += 1
            continue
        candidate_id = stable_id(normalized.get("id"), normalized["url"])
        if candidate_id in seen_ids or normalized["url"] in seen_urls:
            duplicate_count += 1
            continue
        seen_ids.add(candidate_id)
        seen_urls.add(normalized["url"])
        accepted_count += 1
        if len(candidates) >= limit:
            continue
        candidates.append(
            candidate(
                raw=normalized,
                query=query,
                rank=len(candidates) + 1,
                retrieved_at=retrieved_at,
                category=category,
                daily_date=daily_date,
            )
        )

    time_range = {
        "date": daily_date,
        "window_start": window_start,
        "window_end": window_end,
    }
    return envelope(
        query=query,
        requested_limit=limit,
        time_range=time_range,
        mode="daily",
        candidates=candidates,
        raw_result_count=len(raw_candidates) + structural_rejected_count,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        truncated=accepted_count > limit,
        limitations=[
            "AI HOT daily reports are fixed UTC-day editorial snapshots, not rolling 24-hour windows.",
            AI_SUMMARY_LIMITATION,
        ],
    )


def envelope(
    *,
    query: str,
    requested_limit: int,
    time_range: dict,
    mode: str,
    candidates: list[dict],
    raw_result_count: int,
    rejected_count: int,
    duplicate_count: int,
    truncated: bool,
    limitations: list[str],
) -> dict:
    limitations = list(limitations)
    errors: list[dict[str, str]] = []
    status = "completed"
    if rejected_count:
        status = "partial" if candidates else "failed"
        limitations.append(
            f"{rejected_count} returned item(s) were rejected because required public candidate fields were invalid."
        )
        errors.append(
            {
                "backend": "aihot",
                "category": "invalid_candidate",
                "message": "AI HOT returned item(s) that could not be safely normalized.",
            }
        )
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["web"],
            "time_range": time_range,
            "requested_limit": requested_limit,
        },
        "routes": [
            {
                "platform": "web",
                "backend": "aihot",
                "mode": mode,
                "login_state_used": False,
                "status": status,
                "limitations": limitations,
            }
        ],
        "candidates": candidates,
        "coverage": [
            {
                "backend": "aihot",
                "query_count": 1,
                "raw_result_count": raw_result_count,
                "returned_count": len(candidates),
                "rejected_count": rejected_count,
                "duplicate_count": duplicate_count,
                "truncated": truncated,
                "login_state_used": False,
                "limitations": limitations,
            }
        ],
        "errors": errors,
    }


def error_envelope(query: str, category: str, message: str) -> dict:
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": None,
        },
        "routes": [
            {
                "platform": "web",
                "backend": "aihot",
                "mode": "search",
                "login_state_used": False,
                "status": "failed",
                "limitations": [],
            }
        ],
        "candidates": [],
        "coverage": [],
        "errors": [{"category": category, "message": message}],
    }


def build_url(
    *,
    feed: str,
    days: int,
    limit: int,
    keyword: str | None,
    category: str | None,
    date: str | None,
    now: datetime,
) -> str:
    if feed == "daily":
        suffix = f"/{date}" if date else ""
        return f"{BASE_URL}/api/public/daily{suffix}"
    params = {
        "mode": feed,
        "take": str(limit),
        "since": iso_z(now - timedelta(days=days)),
    }
    if keyword:
        params["q"] = keyword
    if category:
        params["category"] = category
    return f"{BASE_URL}/api/public/items?{urlencode(params)}"


def fetch_json(url: str, timeout: int, *, opener=None) -> dict:
    request = Request(
        url,
        headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
    )
    active_opener = opener or AIHOT_OPENER
    with active_opener.open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("AI HOT response exceeds the maximum allowed size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AI HOT returned invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("AI HOT returned a non-object JSON response")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search AI HOT and emit unified-search candidate JSON."
    )
    parser.add_argument("--query", required=True, help="Original user query")
    parser.add_argument(
        "--feed", choices=("selected", "all", "daily"), default="selected"
    )
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--keyword", help="Optional AI HOT server-side keyword")
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--date", help="YYYY-MM-DD; only valid with --feed daily")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if not 1 <= args.days <= 7:
        parser.error("--days must be between 1 and 7")
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60")
    if args.date:
        if args.feed != "daily":
            parser.error("--date requires --feed daily")
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            parser.error("--date must use YYYY-MM-DD")
    if args.feed == "daily" and (args.keyword or args.category):
        parser.error("--keyword and --category are not valid with --feed daily")
    return args


def main() -> int:
    args = parse_args()
    now = utc_now()
    url = build_url(
        feed=args.feed,
        days=args.days,
        limit=args.limit,
        keyword=args.keyword,
        category=args.category,
        date=args.date,
        now=now,
    )
    try:
        payload = fetch_json(url, args.timeout)
        retrieved_at = iso_z(utc_now())
        if args.feed == "daily":
            result = normalize_daily(
                payload,
                query=args.query,
                limit=args.limit,
                retrieved_at=retrieved_at,
            )
        else:
            result = normalize_items(
                payload,
                query=args.query,
                limit=args.limit,
                days=args.days,
                feed=args.feed,
                retrieved_at=retrieved_at,
            )
    except HTTPError as exc:
        result = error_envelope(
            args.query, "http_error", f"AI HOT returned HTTP {exc.code}"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except URLError as exc:
        result = error_envelope(args.query, "network_error", str(exc.reason))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        result = error_envelope(args.query, "invalid_response", str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
