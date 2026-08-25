#!/usr/bin/env python3
"""Search public Weibo posts with bounded read-only session reuse.

The adapter tries the anonymous mobile index first.  If that public route is
blocked by a verification/response gate, ``auto`` mode may make one bounded
OpenCLI ``weibo search`` call through the user's existing Chrome session.  It
never receives, prints, or persists browser cookies and never exposes Weibo
write/private-account commands.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo


PLATFORM = "weibo"
ANONYMOUS_BACKEND = "weibo-public-anonymous"
BROWSER_BACKEND = "weibo-opencli-readonly"
AUTO_BACKEND = "weibo-readonly-auto"
# Backwards-compatible constant used by the anonymous normalization path.
BACKEND = ANONYMOUS_BACKEND
TZ = ZoneInfo("Asia/Shanghai")
SEARCH_URL = "https://m.weibo.cn/api/container/getIndex"
VISITOR_URL = "https://visitor.passport.weibo.cn/visitor/genvisitor2"
ALLOWED_HOSTS = frozenset({"m.weibo.cn", "visitor.passport.weibo.cn"})
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Mobile/15E148"
)
MAX_QUERY_LENGTH = 200
MAX_RESULTS = 20
MAX_PAGES = 3
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_DELAY_MIN = 5.0
DEFAULT_DELAY_MAX = 8.0
BASE_LIMITATIONS = [
    "Results come from an unofficial public mobile endpoint and are discovery candidates, not verified originals.",
    "The public mobile index is incomplete and may change, throttle, or reject anonymous requests without notice.",
    "The adapter uses only an ephemeral in-memory visitor session; it never reads or persists browser/account cookies.",
    "Search is bounded to at most 3 pages and 20 candidates; comments, profiles, media downloads, and private data are not fetched.",
]
BROWSER_LIMITATIONS = [
    "Results come from one bounded read-only OpenCLI Weibo search using the existing Chrome session.",
    "The adapter never receives, prints, or persists browser cookies and exposes no write or private-account command.",
    "Browser-session search returns at most 20 public candidates; comments, profiles, media downloads, favorites, feeds, and messages are not fetched.",
]
FALLBACK_ERROR_CATEGORIES = frozenset(
    {"access_gate_redirect", "access_gate_rejected", "access_gate_response"}
)
ACCESS_GATE_MARKERS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "passport",
    "verify",
    "verification",
    "captcha",
    "forbidden",
    "access denied",
    "登录",
    "验证",
    "验证码",
    "访问受限",
    "请先登录",
    "安全验证",
    "账号异常",
)
OPENCLI_SAFE_ENV_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
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
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "XAUTHORITY",
        "OPENCLI_HOME",
    }
)


class AdapterError(RuntimeError):
    """A public, secret-free adapter failure suitable for the error envelope."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Fail closed instead of following a redirect into login or verification."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def looks_like_access_gate(value: Any) -> bool:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return False
    lowered = text.casefold()
    return any(marker in lowered for marker in ACCESS_GATE_MARKERS)


def opencli_child_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Keep only OpenCLI runtime context; never forward unrelated credentials."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name.upper() in OPENCLI_SAFE_ENV_NAMES
    }


def now_shanghai() -> datetime:
    return datetime.now(TZ)


def iso_time(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)

    def image_alt(match: re.Match[str]) -> str:
        tag = match.group(0)
        alt = re.search(
            r"\balt\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            tag,
            flags=re.I,
        )
        return next((part for part in alt.groups() if part is not None), "") if alt else ""

    text = re.sub(r"<img\b[^>]*>", image_alt, text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clipped_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "…"


def parse_weibo_datetime(value: Any, now: datetime) -> datetime | None:
    raw = strip_html(value)
    if not raw:
        return None
    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.astimezone(TZ) if parsed.tzinfo else parsed.replace(tzinfo=TZ)
        except ValueError:
            pass
    if raw == "刚刚":
        return now
    match = re.fullmatch(r"(\d+)分钟前", raw)
    if match:
        return now - timedelta(minutes=int(match.group(1)))
    match = re.fullmatch(r"(\d+)小时前", raw)
    if match:
        return now - timedelta(hours=int(match.group(1)))
    match = re.fullmatch(r"今天\s*(\d{1,2}):(\d{2})", raw)
    if match:
        return now.replace(
            hour=int(match.group(1)),
            minute=int(match.group(2)),
            second=0,
            microsecond=0,
        )
    match = re.fullmatch(r"昨天\s*(\d{1,2}):(\d{2})", raw)
    if match:
        return (now - timedelta(days=1)).replace(
            hour=int(match.group(1)),
            minute=int(match.group(2)),
            second=0,
            microsecond=0,
        )
    match = re.fullmatch(r"(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})", raw)
    if match:
        try:
            candidate = datetime(
                now.year,
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                tzinfo=TZ,
            )
        except ValueError:
            return None
        if candidate > now + timedelta(days=2):
            candidate = candidate.replace(year=now.year - 1)
        return candidate
    match = re.fullmatch(
        r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",
        raw,
    )
    if match:
        try:
            candidate = datetime(
                int(match.group(1) or now.year),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                tzinfo=TZ,
            )
        except ValueError:
            return None
        if match.group(1) is None and candidate > now + timedelta(days=2):
            candidate = candidate.replace(year=now.year - 1)
        return candidate
    return None


def nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        integer = int(value)
        return integer if integer >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value.strip())
    return None


def valid_cookie_component(value: Any) -> str | None:
    text = str(value or "")
    if not text or len(text) > 4096 or re.search(r"[\s;,\r\n]", text):
        return None
    return text


class WeiboPublicClient:
    """Low-frequency, public-only client with no environment/browser cookies."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        delay_min: float = DEFAULT_DELAY_MIN,
        delay_max: float = DEFAULT_DELAY_MAX,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        uniform: Callable[[float, float], float] = random.uniform,
    ):
        if not 1 <= timeout <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        if delay_min < 0 or delay_max < delay_min:
            raise ValueError("invalid delay range")
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), RejectRedirects()
        )
        self.timeout = timeout
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.uniform = uniform
        self.cookie_header = ""
        self.request_count = 0
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        target = self.uniform(self.delay_min, self.delay_max)
        elapsed = self.monotonic() - self._last_request_at
        if elapsed < target:
            self.sleeper(target - elapsed)

    def _read(self, request: urllib.request.Request) -> str:
        parsed_url = urllib.parse.urlsplit(request.full_url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_HOSTS:
            raise AdapterError("blocked_endpoint", "The adapter refused a non-Weibo HTTPS endpoint.")
        self._throttle()
        self.request_count += 1
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise AdapterError(
                    "access_gate_redirect",
                    "Weibo redirected the anonymous request; login or verification was not followed.",
                ) from None
            if exc.code in {401, 403}:
                raise AdapterError(
                    "access_gate_rejected",
                    f"Weibo public endpoint rejected anonymous access with HTTP {exc.code}.",
                ) from None
            if exc.code == 429:
                raise AdapterError(
                    "rate_limited",
                    "Weibo public endpoint rate-limited the anonymous request.",
                ) from None
            raise AdapterError(
                "http_error", f"Weibo public endpoint returned HTTP {exc.code}."
            ) from None
        except urllib.error.URLError as exc:
            reason = str(exc.reason).splitlines()[0][:160]
            raise AdapterError("network_error", f"Weibo public endpoint network error: {reason}") from exc
        except (TimeoutError, OSError) as exc:
            reason = str(exc).splitlines()[0][:160] or exc.__class__.__name__
            raise AdapterError("network_error", f"Weibo public endpoint network error: {reason}") from exc
        finally:
            self._last_request_at = self.monotonic()
        if len(data) > MAX_RESPONSE_BYTES:
            raise AdapterError("response_too_large", "Weibo public endpoint response exceeded 4 MiB.")
        return data.decode("utf-8", errors="replace")

    def ensure_visitor_cookie(self) -> None:
        if self.cookie_header:
            return
        payload = urllib.parse.urlencode(
            {
                "cb": "visitor_callback",
                "from": "weibo",
                "tid": "",
                "return_url": "https://m.weibo.cn/",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            VISITOR_URL,
            data=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        body = self._read(request)
        match = re.search(r"visitor_callback\((\{.*\})\)\s*;?\s*$", body, flags=re.S)
        if not match:
            if looks_like_access_gate(body):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo visitor passport returned a login or verification gate.",
                )
            raise AdapterError(
                "visitor_session_error",
                "Weibo visitor passport returned an unexpected response.",
            )
        try:
            payload_json = json.loads(match.group(1))
        except json.JSONDecodeError:
            raise AdapterError(
                "visitor_session_error", "Weibo visitor passport returned invalid JSON."
            ) from None
        if not isinstance(payload_json, dict):
            if looks_like_access_gate(payload_json):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo visitor passport returned a login or verification gate.",
                )
            raise AdapterError(
                "visitor_session_error", "Weibo visitor passport returned an invalid shape."
            )
        data = payload_json.get("data")
        data = data if isinstance(data, dict) else {}
        sub = valid_cookie_component(data.get("sub"))
        subp = valid_cookie_component(data.get("subp"))
        if not sub or not subp:
            raise AdapterError(
                "visitor_session_error",
                "Weibo visitor passport did not return a usable anonymous session.",
            )
        self.cookie_header = f"SUB={sub}; SUBP={subp}"

    def get_json(self, base_url: str, params: dict[str, Any]) -> dict[str, Any]:
        if base_url != SEARCH_URL:
            raise AdapterError("blocked_endpoint", "Only the public Weibo search endpoint is allowed.")
        self.ensure_visitor_cookie()
        url = base_url + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://m.weibo.cn/",
                "Accept": "application/json,text/plain,*/*",
                "Cookie": self.cookie_header,
            },
        )
        body = self._read(request)
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            if looks_like_access_gate(body):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo public search returned a login or verification gate.",
                )
            raise AdapterError(
                "invalid_response", "Weibo public search returned non-JSON content."
            ) from None
        if not isinstance(parsed, dict):
            if looks_like_access_gate(parsed):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo public search returned a login or verification gate.",
                )
            raise AdapterError(
                "invalid_response", "Weibo public search returned an unexpected JSON shape."
            )
        ok = parsed.get("ok")
        if ok is not None and ok not in (1, True, "1"):
            message = clipped_text(strip_html(parsed.get("msg")), 120)
            suffix = f": {message}" if message else "."
            if looks_like_access_gate(message):
                raise AdapterError(
                    "access_gate_rejected",
                    "Weibo public search returned an explicit login or verification gate.",
                )
            raise AdapterError(
                "upstream_rejected", f"Weibo public search rejected the request{suffix}"
            )
        return parsed

    def search_page(self, keyword: str, page: int) -> list[dict[str, Any]]:
        if not keyword or len(keyword) > MAX_QUERY_LENGTH or not 1 <= page <= MAX_PAGES:
            raise AdapterError("invalid_request", "Invalid Weibo query or page bound.")
        payload = self.get_json(
            SEARCH_URL,
            {
                "containerid": f"100103type=1&q={keyword}",
                "page_type": "searchall",
                "page": page,
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            if looks_like_access_gate(payload):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo public search returned an explicit login or verification gate.",
                )
            raise AdapterError(
                "invalid_response", "Weibo public search response is missing a data object."
            )
        cards = data.get("cards")
        if not isinstance(cards, list):
            if looks_like_access_gate(payload):
                raise AdapterError(
                    "access_gate_response",
                    "Weibo public search returned an explicit login or verification gate.",
                )
            raise AdapterError(
                "invalid_response", "Weibo public search response is missing a cards list."
            )
        results: list[dict[str, Any]] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            if card.get("card_type") == 9 and isinstance(card.get("mblog"), dict):
                results.append(card["mblog"])
            group = card.get("card_group")
            if not isinstance(group, list):
                continue
            for child in group:
                if (
                    isinstance(child, dict)
                    and child.get("card_type") == 9
                    and isinstance(child.get("mblog"), dict)
                ):
                    results.append(child["mblog"])
        return results


def normalize_post(
    raw: dict[str, Any],
    *,
    query: str,
    page: int,
    retrieved_at: str,
    now: datetime,
) -> tuple[dict[str, Any], datetime | None] | None:
    post_id = str(raw.get("idstr") or raw.get("id") or "").strip()
    if not re.fullmatch(r"\d{6,30}", post_id):
        return None
    text = strip_html(raw.get("text") or raw.get("raw_text"))
    if not text:
        return None
    user = raw.get("user")
    user = user if isinstance(user, dict) else {}
    author = strip_html(user.get("screen_name")) or None
    user_id = str(user.get("id") or "").strip() or None
    created_raw = strip_html(raw.get("created_at"))
    created = parse_weibo_datetime(created_raw, now)
    canonical_url = f"https://m.weibo.cn/detail/{post_id}"
    pics = raw.get("pics")
    picture_count = len(pics) if isinstance(pics, list) else 0
    page_info = raw.get("page_info")
    page_info = page_info if isinstance(page_info, dict) else {}
    limitations = [
        "Search-card text and metrics are candidate metadata; the original post was not opened or verified."
    ]
    if created is None:
        limitations.append("The returned Weibo timestamp could not be parsed reliably.")
    candidate = {
        "candidate_id": f"weibo:{post_id}",
        "query": query,
        "platform": PLATFORM,
        "backend": BACKEND,
        "rank": 0,
        "title": clipped_text(text, 100),
        "url": canonical_url,
        "canonical_url": canonical_url,
        "snippet": clipped_text(text, 600),
        "author": author,
        "published_at": iso_time(created),
        "content_type": "weibo_post",
        "language": None,
        "metrics": {
            "likes": nonnegative_int(raw.get("attitudes_count")),
            "comments": nonnegative_int(raw.get("comments_count")),
            "collects": None,
            "shares": nonnegative_int(raw.get("reposts_count")),
            "views": None,
        },
        "access": {"visibility": "public", "login_state_used": False},
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": post_id,
            "retrieved_at": retrieved_at,
            "route_reason": "public_weibo_anonymous_search",
            "search_page": page,
            "anonymous_visitor_session": True,
        },
        "platform_fields": {
            "weibo": {
                "post_id": post_id,
                "user_id": user_id,
                "source": strip_html(raw.get("source")) or None,
                "created_at_raw": created_raw or None,
                "verified": user.get("verified") if isinstance(user.get("verified"), bool) else None,
                "followers_count": nonnegative_int(user.get("followers_count")),
                "picture_count": picture_count,
                "has_video": page_info.get("type") == "video",
            }
        },
        "limitations": limitations,
    }
    return candidate, created


def parse_opencli_rows(stdout: str) -> list[dict[str, Any]]:
    """Parse only the structured stdout contract; never inspect browser logs."""

    if len(stdout.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES:
        raise AdapterError("response_too_large", "OpenCLI Weibo search output exceeded 4 MiB.")
    try:
        payload = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        raise AdapterError(
            "browser_invalid_response", "OpenCLI Weibo search returned non-JSON stdout."
        ) from exc
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (
                payload[key]
                for key in ("rows", "data", "results", "items")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
    else:
        rows = None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise AdapterError(
            "browser_invalid_response", "OpenCLI Weibo search returned an unexpected JSON shape."
        )
    return rows


def canonicalize_browser_post_url(value: Any) -> tuple[str, str | None, str] | None:
    raw = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in {"weibo.com", "www.weibo.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    user_id, post_id = parts[0], parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", user_id) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,80}", post_id
    ):
        return None
    canonical = f"https://weibo.com/{urllib.parse.quote(user_id)}/{urllib.parse.quote(post_id)}"
    return canonical, user_id or None, post_id


def normalize_browser_row(
    raw: dict[str, Any],
    *,
    query: str,
    retrieved_at: str,
    now: datetime,
) -> tuple[dict[str, Any], datetime | None] | None:
    url_parts = canonicalize_browser_post_url(raw.get("url"))
    if url_parts is None:
        return None
    canonical_url, user_id, url_post_id = url_parts
    returned_post_id = str(raw.get("id") or "").strip()
    if returned_post_id and returned_post_id != url_post_id:
        return None
    post_id = url_post_id
    text = strip_html(raw.get("title") or raw.get("text") or raw.get("summary"))
    if not text:
        return None
    author = strip_html(raw.get("author")) or None
    created_raw = strip_html(raw.get("time") or raw.get("published_at"))
    created = parse_weibo_datetime(created_raw, now)
    limitations = [
        "Browser search-card text is candidate metadata; the original post was not opened or verified.",
        "The existing login state was used only to search public posts; no Cookie value entered the adapter output.",
    ]
    if created is None:
        limitations.append("The returned Weibo timestamp could not be parsed reliably.")
    candidate = {
        "candidate_id": f"weibo:{post_id}",
        "query": query,
        "platform": PLATFORM,
        "backend": BROWSER_BACKEND,
        "rank": 0,
        "title": clipped_text(text, 100),
        "url": canonical_url,
        "canonical_url": canonical_url,
        "snippet": clipped_text(text, 600),
        "author": author,
        "published_at": iso_time(created),
        "content_type": "weibo_post",
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
            "source_id": post_id,
            "retrieved_at": retrieved_at,
            "route_reason": "public_weibo_readonly_browser_fallback",
            "search_page": None,
            "anonymous_visitor_session": False,
            "browser_session_readonly": True,
        },
        "platform_fields": {
            "weibo": {
                "post_id": post_id,
                "user_id": user_id,
                "source": None,
                "created_at_raw": created_raw or None,
                "verified": None,
                "followers_count": None,
                "picture_count": None,
                "has_video": None,
            }
        },
        "limitations": limitations,
    }
    return candidate, created


def envelope(
    *,
    query: str,
    limit: int,
    max_pages: int,
    days: int | None,
    now: datetime,
    candidates: list[dict[str, Any]],
    status: str,
    pages_attempted: int,
    pages_completed: int,
    raw_result_count: int,
    rejected_count: int,
    duplicate_count: int,
    filtered_outside_window: int,
    unknown_time_count: int,
    truncated: bool,
    request_count: int,
    errors: list[dict[str, str]],
    backend: str = ANONYMOUS_BACKEND,
    login_state_used: bool = False,
    route_reason: str = "public_weibo_anonymous_search",
    backend_limitations: list[str] | None = None,
) -> dict[str, Any]:
    start = now - timedelta(days=days) if days is not None else None
    time_range = (
        {
            "start": iso_time(start),
            "end": iso_time(now),
            "filter": "client_side",
        }
        if start
        else None
    )
    limitations = list(
        backend_limitations
        if backend_limitations is not None
        else BASE_LIMITATIONS
        if backend == ANONYMOUS_BACKEND
        else BROWSER_LIMITATIONS
    )
    if days is not None:
        limitations.append(
            "The requested time window is applied locally only to the bounded returned pages; it is not a server-side or exhaustive date search."
        )
        if unknown_time_count:
            limitations.append(
                f"{unknown_time_count} candidate(s) with unparseable timestamps were retained and are not time-window verified."
            )
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": [PLATFORM],
            "time_range": time_range,
            "requested_limit": limit,
        },
        "routes": [
            {
                "platform": PLATFORM,
                "backend": backend,
                "mode": "search",
                "login_state_used": login_state_used,
                "status": status,
                "route_reason": route_reason,
                "limitations": limitations,
            }
        ],
        "candidates": candidates,
        "coverage": [
            {
                "platform": PLATFORM,
                "backend": backend,
                "query_count": 1,
                "pages_allowed": max_pages,
                "pages_attempted": pages_attempted,
                "pages_completed": pages_completed,
                "raw_result_count": raw_result_count,
                "returned_count": len(candidates),
                "rejected_count": rejected_count,
                "duplicate_count": duplicate_count,
                "filtered_outside_window": filtered_outside_window,
                "unknown_time_count": unknown_time_count,
                "request_count": request_count,
                **(
                    {"request_count_including_visitor_session": request_count}
                    if backend == ANONYMOUS_BACKEND
                    else {}
                ),
                "time_filter": "client_side" if days is not None else "none",
                "truncated": truncated,
                "login_state_used": login_state_used,
                "limitations": limitations,
            }
        ],
        "errors": errors,
    }


def run_search(
    *,
    query: str,
    limit: int,
    max_pages: int,
    days: int | None,
    client: WeiboPublicClient,
    now: datetime,
) -> dict[str, Any]:
    retrieved_at = iso_time(now)
    assert retrieved_at is not None
    start = now - timedelta(days=days) if days is not None else None
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    pages_attempted = 0
    pages_completed = 0
    raw_result_count = 0
    rejected_count = 0
    duplicate_count = 0
    filtered_outside_window = 0
    unknown_time_count = 0
    truncated = False
    errors: list[dict[str, str]] = []

    for page in range(1, max_pages + 1):
        pages_attempted += 1
        try:
            raw_posts = client.search_page(query, page)
        except AdapterError as exc:
            errors.append(
                {"backend": BACKEND, "category": exc.category, "message": exc.message}
            )
            truncated = True
            break
        pages_completed += 1
        raw_result_count += len(raw_posts)
        if not raw_posts:
            break
        for raw in raw_posts:
            normalized = normalize_post(
                raw,
                query=query,
                page=page,
                retrieved_at=retrieved_at,
                now=now,
            )
            if normalized is None:
                rejected_count += 1
                continue
            candidate, created = normalized
            candidate_id = candidate["candidate_id"]
            if candidate_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(candidate_id)
            if start is not None:
                if created is None:
                    unknown_time_count += 1
                elif not start <= created <= now:
                    filtered_outside_window += 1
                    continue
            candidates.append(candidate)
            if len(candidates) >= limit:
                truncated = True
                break
        if len(candidates) >= limit:
            break
        if page == max_pages:
            truncated = True

    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    status = "failed" if errors and not candidates else "partial" if errors or rejected_count else "completed"
    return envelope(
        query=query,
        limit=limit,
        max_pages=max_pages,
        days=days,
        now=now,
        candidates=candidates,
        status=status,
        pages_attempted=pages_attempted,
        pages_completed=pages_completed,
        raw_result_count=raw_result_count,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        filtered_outside_window=filtered_outside_window,
        unknown_time_count=unknown_time_count,
        truncated=truncated,
        request_count=client.request_count,
        errors=errors,
    )


def run_browser_search(
    *,
    query: str,
    limit: int,
    days: int | None,
    timeout: int,
    now: datetime,
    runner: Callable[..., Any] = subprocess.run,
    opencli_path: str | None = None,
) -> dict[str, Any]:
    """Run one allowlisted OpenCLI public search without handling Cookie values."""

    retrieved_at = iso_time(now)
    assert retrieved_at is not None
    resolved_opencli = opencli_path or shutil.which("opencli")
    if not resolved_opencli:
        return envelope(
            query=query,
            limit=limit,
            max_pages=1,
            days=days,
            now=now,
            candidates=[],
            status="failed",
            pages_attempted=0,
            pages_completed=0,
            raw_result_count=0,
            rejected_count=0,
            duplicate_count=0,
            filtered_outside_window=0,
            unknown_time_count=0,
            truncated=False,
            request_count=0,
            errors=[
                {
                    "backend": BROWSER_BACKEND,
                    "category": "browser_backend_unavailable",
                    "message": "OpenCLI is not installed or not available on PATH.",
                }
            ],
            backend=BROWSER_BACKEND,
            login_state_used=True,
            route_reason="public_weibo_readonly_browser_fallback",
        )
    command = [
        resolved_opencli,
        "weibo",
        "search",
        query,
        "--limit",
        str(limit),
        "--window",
        "background",
        "--site-session",
        "ephemeral",
        "--keep-tab",
        "false",
        "-f",
        "json",
    ]
    try:
        completed = runner(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=opencli_child_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        completed = None
        execution_error = exc.__class__.__name__
    else:
        execution_error = ""

    errors: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    if completed is None:
        errors.append(
            {
                "backend": BROWSER_BACKEND,
                "category": "browser_search_error",
                "message": f"OpenCLI Weibo search could not complete ({execution_error}).",
            }
        )
    elif completed.returncode != 0:
        errors.append(
            {
                "backend": BROWSER_BACKEND,
                "category": "browser_search_error",
                "message": f"OpenCLI Weibo search exited with code {completed.returncode}; browser logs were not retained.",
            }
        )
    else:
        try:
            rows = parse_opencli_rows(completed.stdout)
        except AdapterError as exc:
            errors.append(
                {"backend": BROWSER_BACKEND, "category": exc.category, "message": exc.message}
            )

    start = now - timedelta(days=days) if days is not None else None
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    rejected_count = 0
    duplicate_count = 0
    filtered_outside_window = 0
    unknown_time_count = 0
    for raw in rows[:limit]:
        normalized = normalize_browser_row(
            raw,
            query=query,
            retrieved_at=retrieved_at,
            now=now,
        )
        if normalized is None:
            rejected_count += 1
            continue
        candidate, created = normalized
        candidate_id = candidate["candidate_id"]
        if candidate_id in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(candidate_id)
        if start is not None:
            if created is None:
                unknown_time_count += 1
            elif not start <= created <= now:
                filtered_outside_window += 1
                continue
        candidates.append(candidate)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    status = (
        "failed"
        if errors
        else "partial"
        if rejected_count
        else "completed"
    )
    return envelope(
        query=query,
        limit=limit,
        max_pages=1,
        days=days,
        now=now,
        candidates=candidates,
        status=status,
        pages_attempted=1 if completed is not None else 0,
        pages_completed=1 if completed is not None and not errors else 0,
        raw_result_count=len(rows),
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        filtered_outside_window=filtered_outside_window,
        unknown_time_count=unknown_time_count,
        truncated=len(rows) >= limit,
        request_count=1 if completed is not None else 0,
        errors=errors,
        backend=BROWSER_BACKEND,
        login_state_used=True,
        route_reason="public_weibo_readonly_browser_fallback",
    )


def should_use_browser_fallback(result: dict[str, Any]) -> bool:
    return any(
        error.get("category") in FALLBACK_ERROR_CATEGORIES
        for error in result.get("errors", [])
        if isinstance(error, dict)
    )


def candidate_fingerprint(candidate: dict[str, Any]) -> tuple[str, str]:
    author = str(candidate.get("author") or "").casefold().strip()
    snippet = re.sub(r"\s+", " ", str(candidate.get("snippet") or "")).casefold().strip()
    return author, snippet


def merge_browser_fallback(
    anonymous: dict[str, Any], browser: dict[str, Any], *, limit: int
) -> dict[str, Any]:
    """Merge recovered public candidates without preserving credential-bearing logs."""

    browser_succeeded = not browser.get("errors")
    merged = dict(anonymous)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_fingerprints: set[tuple[str, str]] = set()
    for source in (anonymous, browser):
        for candidate in source.get("candidates", []):
            candidate_id = str(candidate.get("candidate_id") or "")
            fingerprint = candidate_fingerprint(candidate)
            if candidate_id in seen_ids or fingerprint in seen_fingerprints:
                continue
            seen_ids.add(candidate_id)
            seen_fingerprints.add(fingerprint)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    anonymous_routes = [dict(route) for route in anonymous.get("routes", [])]
    anonymous_coverage = [dict(item) for item in anonymous.get("coverage", [])]
    for item in (*anonymous_routes, *anonymous_coverage):
        item["browser_fallback_triggered"] = True
        item["browser_fallback_recovered"] = browser_succeeded
        item["recovered_error_categories"] = [
            error.get("category") for error in anonymous.get("errors", [])
        ]
    merged["routes"] = [*anonymous_routes, *browser.get("routes", [])]
    merged["coverage"] = [*anonymous_coverage, *browser.get("coverage", [])]
    merged["candidates"] = candidates
    merged["errors"] = [] if browser_succeeded else [
        *anonymous.get("errors", []),
        *browser.get("errors", []),
    ]
    return merged


def run_search_auto(
    *,
    query: str,
    limit: int,
    max_pages: int,
    days: int | None,
    timeout: int,
    now: datetime,
    session_mode: str,
    client: WeiboPublicClient | None = None,
    runner: Callable[..., Any] = subprocess.run,
    opencli_path: str | None = None,
) -> dict[str, Any]:
    if session_mode not in {"auto", "anonymous"}:
        raise AdapterError(
            "invalid_session_mode",
            "Weibo browser search is an internal fallback and cannot be selected directly.",
        )
    anonymous = run_search(
        query=query,
        limit=limit,
        max_pages=max_pages,
        days=days,
        client=client or WeiboPublicClient(timeout=timeout),
        now=now,
    )
    if session_mode == "anonymous" or not should_use_browser_fallback(anonymous):
        return anonymous
    browser = run_browser_search(
        query=query,
        limit=limit,
        days=days,
        timeout=timeout,
        now=now,
        runner=runner,
        opencli_path=opencli_path,
    )
    return merge_browser_fallback(anonymous, browser, limit=limit)


def self_test() -> dict[str, Any]:
    now = datetime(2026, 7, 28, 14, 30, tzinfo=TZ)
    assert strip_html("a<br>b &amp; c") == "a\nb & c"
    assert strip_html('<img alt="[微笑]" src="x">') == "[微笑]"
    assert parse_weibo_datetime("2小时前", now) == datetime(
        2026, 7, 28, 12, 30, tzinfo=TZ
    )
    assert parse_weibo_datetime("昨天 09:15", now) == datetime(
        2026, 7, 27, 9, 15, tzinfo=TZ
    )
    assert parse_weibo_datetime("07月28日 09:15", now) == datetime(
        2026, 7, 28, 9, 15, tzinfo=TZ
    )
    assert nonnegative_int("0") == 0
    assert nonnegative_int("1.2万") is None
    return {"status": "passed", "network_used": False, "backend": AUTO_BACKEND}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Weibo public candidate adapter with bounded browser-session fallback.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser(
        "search", help="Search public Weibo post candidates", allow_abbrev=False
    )
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--max-pages", type=int, default=3)
    search.add_argument("--days", type=int)
    search.add_argument("--timeout", type=int, default=30)
    search.add_argument(
        "--session-mode",
        choices=("auto", "anonymous"),
        default="auto",
        help="auto tries anonymous first and uses one read-only browser search only after an access-gate failure",
    )
    subparsers.add_parser("self-test", help="Run offline parser checks", allow_abbrev=False)
    args = parser.parse_args(argv)
    if args.command == "search":
        args.query = args.query.strip()
        if not args.query or len(args.query) > MAX_QUERY_LENGTH:
            parser.error(f"--query must contain 1 to {MAX_QUERY_LENGTH} characters")
        if not 1 <= args.limit <= MAX_RESULTS:
            parser.error(f"--limit must be between 1 and {MAX_RESULTS}")
        if not 1 <= args.max_pages <= MAX_PAGES:
            parser.error(f"--max-pages must be between 1 and {MAX_PAGES}")
        if args.days is not None and not 1 <= args.days <= 180:
            parser.error("--days must be between 1 and 180")
        if not 1 <= args.timeout <= 60:
            parser.error("--timeout must be between 1 and 60")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "self-test":
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    result = run_search_auto(
        query=args.query,
        limit=args.limit,
        max_pages=args.max_pages,
        days=args.days,
        timeout=args.timeout,
        now=now_shanghai(),
        session_mode=args.session_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
