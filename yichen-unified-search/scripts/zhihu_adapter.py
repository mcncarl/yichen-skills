#!/usr/bin/env python3
"""Read-only adapter for a separately installed Zhihu CLI public search runtime.

Only ``search zhihu`` and ``hot`` are reachable through this wrapper.  The
executable location may be overridden with ``ZHIHU_CLI``; the
environment credential is removed before every subprocess call so that
authentication can only come from the macOS Keychain configured by
``zhihu-cli`` itself. This repository does not independently verify the
runtime's vendor provenance or distribute its binary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


ZHIHU_CLI_ENV = "ZHIHU_CLI"
ZHIHU_CLI = Path(
    os.environ.get(
        ZHIHU_CLI_ENV,
        str(
            Path.home()
            / "Library"
            / "Application Support"
            / "zhihu-cli"
            / "current"
            / "zhihu-cli"
        ),
    )
).expanduser()
BACKEND = "zhihu-open-platform-cli"
PLATFORM = "zhihu"
ALLOWED_HOSTS = frozenset(
    {"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SEARCH_LIMIT = 10
HOT_LIMIT = 30
HOT_QUERY = "知乎热榜"
SAFE_CHILD_ENV_NAMES = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
        "TZ", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "PATHEXT", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)

SEARCH_LIMITATIONS = [
    "Zhihu search summaries are candidate metadata, not verified original body text.",
    "The original Zhihu page was not opened by this adapter.",
    "The configured Zhihu CLI search surface returns one bounded page of at most 10 items and currently has no pagination.",
    "The configured Zhihu CLI search surface does not expose a time filter; no publication-time window was applied.",
]
HOT_LIMITATIONS = [
    "The configured Zhihu CLI hot list is a current ranking snapshot, not fact verification or exhaustive event coverage.",
    "The original Zhihu page was not opened by this adapter.",
]


class AdapterError(RuntimeError):
    """A deliberately sanitized error safe to place in an output envelope."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not repeat unknown argument values, which might contain a secret."""

    def error(self, message: str) -> None:  # pragma: no cover - argparse exit path
        del message
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def safe_child_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return only runtime settings needed by the fixed CLI and macOS Keychain."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name.upper() in SAFE_CHILD_ENV_NAMES
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
    value = " ".join(value.split())
    return value or None


def integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


def timestamp_or_none(value: Any) -> str | None:
    timestamp = integer_or_none(value)
    if timestamp is None:
        return None
    try:
        return iso_z(datetime.fromtimestamp(timestamp, timezone.utc))
    except (OSError, OverflowError, ValueError):
        return None


def _has_unsafe_url_characters(value: str) -> bool:
    return "\\" in value or any(
        character.isspace()
        or unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in value
    )


def _safe_percent_encoding(value: str) -> bool:
    """Reject malformed, unsafe, or excessively nested percent encoding."""

    current = value
    for _ in range(16):
        if _has_unsafe_url_characters(current):
            return False
        if re.search(r"%(?![0-9A-Fa-f]{2})", current):
            return False
        if "%" not in current:
            return True
        try:
            decoded = unquote(current, encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError):
            return False
        if decoded == current:
            return True
        current = decoded
    # A normal URL stabilizes after one decode.  Refuse unusually deep input
    # instead of letting another layer hide a control character or backslash.
    return False


def canonicalize_zhihu_url(value: Any) -> tuple[str, str] | None:
    """Validate a public Zhihu URL and remove UTM parameters canonically."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 8192
        or value != value.strip()
        or _has_unsafe_url_characters(value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    if not all(
        _safe_percent_encoding(component)
        for component in (parsed.path, parsed.query, parsed.fragment)
    ):
        return None

    clean_pairs = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    canonical = urlunsplit(
        (
            "https",
            hostname,
            parsed.path or "/",
            urlencode(clean_pairs, doseq=True),
            "",
        )
    )
    return value, canonical


def content_type_slug(value: Any) -> str | None:
    content_type = text_or_none(value)
    if content_type is None or len(content_type) > 64:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", content_type.casefold()).strip("-")
    return slug or None


def content_identifier(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    identifier = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", identifier):
        return None
    return identifier


def featured_comments(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = text_or_none(item.get("Content"))
        if content is not None:
            result.append(content)
    return result


def infer_hot_identity(canonical_url: str) -> tuple[str, str | None]:
    parsed = urlsplit(canonical_url)
    path = parsed.path.rstrip("/")
    patterns = (
        (r"^/question/([0-9]+)$", "question"),
        (r"^/question/[0-9]+/answer/([0-9]+)$", "answer"),
        (r"^/answer/([0-9]+)$", "answer"),
        (r"^/p/([0-9]+)$", "article"),
        (r"^/pin/([0-9]+)$", "pin"),
    )
    for pattern, kind in patterns:
        match = re.fullmatch(pattern, path)
        if match:
            return kind, match.group(1)
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:20]
    return "hot-item", digest


def normalize_search_item(
    raw: Any, *, query: str, rank: int, retrieved_at: str
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = text_or_none(raw.get("Title"))
    content_slug = content_type_slug(raw.get("ContentType"))
    content_id = content_identifier(raw.get("ContentID"))
    resolved_url = canonicalize_zhihu_url(raw.get("Url"))
    if title is None or content_slug is None or content_id is None or resolved_url is None:
        return None
    url, canonical_url = resolved_url
    source_type = text_or_none(raw.get("ContentType"))
    limitations = list(SEARCH_LIMITATIONS)
    updated_at = timestamp_or_none(raw.get("EditTime"))
    if raw.get("EditTime") is not None and updated_at is None:
        limitations.append("Zhihu returned an unusable EditTime; updated_at remains null.")
    return {
        "candidate_id": f"zhihu:{content_slug}:{content_id}",
        "query": query,
        "platform": PLATFORM,
        "backend": BACKEND,
        "rank": rank,
        "title": title,
        "url": url,
        "canonical_url": canonical_url,
        "snippet": text_or_none(raw.get("ContentText")),
        "author": text_or_none(raw.get("AuthorName")),
        # EditTime is documented as publish-or-edit time, so it must not be
        # promoted to a verified publication timestamp.
        "published_at": None,
        "content_type": f"zhihu_{content_slug}",
        "language": None,
        "metrics": {
            "likes": integer_or_none(raw.get("VoteUpCount")),
            "comments": integer_or_none(raw.get("CommentCount")),
            "collects": None,
            "shares": None,
            "views": None,
        },
        "access": {"visibility": "authenticated_public", "login_state_used": True},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": f"{source_type}:{content_id}",
            "retrieved_at": retrieved_at,
            "route_reason": "zhihu_cli_search",
        },
        "platform_fields": {
            "zhihu": {
                "content_id": content_id,
                "content_type": source_type,
                "updated_at": updated_at,
                "authority_level": text_or_none(raw.get("AuthorityLevel")),
                "ranking_score": number_or_none(raw.get("RankingScore")),
                "featured_comments": featured_comments(raw.get("CommentInfoList")),
            }
        },
        "limitations": limitations,
    }


def normalize_hot_item(raw: Any, *, rank: int, retrieved_at: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = text_or_none(raw.get("Title"))
    resolved_url = canonicalize_zhihu_url(raw.get("Url"))
    if title is None or resolved_url is None:
        return None
    url, canonical_url = resolved_url
    kind, identifier = infer_hot_identity(canonical_url)
    return {
        "candidate_id": f"zhihu:{kind}:{identifier}",
        "query": HOT_QUERY,
        "platform": PLATFORM,
        "backend": BACKEND,
        "rank": rank,
        "title": title,
        "url": url,
        "canonical_url": canonical_url,
        "snippet": text_or_none(raw.get("Summary")),
        "author": None,
        "published_at": None,
        "content_type": f"zhihu_{kind.replace('-', '_')}",
        "language": None,
        "metrics": {
            "likes": None,
            "comments": None,
            "collects": None,
            "shares": None,
            "views": None,
        },
        "access": {"visibility": "authenticated_public", "login_state_used": True},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": f"{kind}:{identifier}",
            "retrieved_at": retrieved_at,
            "route_reason": "zhihu_cli_hot_list",
        },
        "platform_fields": {"zhihu": {"hot_rank": rank}},
        "limitations": list(HOT_LIMITATIONS),
    }


def _safe_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _api_error(code: int) -> AdapterError:
    category = {
        10001: "invalid_request",
        20001: "authentication_failed",
        30001: "rate_limited",
        90001: "upstream_error",
    }.get(code, "upstream_api_error")
    return AdapterError(category, f"Zhihu returned API error code {code}.")


def parse_cli_json(stdout: Any) -> tuple[dict[str, Any], list[Any]]:
    if not isinstance(stdout, str) or not stdout.strip():
        raise AdapterError("invalid_response", "Zhihu CLI returned no JSON response.")
    if len(stdout.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES:
        raise AdapterError(
            "response_too_large", "Zhihu CLI response exceeded the local safety limit."
        )
    parse_failed = False
    payload: Any = None
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeError):
        parse_failed = True
    if parse_failed or not isinstance(payload, dict):
        raise AdapterError("invalid_response", "Zhihu CLI returned invalid JSON.")

    code = _safe_code(payload.get("Code"))
    if code is None:
        raise AdapterError("invalid_response", "Zhihu response is missing a valid Code.")
    if code != 0:
        raise _api_error(code)
    data = payload.get("Data")
    if not isinstance(data, dict):
        raise AdapterError("invalid_response", "Zhihu response is missing Data.")
    items = data.get("Items")
    if not isinstance(items, list):
        raise AdapterError("invalid_response", "Zhihu response is missing Data.Items.")
    return data, items


def _cli_argv(command: str, *, query: str | None, limit: int, timeout: int) -> list[str]:
    if not ZHIHU_CLI.is_absolute():
        raise AdapterError(
            "configuration_error", "ZHIHU_CLI must identify an absolute executable path."
        )
    if command == "search":
        assert query is not None
        return [
            str(ZHIHU_CLI),
            "search",
            "zhihu",
            "--query",
            query,
            "--count",
            str(limit),
            "--timeout",
            f"{timeout}s",
        ]
    if command == "hot":
        return [
            str(ZHIHU_CLI),
            "hot",
            "--limit",
            str(limit),
            "--timeout",
            f"{timeout}s",
        ]
    raise AdapterError("invalid_command", "Only Zhihu public search and hot are allowed.")


def run_cli(
    command: str, *, query: str | None, limit: int, timeout: int
) -> str:
    child_env = safe_child_environment()
    argv = _cli_argv(command, query=query, limit=limit, timeout=timeout)

    failure: AdapterError | None = None
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 5,
            check=False,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        failure = AdapterError("timeout", "Zhihu CLI timed out.")
    except FileNotFoundError:
        failure = AdapterError(
            "missing_binary", "The configured Zhihu CLI binary is unavailable."
        )
    except (PermissionError, OSError):
        failure = AdapterError(
            "cli_unavailable", "The configured Zhihu CLI binary could not run."
        )
    if failure is not None:
        # Raise after leaving the subprocess exception handler.  This avoids
        # retaining TimeoutExpired/CalledProcessError objects containing argv,
        # stdout, or stderr in an exception chain.
        raise failure
    assert completed is not None
    if completed.returncode != 0:
        raise AdapterError(
            "cli_error", f"Zhihu CLI failed with exit code {completed.returncode}."
        )
    return completed.stdout


def _base_envelope(*, query: str, mode: str, limit: int) -> dict[str, Any]:
    limitations = SEARCH_LIMITATIONS if mode == "search" else HOT_LIMITATIONS
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": [PLATFORM],
            "time_range": None,
            "requested_limit": limit,
        },
        "routes": [
            {
                "platform": PLATFORM,
                "backend": BACKEND,
                "mode": mode,
                "login_state_used": True,
                "status": "completed",
                "limitations": list(limitations),
            }
        ],
        "candidates": [],
        "coverage": [],
        "errors": [],
    }


def error_envelope(
    *, query: str, mode: str, limit: int, error: AdapterError
) -> dict[str, Any]:
    result = _base_envelope(query=query, mode=mode, limit=limit)
    result["routes"][0]["status"] = "failed"
    result["coverage"] = []
    result["errors"] = [
        {"backend": BACKEND, "category": error.category, "message": error.message}
    ]
    return result


def normalize_response(
    *, command: str, query: str, limit: int, stdout: str, now: datetime
) -> dict[str, Any]:
    if command not in {"search", "hot"}:
        raise AdapterError("invalid_command", "Only Zhihu public search and hot are allowed.")
    data, raw_items = parse_cli_json(stdout)
    retrieved_at = iso_z(now)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    rejected_count = 0
    duplicate_count = 0

    for raw in raw_items:
        if command == "search":
            candidate = normalize_search_item(
                raw,
                query=query,
                rank=len(candidates) + 1,
                retrieved_at=retrieved_at,
            )
        else:
            candidate = normalize_hot_item(
                raw,
                rank=len(candidates) + 1,
                retrieved_at=retrieved_at,
            )
        if candidate is None:
            rejected_count += 1
            continue
        candidate_id = candidate["candidate_id"]
        canonical_url = candidate["canonical_url"]
        if candidate_id in seen_ids or canonical_url in seen_urls:
            duplicate_count += 1
            continue
        seen_ids.add(candidate_id)
        seen_urls.add(canonical_url)
        candidates.append(candidate)

    # Rank is the accepted, de-duplicated source order.  Apply the requested
    # bound locally even if an upstream version ever returns too many rows.
    candidates = candidates[:limit]
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
        if command == "hot":
            candidate["platform_fields"]["zhihu"]["hot_rank"] = rank

    result = _base_envelope(query=query, mode=command, limit=limit)
    result["candidates"] = candidates
    limitations = result["routes"][0]["limitations"]
    if rejected_count:
        limitations.append(
            f"{rejected_count} returned item(s) were rejected because required public candidate fields were invalid."
        )
        result["routes"][0]["status"] = "partial" if candidates else "failed"
        result["errors"].append(
            {
                "backend": BACKEND,
                "category": "invalid_candidate",
                "message": "Zhihu returned item(s) that could not be safely normalized.",
            }
        )

    total = integer_or_none(data.get("Total")) if command == "hot" else None
    has_more = data.get("HasMore") is True if command == "search" else False
    result["coverage"] = [
        {
            "platform": PLATFORM,
            "backend": BACKEND,
            "query_count": 1,
            "raw_result_count": len(raw_items),
            "returned_count": len(candidates),
            "rejected_count": rejected_count,
            "duplicate_count": duplicate_count,
            "reported_total": total,
            "truncated": has_more or len(candidates) < len(raw_items) - rejected_count - duplicate_count,
            "login_state_used": True,
            "limitations": list(limitations),
        }
    ]
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = SafeArgumentParser(
        description="Read-only Zhihu CLI public candidate adapter.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser(
        "search", help="Search public Zhihu candidates", allow_abbrev=False
    )
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--timeout", type=int, default=20)

    hot = subparsers.add_parser(
        "hot", help="Read the current public Zhihu hot list", allow_abbrev=False
    )
    hot.add_argument("--limit", type=int, default=30)
    hot.add_argument("--timeout", type=int, default=20)

    args = parser.parse_args(argv)
    if args.command == "search":
        args.query = args.query.strip()
        if not args.query or len(args.query) > 500:
            parser.error("invalid query")
        if not 1 <= args.limit <= SEARCH_LIMIT:
            parser.error("invalid search limit")
    elif not 1 <= args.limit <= HOT_LIMIT:
        parser.error("invalid hot limit")
    if not 1 <= args.timeout <= 120:
        parser.error("invalid timeout")
    return args


def execute(args: argparse.Namespace) -> dict[str, Any]:
    query = args.query if args.command == "search" else HOT_QUERY
    stdout = run_cli(
        args.command,
        query=query if args.command == "search" else None,
        limit=args.limit,
        timeout=args.timeout,
    )
    return normalize_response(
        command=args.command,
        query=query,
        limit=args.limit,
        stdout=stdout,
        now=utc_now(),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query = args.query if args.command == "search" else HOT_QUERY
    try:
        result = execute(args)
    except AdapterError as exc:
        result = error_envelope(
            query=query,
            mode=args.command,
            limit=args.limit,
            error=exc,
        )
        exit_code = 2
    else:
        exit_code = 2 if result["errors"] else 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
