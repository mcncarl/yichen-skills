#!/usr/bin/env python3
"""Explicit, bounded Firecrawl Map and current-candidate Scrape adapter."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import ipaddress
import json
import os
import posixpath
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import unquote, urlsplit, urlunsplit

try:
    import idna as _idna_uts46
except ImportError:  # Fail closed for non-ASCII hosts when the helper is absent.
    _idna_uts46 = None


BACKEND = "firecrawl"
MAP_ENDPOINT = "https://api.firecrawl.dev/v2/map"
SCRAPE_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"
API_KEY_ENV = "FIRECRAWL_API_KEY"  # pragma: allowlist secret
API_KEY_FILE_ENV = "FIRECRAWL_KEY_FILE"  # pragma: allowlist secret
DEFAULT_API_KEY_FILE = Path.home() / ".config" / "agent-secrets" / "firecrawl-api-key"
MAX_MAP_LIMIT = 100
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAP_LIMITATION = (
    "Firecrawl Map is an explicit, bounded site-link discovery pass, not a general "
    "web search or proof of exhaustive coverage."
)
SCRAPE_LIMITATION = (
    "Firecrawl opened the current AnySearch candidate, but opening a page alone does "
    "not verify a factual claim; verification status remains candidate."
)


class AdapterError(RuntimeError):
    """A fixed, public error that contains no credential or raw response body."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


def _load_anysearch_adapter() -> Any:
    module_path = Path(__file__).resolve().with_name("anysearch_adapter.py")
    module_name = "_yichen_unified_search_anysearch_adapter"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AdapterError(
            "runtime_unavailable", "AnySearch receipt validator could not be loaded."
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise AdapterError(
            "runtime_unavailable", "AnySearch receipt validator could not be loaded."
        ) from None
    return module


def utc_now_iso(now: datetime | None = None) -> str:
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None:
        raise AdapterError("invalid_input", "Current time must include a timezone.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _public_error(category: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"category": category, "message": message}
    for key, value in details.items():
        if value is not None:
            result[key] = value
    return result


def _normalize_host_uts46(raw_host: str) -> str:
    """Normalize one URL host without legacy IDNA2003 target changes."""

    host_input = raw_host.rstrip(".")
    if not host_input or "%" in host_input:
        raise AdapterError("invalid_input", "The URL is malformed.")
    try:
        literal = ipaddress.ip_address(host_input)
    except ValueError:
        literal = None
    if literal is not None:
        return str(literal).lower()

    if _idna_uts46 is None:
        if any(ord(character) > 0x7F for character in host_input):
            raise AdapterError("invalid_input", "The URL is malformed.")
        try:
            return host_input.encode("ascii").decode("ascii").lower()
        except UnicodeError:
            raise AdapterError("invalid_input", "The URL is malformed.") from None
    try:
        return _idna_uts46.encode(
            host_input,
            uts46=True,
            transitional=False,
            std3_rules=True,
        ).decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise AdapterError("invalid_input", "The URL is malformed.") from None


def validate_public_http_url(value: Any) -> str:
    """Validate a literal public HTTP(S) URL without performing DNS resolution."""

    if not isinstance(value, str) or not value.strip():
        raise AdapterError("invalid_input", "A public HTTP(S) URL is required.")
    cleaned = value.strip()
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in cleaned):
        raise AdapterError("invalid_input", "The URL is malformed.")
    try:
        parsed = urlsplit(cleaned)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise AdapterError("invalid_input", "The URL is malformed.") from None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise AdapterError("invalid_input", "The URL must use public HTTP(S).")
    if parsed.username is not None or parsed.password is not None:
        raise AdapterError("invalid_input", "The URL must not contain user information.")
    if port is not None and not 1 <= port <= 65535:
        raise AdapterError("invalid_input", "The URL is malformed.")

    host = _normalize_host_uts46(hostname)
    if not host or len(host) > 253:
        raise AdapterError("invalid_input", "The URL is malformed.")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise AdapterError("invalid_input", "The URL must identify a public host.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise AdapterError("invalid_input", "The URL must identify a public host.")
    if address is None:
        if "." not in host:
            raise AdapterError(
                "invalid_input", "The URL host must be a fully qualified public name."
            )
        labels = host.split(".")
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
            raise AdapterError(
                "invalid_input", "The URL contains an ambiguous numeric host."
            )
        if any(
            re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label
            )
            is None
            for label in labels
        ):
            raise AdapterError("invalid_input", "The URL is malformed.")
    return cleaned


def _normalized_hostname(url: str) -> str:
    """Return the IDNA-normalized hostname of an already validated URL."""

    validated = validate_public_http_url(url)
    hostname = urlsplit(validated).hostname
    if hostname is None:  # Defensive: validation above requires a hostname.
        raise AdapterError("invalid_input", "The URL is malformed.")
    return _normalize_host_uts46(hostname)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, _normalized_hostname(url), port


def _normalized_path(url: str) -> str:
    raw_path = urlsplit(url).path or "/"
    decoded = raw_path
    for _ in range(5):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        raise AdapterError("invalid_response", "A mapped URL path was over-encoded.")
    if "\\" in decoded or "\x00" in decoded:
        raise AdapterError("invalid_response", "A mapped URL path was unsafe.")
    normalized = posixpath.normpath("/" + decoded.lstrip("/"))
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _within_seed_path(candidate_url: str, seed_url: str) -> bool:
    seed_path = _normalized_path(seed_url).rstrip("/") or "/"
    candidate_path = _normalized_path(candidate_url)
    if seed_path == "/":
        return True
    return candidate_path == seed_path or candidate_path.startswith(f"{seed_path}/")


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _candidate_id(url: str) -> str:
    return f"web:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}"


def _validate_api_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 4096 or any(ord(character) < 33 for character in key):
        raise AdapterError("configuration_error", "Firecrawl API key is invalid.")
    return key


def _read_api_key_file(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise AdapterError(
            "configuration_error",
            "Firecrawl API key is unavailable; set FIRECRAWL_API_KEY or provision the private key file.",
        ) from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AdapterError("configuration_error", "Firecrawl API key file is invalid.")
        if metadata.st_mode & 0o077:
            raise AdapterError(
                "configuration_error", "Firecrawl API key file permissions must be 0600 or stricter."
            )
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise AdapterError(
                "configuration_error", "Firecrawl API key file must be owned by the current user."
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            raise AdapterError("configuration_error", "Firecrawl API key file is too large.")
        try:
            return _validate_api_key(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise AdapterError("configuration_error", "Firecrawl API key file is invalid.") from None
    finally:
        os.close(descriptor)


def load_api_key(
    *, environ: dict[str, str] | None = None, key_file: Path | None = None
) -> str:
    environment = os.environ if environ is None else environ
    if API_KEY_ENV in environment:
        return _validate_api_key(environment[API_KEY_ENV])
    if key_file is None:
        configured = environment.get(API_KEY_FILE_ENV)
        key_file = Path(configured).expanduser() if configured else DEFAULT_API_KEY_FILE
    if not key_file.is_absolute():
        raise AdapterError(
            "configuration_error", "Firecrawl API key file path must be absolute."
        )
    return _read_api_key_file(key_file)


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Fail closed on every redirect so bearer credentials never change origin."""

    def redirect_request(
        self,
        req: urllib_request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _open_without_redirect(request: urllib_request.Request, timeout: int) -> Any:
    opener = urllib_request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


def _validated_timeout(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS
    ):
        raise AdapterError(
            "invalid_input",
            f"Firecrawl timeout must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS} seconds.",
        )
    return value


def _validated_map_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_MAP_LIMIT:
        raise AdapterError(
            "invalid_input", f"Firecrawl Map limit must be between 1 and {MAX_MAP_LIMIT}."
        )
    return value


def post_json(endpoint: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    """POST fixed-shape JSON and return a bounded object; never expose response bodies."""

    if endpoint not in {MAP_ENDPOINT, SCRAPE_ENDPOINT}:
        raise AdapterError("invalid_input", "Unsupported Firecrawl endpoint.")
    timeout = _validated_timeout(timeout)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib_request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_validate_api_key(api_key)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with _open_without_redirect(request, timeout) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib_error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise AdapterError("authentication_error", "Firecrawl authentication failed.") from None
        if exc.code == 429:
            raise AdapterError("rate_limited", "Firecrawl quota or rate limit blocked the request.") from None
        raise AdapterError("upstream_error", "Firecrawl returned an unsuccessful HTTP response.") from None
    except (urllib_error.URLError, TimeoutError, OSError):
        raise AdapterError("network_error", "Firecrawl could not be reached.") from None

    if not isinstance(status, int) or not 200 <= status < 300:
        raise AdapterError("upstream_error", "Firecrawl returned an unsuccessful HTTP response.")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AdapterError("invalid_response", "Firecrawl response exceeded the safe size limit.")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AdapterError("invalid_response", "Firecrawl returned invalid JSON.") from None
    if not isinstance(decoded, dict):
        raise AdapterError("invalid_response", "Firecrawl response must be a JSON object.")
    return decoded


Transport = Callable[[str, dict[str, Any], str, int], dict[str, Any]]


def _route(*, mode: str, status: str, reason: str, limitations: list[str]) -> dict[str, Any]:
    return {
        "platform": "web",
        "backend": BACKEND,
        "mode": mode,
        "reason": reason,
        "login_state_used": False,
        "status": status,
        "limitations": limitations,
    }


def _map_links(response: dict[str, Any]) -> list[Any]:
    if response.get("success") is not True:
        raise AdapterError("invalid_response", "Firecrawl Map did not report success.")
    container = response.get("data") if isinstance(response.get("data"), dict) else response
    links = container.get("links") if isinstance(container, dict) else None
    if not isinstance(links, list):
        raise AdapterError("invalid_response", "Firecrawl Map response is missing links.")
    return links


def normalize_map_response(
    response: dict[str, Any], *, seed_url: str, limit: int, retrieved_at: str
) -> dict[str, Any]:
    seed = validate_public_http_url(seed_url)
    limit = _validated_map_limit(limit)
    seed_origin = _origin(seed)
    links = _map_links(response)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    excluded_non_public = 0
    excluded_cross_origin = 0
    excluded_outside_path = 0
    duplicate_links = 0

    for raw_link in links:
        if isinstance(raw_link, str):
            raw_url = raw_link
            title = None
            description = None
        elif isinstance(raw_link, dict):
            raw_url = raw_link.get("url")
            title = raw_link.get("title")
            description = raw_link.get("description")
            if title is not None and not isinstance(title, str):
                raise AdapterError("invalid_response", "Firecrawl Map link title is invalid.")
            if description is not None and not isinstance(description, str):
                raise AdapterError("invalid_response", "Firecrawl Map link description is invalid.")
        else:
            raise AdapterError("invalid_response", "Firecrawl Map returned an invalid link item.")
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise AdapterError("invalid_response", "Firecrawl Map link URL is invalid.")
        try:
            url = validate_public_http_url(raw_url)
        except AdapterError:
            excluded_non_public += 1
            continue
        if _origin(url) != seed_origin:
            excluded_cross_origin += 1
            continue
        if not _within_seed_path(url, seed):
            excluded_outside_path += 1
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            duplicate_links += 1
            continue
        seen.add(canonical)
        rank = len(candidates) + 1
        candidates.append(
            {
                "candidate_id": _candidate_id(canonical),
                "query": seed,
                "platform": "web",
                "backend": BACKEND,
                "rank": rank,
                "title": title.strip() if isinstance(title, str) and title.strip() else None,
                "url": url,
                "canonical_url": canonical,
                "snippet": description.strip() if isinstance(description, str) and description.strip() else None,
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
                    "route_reason": "explicit_site_map",
                    "map_seed_url": seed,
                },
                "limitations": [MAP_LIMITATION],
            }
        )

    truncated = len(candidates) > limit
    candidates = candidates[:limit]
    limitations = [MAP_LIMITATION]
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [seed],
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": limit,
        },
        "routes": [
            _route(
                mode="site-map",
                status="completed",
                reason="explicit_site_map",
                limitations=limitations,
            )
        ],
        "candidates": candidates,
        "coverage": [
            {
                "backend": BACKEND,
                "mode": "site-map",
                "seed_url": seed,
                "input_links": len(links),
                "returned_count": len(candidates),
                "excluded_non_public": excluded_non_public,
                "excluded_cross_origin": excluded_cross_origin,
                "excluded_outside_path": excluded_outside_path,
                "duplicate_links": duplicate_links,
                "truncated": truncated,
                "login_state_used": False,
                "limitations": limitations,
            }
        ],
        "errors": [],
    }


def normalize_scrape_response(
    response: dict[str, Any], *, candidate: dict[str, Any], checked_at: str
) -> dict[str, Any]:
    if response.get("success") is not True or not isinstance(response.get("data"), dict):
        raise AdapterError("invalid_response", "Firecrawl Scrape did not report success.")
    markdown = response["data"].get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise AdapterError("invalid_response", "Firecrawl Scrape returned no Markdown.")

    normalized = copy.deepcopy(candidate)
    normalized["verification"] = {
        "status": "candidate",
        "opened_original": True,
        "checked_at": checked_at,
    }
    platform_fields = normalized.get("platform_fields")
    platform_fields = copy.deepcopy(platform_fields) if isinstance(platform_fields, dict) else {}
    platform_fields["firecrawl"] = {
        "scrape_markdown": markdown.strip(),
        "scrape_retrieved_at": checked_at,
        "store_in_cache": False,
        "proxy": "basic",
    }
    normalized["platform_fields"] = platform_fields
    provenance = normalized.get("provenance")
    provenance = copy.deepcopy(provenance) if isinstance(provenance, dict) else {}
    provenance["verification"] = {
        "backend": BACKEND,
        "route_reason": "verify_current_candidate_with_firecrawl",
        "source_query": normalized["query"],
        "candidate_id": normalized["candidate_id"],
        "checked_at": checked_at,
    }
    normalized["provenance"] = provenance
    limitations = normalized.get("limitations")
    limitations = list(limitations) if isinstance(limitations, list) else []
    if SCRAPE_LIMITATION not in limitations:
        limitations.append(SCRAPE_LIMITATION)
    normalized["limitations"] = limitations
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [normalized["query"]],
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": 1,
        },
        "routes": [
            _route(
                mode="verify-candidate",
                status="completed",
                reason="verify_current_candidate_with_firecrawl",
                limitations=[SCRAPE_LIMITATION],
            )
        ],
        "candidates": [normalized],
        "coverage": [
            {
                "backend": BACKEND,
                "mode": "verify-candidate",
                "query_count": 1,
                "returned_count": 1,
                "opened_count": 1,
                "truncated": False,
                "login_state_used": False,
                "limitations": [SCRAPE_LIMITATION],
            }
        ],
        "errors": [],
    }


def execute(
    args: argparse.Namespace,
    *,
    transport: Transport = post_json,
    receipt_secret: bytes | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    timeout = _validated_timeout(getattr(args, "timeout", None))
    if args.command == "map":
        limit = _validated_map_limit(getattr(args, "limit", None))
        seed = validate_public_http_url(args.url)
        key = load_api_key()
        response = transport(
            MAP_ENDPOINT,
            {
                "url": seed,
                "limit": limit,
                "includeSubdomains": False,
                "ignoreQueryParameters": True,
            },
            key,
            timeout,
        )
        if not isinstance(response, dict):
            raise AdapterError("invalid_response", "Firecrawl response must be a JSON object.")
        return normalize_map_response(
            response,
            seed_url=seed,
            limit=limit,
            retrieved_at=utc_now_iso(now),
        )

    if args.command == "scrape":
        anysearch = _load_anysearch_adapter()
        try:
            candidate = anysearch.load_candidate_argument(
                args.candidate_from_search,
                receipt_secret=receipt_secret,
                now=now,
            )
        except Exception as exc:
            if isinstance(exc, anysearch.AdapterError):
                raise AdapterError(exc.category, exc.message) from None
            raise AdapterError(
                "invalid_candidate", "Current AnySearch candidate validation failed."
            ) from None
        candidate_url = validate_public_http_url(candidate.get("url"))
        key = load_api_key()
        response = transport(
            SCRAPE_ENDPOINT,
            {
                "url": candidate_url,
                "formats": ["markdown"],
                "storeInCache": False,
                "proxy": "basic",
                "skipTlsVerification": False,
            },
            key,
            timeout,
        )
        if not isinstance(response, dict):
            raise AdapterError("invalid_response", "Firecrawl response must be a JSON object.")
        return normalize_scrape_response(
            response, candidate=candidate, checked_at=utc_now_iso(now)
        )

    raise AdapterError("invalid_input", "Unsupported Firecrawl adapter command.")


def error_envelope(
    *, mode: str, queries: list[str], category: str, message: str, requested_limit: int
) -> dict[str, Any]:
    limitation = MAP_LIMITATION if mode == "site-map" else SCRAPE_LIMITATION
    reason = "explicit_site_map" if mode == "site-map" else "verify_current_candidate_with_firecrawl"
    return {
        "schema_version": "1.0",
        "request": {
            "queries": queries,
            "platforms": ["web"],
            "time_range": None,
            "requested_limit": requested_limit,
        },
        "routes": [
            _route(mode=mode, status="failed", reason=reason, limitations=[limitation])
        ],
        "candidates": [],
        "coverage": [
            {
                "backend": BACKEND,
                "mode": mode,
                "returned_count": 0,
                "truncated": False,
                "login_state_used": False,
                "limitations": [limitation],
            }
        ],
        "errors": [_public_error(category, message)],
    }


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=int, default=45)
    parser = argparse.ArgumentParser(
        description="Run explicit bounded Firecrawl Map or current-candidate Scrape."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    map_parser = subparsers.add_parser("map", parents=[common])
    map_parser.add_argument("--url", required=True)
    map_parser.add_argument("--limit", type=int, default=50)
    scrape = subparsers.add_parser("scrape", parents=[common])
    scrape.add_argument("--candidate-from-search", required=True)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not MIN_TIMEOUT_SECONDS <= args.timeout <= MAX_TIMEOUT_SECONDS:
        parser.error(
            f"--timeout must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}"
        )
    if args.command == "map" and not 1 <= args.limit <= MAX_MAP_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_MAP_LIMIT}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "site-map" if args.command == "map" else "verify-candidate"
    queries = [args.url] if args.command == "map" else []
    requested_limit = args.limit if args.command == "map" else 1
    try:
        result = execute(args)
    except AdapterError as exc:
        result = error_envelope(
            mode=mode,
            queries=queries,
            category=exc.category,
            message=exc.message,
            requested_limit=requested_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except Exception:
        result = error_envelope(
            mode=mode,
            queries=queries,
            category="internal_error",
            message="The Firecrawl adapter failed without exposing credentials or response bodies.",
            requested_limit=requested_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
