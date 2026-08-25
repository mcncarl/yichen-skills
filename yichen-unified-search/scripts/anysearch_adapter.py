#!/usr/bin/env python3
"""Run AnySearch safely and emit unified-search candidate envelopes.

The upstream AnySearch CLI intentionally returns Markdown.  This adapter keeps
that CLI as the source of truth, reads its configured command from
``runtime.conf``, and normalizes search results without treating parser
failures as successful empty searches.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

try:
    import idna as _idna_uts46
except ImportError:  # Fail closed for non-ASCII hosts when the helper is absent.
    _idna_uts46 = None


BACKEND = "anysearch"
SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = Path(
    os.environ.get("YICHEN_SKILLS_ROOT", str(SKILL_DIR.parent))
).expanduser()
DEFAULT_RUNTIME_CONF = Path(
    os.environ.get(
        "YICHEN_ANYSEARCH_RUNTIME_CONF",
        str(SKILLS_ROOT / "anysearch" / "runtime.conf"),
    )
).expanduser()
RECEIPT_KEY_ENV = "YICHEN_UNIFIED_SEARCH_RECEIPT_KEY"
RECEIPT_KEY_FILE_ENV = "YICHEN_UNIFIED_SEARCH_RECEIPT_KEY_FILE"
DEFAULT_RECEIPT_KEY_FILE = (
    Path.home() / ".config" / "agent-secrets" / "yichen-unified-search-receipt-key"
)
RECEIPT_TTL_SECONDS = 2 * 60 * 60
MIN_RECEIPT_KEY_BYTES = 32
SEARCH_SNIPPET_LIMITATION = (
    "AnySearch result snippets are discovery text, not verified page content."
)
VERIFY_LIMITATION = (
    "Opening the original URL does not by itself verify a factual claim; "
    "verification status remains candidate."
)
ALLOWED_BATCH_KEYS = {
    "query",
    "domain",
    "sub_domain",
    "sub_domain_params",
    "max_results",
}
SEARCH_ROUTE_REASONS = {
    "public_web_default",
    "anysearch_vertical_domain",
    "public_web_batch",
    "anysearch_vertical_domain_batch",
}
SAFE_CHILD_ENV_NAMES = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
        "TZ", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "PATHEXT", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)

SEARCH_HEADER_RE = re.compile(
    r"^##[ \t]+Search Results[ \t]*\([ \t]*(?P<count>\d+)[ \t]+"
    r"results?(?:[ \t]*,[ \t]*(?P<meta>[^)]*))?\)[ \t]*$",
    flags=re.MULTILINE | re.IGNORECASE,
)
RESULT_START_RE = re.compile(
    r"^###[ \t]+(?P<rank>\d+)\.[ \t]+(?P<title>[^\n]+)\n"
    r"(?:[ \t]*\n)*-[ \t]*\*\*URL\*\*:[ \t]*(?P<url>[^\n]+)[ \t]*$",
    flags=re.MULTILINE | re.IGNORECASE,
)
QUERY_SECTION_RE = re.compile(
    r"(?:\A|^---[ \t]*\n(?:[ \t]*\n)*)"
    r"##[ \t]+Query[ \t]+(?P<index>\d+):[ \t]*(?P<query>[^\n]*)$",
    flags=re.MULTILINE | re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(
    r"^\[[^\]]*\]\((?P<url>https?://[^\s)]+)(?:[ \t]+[\"'][^\"']*[\"'])?\)$",
    flags=re.IGNORECASE,
)


class AdapterError(RuntimeError):
    """A public, already-redacted adapter failure."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class ParsedRow:
    rank: int
    title: str
    url: str
    snippet: str | None


@dataclass(frozen=True)
class ParsedSection:
    rows: tuple[ParsedRow, ...]
    reported_count: int | None
    elapsed_ms: int | None
    status: str
    errors: tuple[dict[str, Any], ...]


Runner = Callable[[Path, list[str], int], str]


def safe_child_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Keep only process/runtime settings; credentials require explicit runtime overrides."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name.upper() in SAFE_CHILD_ENV_NAMES
    }


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError("invalid_candidate", f"{label} is required.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise AdapterError("invalid_candidate", f"{label} is invalid.") from None
    if parsed.tzinfo is None:
        raise AdapterError(
            "invalid_candidate", f"{label} needs a timezone."
        )
    return parsed.astimezone(timezone.utc)


def _require_receipt_key(secret: bytes) -> bytes:
    if not isinstance(secret, bytes) or len(secret) < MIN_RECEIPT_KEY_BYTES:
        raise AdapterError(
            "runtime_unavailable",
            "Unified-search receipt key must contain at least 32 bytes.",
        )
    return secret


def _read_secure_receipt_key(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise AdapterError(
            "runtime_unavailable", "Unified-search receipt key could not be read."
        ) from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AdapterError(
                "runtime_unavailable", "Unified-search receipt key is not a regular file."
            )
        if metadata.st_mode & 0o077:
            raise AdapterError(
                "runtime_unavailable",
                "Unified-search receipt key permissions must be 0600 or stricter.",
            )
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise AdapterError(
                "runtime_unavailable",
                "Unified-search receipt key must be owned by the current user.",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            secret = handle.read(4097)
        if len(secret) > 4096:
            raise AdapterError(
                "runtime_unavailable", "Unified-search receipt key file is too large."
            )
        return _require_receipt_key(secret)
    finally:
        os.close(descriptor)


def _ensure_private_key_parent(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise AdapterError(
                "runtime_unavailable",
                "Unified-search receipt key directory is not private.",
            )
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise AdapterError(
                "runtime_unavailable",
                "Unified-search receipt key directory must be owned by the current user.",
            )
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise AdapterError(
                "runtime_unavailable",
                "Unified-search receipt key directory permissions must be 0700.",
            )
    except AdapterError:
        raise
    except OSError:
        raise AdapterError(
            "runtime_unavailable",
            "Unified-search receipt key directory could not be secured.",
        ) from None


def _create_receipt_key(path: Path) -> bytes:
    _ensure_private_key_parent(path.parent)
    secret = secrets.token_bytes(MIN_RECEIPT_KEY_BYTES)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return _read_secure_receipt_key(path)
    except OSError:
        raise AdapterError(
            "runtime_unavailable", "Unified-search receipt key could not be created."
        ) from None
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(descriptor)
        os.chmod(path, 0o600)
    except OSError:
        raise AdapterError(
            "runtime_unavailable", "Unified-search receipt key could not be written."
        ) from None
    finally:
        os.close(descriptor)
    return secret


def load_receipt_secret(
    *,
    key_file: Path | None = None,
    environ: dict[str, str] | None = None,
) -> bytes:
    """Load the receipt HMAC key without exposing it in argv or output."""

    environment = os.environ if environ is None else environ
    inline = environment.get(RECEIPT_KEY_ENV)
    if inline is not None:
        return _require_receipt_key(inline.encode("utf-8"))

    if key_file is None:
        configured = environment.get(RECEIPT_KEY_FILE_ENV)
        if configured:
            key_file = Path(configured).expanduser()
            if not key_file.is_absolute():
                raise AdapterError(
                    "runtime_unavailable",
                    "Unified-search receipt key file path must be absolute.",
                )
        else:
            key_file = DEFAULT_RECEIPT_KEY_FILE
    path = key_file.expanduser()
    try:
        return _read_secure_receipt_key(path)
    except AdapterError as exc:
        if path.exists() or path.is_symlink():
            raise exc
    return _create_receipt_key(path)


def _normalize_host_uts46(raw_host: str) -> str:
    """Normalize one URL host without falling back to legacy IDNA2003."""

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


def validate_public_http_url(value: Any) -> str:
    """Return a public HTTP(S) URL, without DNS resolution."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("URL is missing")
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

    try:
        host = _normalize_host_uts46(hostname)
    except ValueError:
        raise ValueError("URL host is malformed") from None
    if not host or len(host) > 253:
        raise ValueError("URL host is malformed")
    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
    ):
        raise ValueError("URL does not identify a public host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("URL does not identify a public host")
    if address is None:
        if "." not in host:
            raise ValueError("URL host is not a fully qualified public name")
        labels = host.split(".")
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
            raise ValueError("URL contains an ambiguous numeric host")
        if any(
            re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label
            )
            is None
            for label in labels
        ):
            raise ValueError("URL host is malformed")
    return cleaned


def _parse_elapsed_ms(meta: str | None) -> int | None:
    if not meta:
        return None
    match = re.search(r"(?<!\d)(\d+)[ \t]*ms\b", meta, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _public_error(category: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"category": category, "message": message}
    for key, value in details.items():
        if value is not None:
            result[key] = value
    return result


def _clean_snippet(raw: str) -> str | None:
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and (not lines[-1].strip() or lines[-1].strip() == "---"):
        lines.pop()
    if lines and lines[0].startswith("- "):
        lines[0] = lines[0][2:]
    value = "\n".join(lines).strip()
    return value or None


def _clean_url(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    else:
        link = MARKDOWN_LINK_RE.fullmatch(value)
        if link:
            value = link.group("url")
    return validate_public_http_url(value)


def _candidate_id(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"web:{digest}"


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _receipt_payload(
    candidate: dict[str, Any], *, run_id: str, expires_at: str
) -> bytes:
    provenance = candidate.get("provenance")
    retrieved_at = provenance.get("retrieved_at") if isinstance(provenance, dict) else None
    payload = {
        "version": 1,
        "run_id": run_id,
        "candidate_id": candidate.get("candidate_id"),
        "url": candidate.get("url"),
        "query": candidate.get("query"),
        "retrieved_at": retrieved_at,
        "expires_at": expires_at,
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _receipt_signature(
    candidate: dict[str, Any], *, run_id: str, expires_at: str, secret: bytes
) -> str:
    digest = hmac.new(
        _require_receipt_key(secret),
        _receipt_payload(candidate, run_id=run_id, expires_at=expires_at),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def issue_candidate_receipt(
    candidate: dict[str, Any],
    *,
    secret: bytes,
    run_id: str,
) -> None:
    """Attach one signed, short-lived receipt to a search-produced candidate."""

    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise AdapterError("internal_error", "Search receipt run ID is invalid.")
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict):
        raise AdapterError("internal_error", "Candidate provenance is missing.")
    retrieved_at = _parse_timestamp(
        provenance.get("retrieved_at"), label="Candidate retrieval timestamp"
    )
    expires_at = _format_timestamp(
        retrieved_at + timedelta(seconds=RECEIPT_TTL_SECONDS)
    )
    provenance["anysearch_receipt"] = {
        "version": 1,
        "run_id": run_id,
        "expires_at": expires_at,
        "signature": _receipt_signature(
            candidate, run_id=run_id, expires_at=expires_at, secret=secret
        ),
    }


def _issue_envelope_receipts(
    envelope: dict[str, Any], *, receipt_secret: bytes | None
) -> dict[str, Any]:
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return envelope
    secret = load_receipt_secret() if receipt_secret is None else receipt_secret
    _require_receipt_key(secret)
    run_id = secrets.token_hex(16)
    for candidate in candidates:
        issue_candidate_receipt(candidate, secret=secret, run_id=run_id)
    return envelope


def parse_search_section(markdown: str) -> ParsedSection:
    """Parse one documented AnySearch ``Search Results`` Markdown section.

    This function is deliberately pure.  A documented, explicit zero-result
    header is the only route to a successful empty section.  Missing headers,
    count mismatches, or invalid result blocks always produce parse errors.
    """

    text = (
        markdown.replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
        .lstrip("\ufeff")
    )
    if not text:
        return ParsedSection(
            rows=(),
            reported_count=None,
            elapsed_ms=None,
            status="failed",
            errors=(
                _public_error(
                    "parse_error",
                    "AnySearch returned an empty response instead of search-result Markdown.",
                ),
            ),
        )

    header = SEARCH_HEADER_RE.match(text)
    if header is None:
        return ParsedSection(
            rows=(),
            reported_count=None,
            elapsed_ms=None,
            status="failed",
            errors=(
                _public_error(
                    "parse_error",
                    "AnySearch output did not begin with the documented search-results header.",
                ),
            ),
        )

    reported_count = int(header.group("count"))
    elapsed_ms = _parse_elapsed_ms(header.group("meta"))
    starts = list(RESULT_START_RE.finditer(text, header.end()))
    rows: list[ParsedRow] = []
    errors: list[dict[str, Any]] = []

    if reported_count == 0:
        remainder = text[header.end() :].strip()
        if remainder not in {"", "---"}:
            errors.append(
                _public_error(
                    "parse_error",
                    "AnySearch returned unexpected content after a zero-results header.",
                )
            )

    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        try:
            url = _clean_url(match.group("url"))
        except ValueError:
            errors.append(
                _public_error(
                    "parse_error",
                    "An AnySearch result block contained an invalid URL.",
                    result_rank=int(match.group("rank")),
                )
            )
            continue
        title = match.group("title").strip()
        if not title:
            errors.append(
                _public_error(
                    "parse_error",
                    "An AnySearch result block was missing its title.",
                    result_rank=int(match.group("rank")),
                )
            )
            continue
        rows.append(
            ParsedRow(
                rank=int(match.group("rank")),
                title=title,
                url=url,
                snippet=_clean_snippet(text[match.end() : end]),
            )
        )

    if reported_count != len(starts):
        errors.append(
            _public_error(
                "parse_error",
                "AnySearch's reported result count did not match its parseable result blocks.",
                backend_reported_count=reported_count,
                parseable_block_count=len(starts),
            )
        )
    if len(rows) != len(starts):
        errors.append(
            _public_error(
                "parse_error",
                "One or more AnySearch result blocks could not be normalized.",
                parseable_block_count=len(starts),
                normalized_count=len(rows),
            )
        )

    if errors:
        status = "partial" if rows else "failed"
    else:
        status = "completed"
    return ParsedSection(
        rows=tuple(rows),
        reported_count=reported_count,
        elapsed_ms=elapsed_ms,
        status=status,
        errors=tuple(errors),
    )


def make_candidate(
    row: ParsedRow,
    *,
    query: str,
    retrieved_at: str,
    route_reason: str,
) -> dict[str, Any]:
    return {
        "candidate_id": _candidate_id(row.url),
        "query": query,
        "platform": "web",
        "backend": BACKEND,
        "rank": row.rank,
        "title": row.title,
        "url": row.url,
        "canonical_url": row.url,
        "snippet": row.snippet,
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
            "retrieved_at": retrieved_at,
            "route_reason": route_reason,
        },
        "limitations": [SEARCH_SNIPPET_LIMITATION],
    }


def _route(
    *, mode: str, status: str, reason: str, limitations: Iterable[str]
) -> dict[str, Any]:
    return {
        "platform": "web",
        "backend": BACKEND,
        "mode": mode,
        "reason": reason,
        "login_state_used": False,
        "status": status,
        "limitations": list(limitations),
    }


def normalize_search_markdown(
    markdown: str,
    *,
    query: str,
    requested_limit: int,
    retrieved_at: str,
    route_reason: str = "public_web_default",
    receipt_secret: bytes | None = None,
) -> dict[str, Any]:
    """Normalize one AnySearch search response into the candidate envelope."""

    section = parse_search_section(markdown)
    all_candidates = [
        make_candidate(
            row,
            query=query,
            retrieved_at=retrieved_at,
            route_reason=route_reason,
        )
        for row in section.rows
    ]
    candidates = all_candidates[:requested_limit]
    truncated = len(all_candidates) > len(candidates) or (
        section.reported_count is not None
        and section.reported_count > requested_limit
    )
    limitations = [SEARCH_SNIPPET_LIMITATION]
    coverage = {
        "backend": BACKEND,
        "mode": "search",
        "query_count": 1,
        "returned_count": len(candidates),
        "backend_reported_count": section.reported_count,
        "truncated": truncated,
        "login_state_used": False,
        "parse_status": section.status,
        "limitations": limitations,
    }
    if section.elapsed_ms is not None:
        coverage["elapsed_ms"] = section.elapsed_ms
    envelope = {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": requested_limit,
        },
        "routes": [
            _route(
                mode="search",
                status=section.status,
                reason=route_reason,
                limitations=limitations,
            )
        ],
        "candidates": candidates,
        "coverage": [coverage],
        "errors": list(section.errors),
    }
    return _issue_envelope_receipts(envelope, receipt_secret=receipt_secret)


def _query_requested_limit(query_item: dict[str, Any]) -> int:
    value = query_item.get("max_results", 10)
    return value if isinstance(value, int) and not isinstance(value, bool) else 10


def normalize_batch_markdown(
    markdown: str,
    *,
    query_items: list[dict[str, Any]],
    retrieved_at: str,
    receipt_secret: bytes | None = None,
) -> dict[str, Any]:
    """Normalize AnySearch's numbered batch Markdown using submitted queries.

    Query headings are used only to associate a numbered response section with
    its submitted item.  The original submitted query remains authoritative in
    each candidate and in coverage.
    """

    text = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    headings = list(QUERY_SECTION_RE.finditer(text)) if text else []
    section_by_index: dict[int, tuple[str, str]] = {}
    global_errors: list[dict[str, Any]] = []
    observed_indices = [int(heading.group("index")) for heading in headings]
    expected_indices = list(range(1, len(query_items) + 1))
    index_counts: dict[int, int] = {}
    for index in observed_indices:
        index_counts[index] = index_counts.get(index, 0) + 1
    duplicated_indices = {
        index for index, count in index_counts.items() if count > 1
    }

    for index in sorted(duplicated_indices):
        global_errors.append(
            _public_error(
                "parse_error",
                "AnySearch batch output repeated a query section number; all sections with that number were discarded.",
                query_index=index,
            )
        )

    if headings and observed_indices != expected_indices:
        global_errors.append(
            _public_error(
                "parse_error",
                "AnySearch batch output must contain exactly one ordered section for each submitted query.",
                expected_query_count=len(query_items),
                observed_section_count=len(headings),
            )
        )

    for position, heading in enumerate(headings, start=1):
        index = int(heading.group("index"))
        offset = position - 1
        end = headings[offset + 1].start() if offset + 1 < len(headings) else len(text)
        if (
            index in duplicated_indices
            or index not in expected_indices
            or position != index
        ):
            continue
        if index in section_by_index:
            global_errors.append(
                _public_error(
                    "parse_error",
                    "AnySearch batch output repeated a query section number; all sections with that number were discarded.",
                    query_index=index,
                )
            )
            section_by_index.pop(index, None)
            continue
        section_by_index[index] = (
            heading.group("query").strip(),
            text[heading.end() : end],
        )

    if not headings:
        global_errors.append(
            _public_error(
                "parse_error",
                "AnySearch batch output did not contain documented numbered query sections.",
            )
        )

    candidates: list[dict[str, Any]] = []
    per_query: list[dict[str, Any]] = []
    section_statuses: list[str] = []
    errors = list(global_errors)
    total_reported = 0
    all_reported_known = True
    any_truncated = False

    for index, query_item in enumerate(query_items, start=1):
        query = query_item["query"]
        response_section = section_by_index.get(index)
        requested_limit = _query_requested_limit(query_item)
        route_reason = (
            "anysearch_vertical_domain_batch"
            if query_item.get("domain")
            else "public_web_batch"
        )
        if response_section is None:
            section = ParsedSection(
                rows=(),
                reported_count=None,
                elapsed_ms=None,
                status="failed",
                errors=(
                    _public_error(
                        "parse_error",
                        "AnySearch batch output was missing a submitted query section.",
                        query_index=index,
                    ),
                ),
            )
            response_query = None
        else:
            response_query, raw_section = response_section
            section = parse_search_section(raw_section)

        query_candidates = [
            make_candidate(
                row,
                query=query,
                retrieved_at=retrieved_at,
                route_reason=route_reason,
            )
            for row in section.rows
        ]
        emitted = query_candidates[:requested_limit]
        candidates.extend(emitted)
        truncated = len(query_candidates) > len(emitted) or (
            section.reported_count is not None
            and section.reported_count > requested_limit
        )
        any_truncated = any_truncated or truncated
        if section.reported_count is None:
            all_reported_known = False
        else:
            total_reported += section.reported_count

        for error in section.errors:
            enriched = dict(error)
            enriched.setdefault("query_index", index)
            errors.append(enriched)
        section_statuses.append(section.status)
        query_coverage: dict[str, Any] = {
            "query": query,
            "query_index": index,
            "response_query": response_query,
            "returned_count": len(emitted),
            "backend_reported_count": section.reported_count,
            "requested_limit": requested_limit,
            "truncated": truncated,
            "parse_status": section.status,
        }
        if section.elapsed_ms is not None:
            query_coverage["elapsed_ms"] = section.elapsed_ms
        per_query.append(query_coverage)

    extra_indices = sorted(set(observed_indices) - set(expected_indices))
    for index in extra_indices:
        errors.append(
            _public_error(
                "parse_error",
                "AnySearch batch output contained an unexpected query section.",
                query_index=index,
            )
        )

    if not section_statuses or all(status == "failed" for status in section_statuses):
        route_status = "failed"
    elif (
        all(status == "completed" for status in section_statuses)
        and not global_errors
        and not extra_indices
    ):
        route_status = "completed"
    else:
        route_status = "partial"

    requested_limits = [_query_requested_limit(item) for item in query_items]
    common_limit = (
        requested_limits[0]
        if requested_limits and len(set(requested_limits)) == 1
        else None
    )
    limitations = [SEARCH_SNIPPET_LIMITATION]
    coverage = {
        "backend": BACKEND,
        "mode": "batch",
        "query_count": len(query_items),
        "returned_count": len(candidates),
        "backend_reported_count": total_reported if all_reported_known else None,
        "truncated": any_truncated,
        "login_state_used": False,
        "parse_status": route_status,
        "per_query": per_query,
        "limitations": limitations,
    }
    envelope = {
        "schema_version": "1.0",
        "request": {
            "queries": [item["query"] for item in query_items],
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": common_limit,
        },
        "routes": [
            _route(
                mode="batch",
                status=route_status,
                reason="anysearch_batch",
                limitations=limitations,
            )
        ],
        "candidates": candidates,
        "coverage": [coverage],
        "errors": errors,
    }
    return _issue_envelope_receipts(envelope, receipt_secret=receipt_secret)


def _validate_candidate_url(url: Any) -> str:
    try:
        return validate_public_http_url(url)
    except ValueError:
        raise AdapterError(
            "invalid_candidate", "Candidate URL must use public HTTP(S)."
        ) from None


def _validate_search_receipt(
    candidate: dict[str, Any],
    *,
    secret: bytes,
    retrieved_at: datetime,
    now: datetime | None,
) -> None:
    provenance = candidate.get("provenance")
    receipt = provenance.get("anysearch_receipt") if isinstance(provenance, dict) else None
    required_keys = {"version", "run_id", "expires_at", "signature"}
    if not isinstance(receipt, dict) or set(receipt) != required_keys:
        raise AdapterError(
            "invalid_candidate",
            "Candidate is missing a valid current-search receipt.",
        )
    if receipt.get("version") != 1:
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt version is invalid."
        )
    run_id = receipt.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt run ID is invalid."
        )
    expires_at_raw = receipt.get("expires_at")
    expires_at = _parse_timestamp(
        expires_at_raw, label="Candidate search receipt expiration"
    )
    if expires_at <= retrieved_at or expires_at > retrieved_at + timedelta(
        seconds=RECEIPT_TTL_SECONDS
    ):
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt lifetime is invalid."
        )
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise AdapterError(
            "invalid_candidate", "Candidate verification time needs a timezone."
        )
    if current.astimezone(timezone.utc) >= expires_at:
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt has expired."
        )
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", signature
    ):
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt signature is invalid."
        )
    expected = _receipt_signature(
        candidate,
        run_id=run_id,
        expires_at=expires_at_raw,
        secret=secret,
    )
    if not hmac.compare_digest(signature, expected):
        raise AdapterError(
            "invalid_candidate", "Candidate search receipt signature is invalid."
        )


def validate_candidate_from_search(
    candidate: Any,
    *,
    receipt_secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise AdapterError(
            "invalid_candidate", "--candidate-from-search must contain one candidate object."
        )
    if candidate.get("backend") != BACKEND:
        raise AdapterError(
            "invalid_candidate", "Candidate backend must be anysearch."
        )
    for field in ("candidate_id", "query"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            raise AdapterError(
                "invalid_candidate", f"Candidate field {field} is required."
            )
    if candidate.get("platform") != "web":
        raise AdapterError(
            "invalid_candidate", "AnySearch candidate platform must be web."
        )
    if (
        isinstance(candidate.get("rank"), bool)
        or not isinstance(candidate.get("rank"), int)
        or candidate["rank"] < 1
    ):
        raise AdapterError(
            "invalid_candidate", "Candidate rank must be a positive integer."
        )
    if not isinstance(candidate.get("title"), str) or not candidate["title"].strip():
        raise AdapterError("invalid_candidate", "Candidate title is required.")
    verification = candidate.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "candidate":
        raise AdapterError(
            "invalid_candidate", "Candidate verification status must be candidate."
        )
    if verification.get("opened_original") is not False or verification.get(
        "checked_at"
    ) is not None:
        raise AdapterError(
            "invalid_candidate",
            "Candidate must be an unopened current-search result.",
        )
    url = _validate_candidate_url(candidate.get("url"))
    if candidate.get("canonical_url") != url:
        raise AdapterError(
            "invalid_candidate", "Candidate canonical URL must match its search URL."
        )
    if candidate["candidate_id"] != _candidate_id(url):
        raise AdapterError(
            "invalid_candidate", "Candidate ID does not match its search URL."
        )
    access = candidate.get("access")
    if not isinstance(access, dict) or access.get("visibility") != "public":
        raise AdapterError(
            "invalid_candidate", "AnySearch candidate access must be public."
        )
    if access.get("login_state_used") is not False:
        raise AdapterError(
            "invalid_candidate", "AnySearch candidate must not use login state."
        )
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict) or provenance.get(
        "route_reason"
    ) not in SEARCH_ROUTE_REASONS:
        raise AdapterError(
            "invalid_candidate", "Candidate search provenance is missing or invalid."
        )
    parsed_retrieved_at = _parse_timestamp(
        provenance.get("retrieved_at"), label="Candidate retrieval timestamp"
    )
    secret = load_receipt_secret() if receipt_secret is None else receipt_secret
    _validate_search_receipt(
        candidate,
        secret=_require_receipt_key(secret),
        retrieved_at=parsed_retrieved_at,
        now=now,
    )
    return candidate


def normalize_verified_candidate(
    candidate: dict[str, Any],
    *,
    extract_markdown: str,
    checked_at: str,
    receipt_secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach extract Markdown while deliberately retaining candidate status."""

    validate_candidate_from_search(
        candidate, receipt_secret=receipt_secret, now=now
    )
    markdown = extract_markdown.strip()
    if not markdown:
        raise AdapterError(
            "invalid_response", "AnySearch extract returned no Markdown content."
        )

    normalized = copy.deepcopy(candidate)
    normalized["verification"] = dict(normalized.get("verification") or {})
    normalized["verification"].update(
        {
            "status": "candidate",
            "opened_original": True,
            "checked_at": checked_at,
        }
    )

    platform_fields = normalized.get("platform_fields")
    if not isinstance(platform_fields, dict):
        platform_fields = {}
    else:
        platform_fields = copy.deepcopy(platform_fields)
    prior_anysearch = platform_fields.get("anysearch")
    if isinstance(prior_anysearch, dict):
        anysearch_fields = copy.deepcopy(prior_anysearch)
    elif prior_anysearch is None:
        anysearch_fields = {}
    else:
        anysearch_fields = {"prior_value": prior_anysearch}
    anysearch_fields.update(
        {
            "extract_markdown": markdown,
            "extract_retrieved_at": checked_at,
        }
    )
    platform_fields["anysearch"] = anysearch_fields
    normalized["platform_fields"] = platform_fields

    provenance = normalized.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    else:
        provenance = copy.deepcopy(provenance)
    provenance["verification"] = {
        "backend": BACKEND,
        "route_reason": "verify_candidate_from_current_search",
        "source_query": normalized["query"],
        "candidate_id": normalized["candidate_id"],
        "checked_at": checked_at,
    }
    normalized["provenance"] = provenance

    limitations = normalized.get("limitations")
    limitations = list(limitations) if isinstance(limitations, list) else []
    if VERIFY_LIMITATION not in limitations:
        limitations.append(VERIFY_LIMITATION)
    normalized["limitations"] = limitations
    return normalized


def verification_envelope(
    candidate: dict[str, Any],
    *,
    extract_markdown: str,
    checked_at: str,
    receipt_secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = normalize_verified_candidate(
        candidate,
        extract_markdown=extract_markdown,
        checked_at=checked_at,
        receipt_secret=receipt_secret,
        now=now,
    )
    query = normalized["query"]
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": [normalized.get("platform") or "web"],
            "time_range": None,
            "requested_limit": 1,
        },
        "routes": [
            _route(
                mode="verify",
                status="completed",
                reason="verify_candidate_from_current_search",
                limitations=[VERIFY_LIMITATION],
            )
        ],
        "candidates": [normalized],
        "coverage": [
            {
                "backend": BACKEND,
                "mode": "verify",
                "query_count": 1,
                "returned_count": 1,
                "opened_count": 1,
                "truncated": False,
                "login_state_used": False,
                "limitations": [VERIFY_LIMITATION],
            }
        ],
        "errors": [],
    }


def read_runtime_command(runtime_conf: Path) -> list[str]:
    """Read and split the configured AnySearch command without evaluating it."""

    try:
        text = runtime_conf.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AdapterError(
            "runtime_unavailable", "AnySearch runtime configuration could not be read."
        ) from exc
    command_values = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.split(":", 1)[0].strip().lower() == "command" and ":" in line
    ]
    command_values = [value for value in command_values if value]
    if len(command_values) != 1:
        raise AdapterError(
            "runtime_unavailable",
            "AnySearch runtime configuration must contain exactly one Command value.",
        )
    try:
        command = shlex.split(command_values[0], posix=True)
    except ValueError as exc:
        raise AdapterError(
            "runtime_unavailable", "AnySearch Command could not be parsed safely."
        ) from exc
    if not command or any("\x00" in token for token in command):
        raise AdapterError(
            "runtime_unavailable", "AnySearch Command is empty or invalid."
        )
    return command


def prepare_runtime_invocation(
    command: list[str],
) -> tuple[list[str], dict[str, str] | None]:
    """Move ``env KEY=value`` prefixes out of process argv.

    ``runtime.conf`` is trusted configuration, but its values must not become
    visible in a child command line or in ``TimeoutExpired.cmd``.  The standard
    ``env`` prefix used by the AnySearch skill is therefore represented through
    ``subprocess``'s environment mapping instead.
    """

    argv = list(command)
    child_env = safe_child_environment()
    if Path(argv[0]).name == "env":
        overrides: dict[str, str] = {}
        index = 1
        while index < len(argv):
            token = argv[index]
            if token.startswith("-"):
                raise AdapterError(
                    "runtime_unavailable",
                    "AnySearch Command uses unsupported env options.",
                )
            name, separator, value = token.partition("=")
            if not separator:
                break
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise AdapterError(
                    "runtime_unavailable",
                    "AnySearch Command contains an invalid environment assignment.",
                )
            overrides[name] = value
            index += 1
        argv = argv[index:]
        if not argv:
            raise AdapterError(
                "runtime_unavailable", "AnySearch Command has no executable."
            )
        if overrides:
            child_env.update(overrides)

    lowered = [token.casefold() for token in argv]
    for index, token in enumerate(lowered):
        if token in {"--api_key", "--api-key"} or token.startswith(
            ("--api_key=", "--api-key=")
        ):
            raise AdapterError(
                "runtime_unavailable",
                "AnySearch credentials must be provided through the environment, not Command argv.",
            )
        if index == 0 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
            raise AdapterError(
                "runtime_unavailable",
                "AnySearch environment assignments require an env prefix.",
            )
    return argv, child_env


def _failure_category(stdout: str, stderr: str) -> tuple[str, str]:
    """Classify captured output while returning only fixed, redacted messages."""

    signal = f"{stdout}\n{stderr}".casefold()
    if any(token in signal for token in ("429", "quota", "rate limit", "exhaust")):
        return "rate_limited", "AnySearch quota or rate limit prevented the request."
    if any(token in signal for token in ("401", "unauthorized", "authentication")):
        return "authentication_error", "AnySearch authentication failed."
    if any(
        token in signal
        for token in ("connection error", "unable to reach", "name resolution", "network")
    ):
        return "network_error", "AnySearch could not be reached."
    if "timeout" in signal or "timed out" in signal:
        return "timeout", "AnySearch did not respond before the timeout."
    return "upstream_error", "AnySearch returned an unsuccessful response."


def run_anysearch(runtime_conf: Path, argv: list[str], timeout: int) -> str:
    """Execute the configured CLI as argv, capturing all potentially sensitive text."""

    command, child_env = prepare_runtime_invocation(
        read_runtime_command(runtime_conf)
    )
    child_env.pop(RECEIPT_KEY_ENV, None)
    child_env.pop(RECEIPT_KEY_FILE_ENV, None)
    failure: tuple[str, str] | None = None
    result: subprocess.CompletedProcess[str] | None = None
    try:
        result = subprocess.run(
            [*command, *argv],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        failure = ("timeout", "AnySearch did not respond before the timeout.")
    except (OSError, ValueError):
        failure = (
            "runtime_unavailable",
            "AnySearch runtime could not be started.",
        )
    if failure is not None:
        raise AdapterError(*failure)
    if result is None:
        raise AdapterError(
            "runtime_unavailable", "AnySearch runtime did not return a result."
        )
    if result.returncode != 0:
        category, message = _failure_category(result.stdout, result.stderr)
        raise AdapterError(category, message)
    return result.stdout


def _read_json_argument(value: str, *, label: str) -> Any:
    raw = value
    if value.startswith("@"):
        path_text = value[1:]
        if not path_text:
            raise AdapterError("invalid_input", f"{label} file path is missing.")
        path = Path(path_text).expanduser()
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise AdapterError("invalid_input", f"{label} file is too large.")
            raw = path.read_text(encoding="utf-8-sig")
        except AdapterError:
            raise
        except OSError as exc:
            raise AdapterError("invalid_input", f"{label} file could not be read.") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdapterError("invalid_input", f"{label} must be valid JSON.") from exc


def parse_batch_queries(value: str) -> list[dict[str, Any]]:
    payload = _read_json_argument(value, label="Batch queries")
    if not isinstance(payload, list) or not 1 <= len(payload) <= 5:
        raise AdapterError(
            "invalid_input", "Batch queries must be a JSON list containing 1 to 5 items."
        )
    queries: list[dict[str, Any]] = []
    for index, raw_item in enumerate(payload, start=1):
        if isinstance(raw_item, str):
            item: dict[str, Any] = {"query": raw_item}
        elif isinstance(raw_item, dict):
            item = copy.deepcopy(raw_item)
        else:
            raise AdapterError(
                "invalid_input", f"Batch query item {index} must be an object or string."
            )
        unknown = set(item) - ALLOWED_BATCH_KEYS
        if unknown:
            raise AdapterError(
                "invalid_input", f"Batch query item {index} contains unsupported fields."
            )
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise AdapterError(
                "invalid_input", f"Batch query item {index} requires a query string."
            )
        if "max_results" in item and (
            isinstance(item["max_results"], bool)
            or not isinstance(item["max_results"], int)
            or not 1 <= item["max_results"] <= 10
        ):
            raise AdapterError(
                "invalid_input", f"Batch query item {index} max_results must be 1 to 10."
            )
        for field in ("domain", "sub_domain"):
            if field in item and (
                not isinstance(item[field], str) or not item[field].strip()
            ):
                raise AdapterError(
                    "invalid_input", f"Batch query item {index} {field} must be a string."
                )
        if "sub_domain_params" in item and not isinstance(
            item["sub_domain_params"], dict
        ):
            raise AdapterError(
                "invalid_input",
                f"Batch query item {index} sub_domain_params must be an object.",
            )
        queries.append(item)
    return queries


def load_candidate_argument(
    value: str,
    *,
    receipt_secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    candidate = _read_json_argument(value, label="Candidate")
    return validate_candidate_from_search(
        candidate, receipt_secret=receipt_secret, now=now
    )


def _validate_sub_domain_params(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AdapterError(
            "invalid_input", "--sub-domain-params must be valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise AdapterError(
            "invalid_input", "--sub-domain-params must contain a JSON object."
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def error_envelope(
    *,
    queries: list[str],
    mode: str,
    category: str,
    message: str,
    requested_limit: int | None,
    route_reason: str | None = None,
) -> dict[str, Any]:
    reason = route_reason or {
        "search": "public_web_default",
        "batch": "anysearch_batch",
        "verify": "verify_candidate_from_current_search",
    }.get(mode, "anysearch_adapter")
    limitations = [SEARCH_SNIPPET_LIMITATION] if mode != "verify" else [VERIFY_LIMITATION]
    return {
        "schema_version": "1.0",
        "request": {
            "queries": queries,
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": requested_limit,
        },
        "routes": [
            _route(
                mode=mode,
                status="failed",
                reason=reason,
                limitations=limitations,
            )
        ],
        "candidates": [],
        "coverage": [
            {
                "backend": BACKEND,
                "mode": mode,
                "query_count": len(queries),
                "returned_count": 0,
                "truncated": False,
                "login_state_used": False,
                "parse_status": "failed",
                "limitations": limitations,
            }
        ],
        "errors": [_public_error(category, message)],
    }


def execute(
    args: argparse.Namespace,
    runner: Runner = run_anysearch,
    *,
    receipt_secret: bytes | None = None,
) -> dict[str, Any]:
    runtime_conf = Path(args.runtime_conf).expanduser()
    if not runtime_conf.is_absolute():
        raise AdapterError(
            "configuration_error",
            "AnySearch runtime configuration path must be absolute.",
        )
    if args.command == "search":
        route_reason = (
            "anysearch_vertical_domain" if args.domain else "public_web_default"
        )
        argv = ["search", args.query, "--max_results", str(args.limit)]
        if args.domain:
            argv.extend(["--domain", args.domain])
        if args.sub_domain:
            argv.extend(["--sub_domain", args.sub_domain])
        params = _validate_sub_domain_params(args.sub_domain_params)
        if params is not None:
            argv.extend(["--sub_domain_params", params])
        markdown = runner(runtime_conf, argv, args.timeout)
        return normalize_search_markdown(
            markdown,
            query=args.query,
            requested_limit=args.limit,
            retrieved_at=utc_now_iso(),
            route_reason=route_reason,
            receipt_secret=receipt_secret,
        )

    if args.command == "batch":
        query_items = parse_batch_queries(args.queries)
        payload = json.dumps(query_items, ensure_ascii=False, separators=(",", ":"))
        markdown = runner(
            runtime_conf, ["batch_search", "--queries", payload], args.timeout
        )
        return normalize_batch_markdown(
            markdown,
            query_items=query_items,
            retrieved_at=utc_now_iso(),
            receipt_secret=receipt_secret,
        )

    if args.command == "verify":
        secret = load_receipt_secret() if receipt_secret is None else receipt_secret
        candidate = load_candidate_argument(
            args.candidate_from_search, receipt_secret=secret
        )
        markdown = runner(runtime_conf, ["extract", candidate["url"]], args.timeout)
        return verification_envelope(
            candidate,
            extract_markdown=markdown,
            checked_at=utc_now_iso(),
            receipt_secret=secret,
        )

    raise AdapterError("invalid_input", "Unsupported adapter command.")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--runtime-conf",
        default=str(DEFAULT_RUNTIME_CONF),
        help="AnySearch runtime.conf path.",
    )
    common.add_argument("--timeout", type=int, default=45)

    parser = argparse.ArgumentParser(
        description="Run AnySearch and emit unified-search candidate JSON."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", parents=[common])
    search.add_argument("query")
    search.add_argument(
        "--limit", "--max-results", "--max_results", dest="limit", type=int, default=10
    )
    search.add_argument("--domain")
    search.add_argument("--sub-domain", "--sub_domain", dest="sub_domain")
    search.add_argument(
        "--sub-domain-params",
        "--sub_domain_params",
        dest="sub_domain_params",
    )

    batch = subparsers.add_parser("batch", parents=[common])
    batch.add_argument("--queries", required=True)

    verify = subparsers.add_parser("verify", parents=[common])
    verify.add_argument(
        "--candidate-from-search",
        required=True,
        help="One current-search AnySearch candidate as JSON, or @file.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120")
    if args.command == "search":
        if not args.query.strip():
            parser.error("query must not be empty")
        if not 1 <= args.limit <= 10:
            parser.error("--limit must be between 1 and 10")
        if (args.sub_domain or args.sub_domain_params) and not args.domain:
            parser.error("--sub-domain and --sub-domain-params require --domain")
    return args


def _request_context(args: argparse.Namespace) -> tuple[list[str], int | None]:
    if args.command == "search":
        return [args.query], args.limit
    if args.command == "batch":
        try:
            items = parse_batch_queries(args.queries)
        except AdapterError:
            return [], None
        limits = [_query_requested_limit(item) for item in items]
        common = limits[0] if limits and len(set(limits)) == 1 else None
        return [item["query"] for item in items], common
    if args.command == "verify":
        try:
            candidate = load_candidate_argument(args.candidate_from_search)
        except AdapterError:
            return [], 1
        return [candidate["query"]], 1
    return [], None


def _route_reason_for_args(args: argparse.Namespace) -> str:
    if args.command == "search":
        return "anysearch_vertical_domain" if args.domain else "public_web_default"
    if args.command == "batch":
        return "anysearch_batch"
    if args.command == "verify":
        return "verify_candidate_from_current_search"
    return "anysearch_adapter"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = execute(args)
    except AdapterError as exc:
        queries, requested_limit = _request_context(args)
        result = error_envelope(
            queries=queries,
            mode=args.command,
            category=exc.category,
            message=exc.message,
            requested_limit=requested_limit,
            route_reason=_route_reason_for_args(args),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except Exception:
        queries, requested_limit = _request_context(args)
        result = error_envelope(
            queries=queries,
            mode=args.command,
            category="internal_error",
            message="The AnySearch adapter failed without exposing captured runtime output.",
            requested_limit=requested_limit,
            route_reason=_route_reason_for_args(args),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["routes"][0]["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
