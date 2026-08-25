#!/usr/bin/env python3
"""Create an offline search route plan without invoking any backend."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

try:
    import idna as _idna_uts46
except ImportError:  # Fail closed for non-ASCII hosts when the helper is absent.
    _idna_uts46 = None


PLATFORM_SITES = {
    "github": "github.com",
    "zhihu": "zhihu.com",
    "wechat": "mp.weixin.qq.com",
    "xiaohongshu": "xiaohongshu.com",
    "douyin": "douyin.com",
    "toutiao": "toutiao.com",
    "x": "x.com",
    "bilibili": "bilibili.com",
    "youtube": "youtube.com",
    "xiaoyuzhou": "xiaoyuzhoufm.com",
    "weibo": "weibo.com",
}

PLATFORM_HINTS = (
    ("zhihu", (r"知乎", r"\bzhihu\b")),
    ("xiaohongshu", (r"小红书", r"\bxiaohongshu\b", r"\bxhs\b")),
    ("douyin", (r"抖音", r"\bdouyin\b")),
    ("toutiao", (r"今日头条", r"\btoutiao\b")),
    ("wechat", (r"微信公众号", r"微信文章", r"\bweixin\b", r"\bwechat\b")),
    ("weibo", (r"微博", r"\bweibo\b")),
    ("bilibili", (r"哔哩哔哩", r"B站", r"\bbilibili\b")),
    ("youtube", (r"\byoutube\b",)),
    ("xiaoyuzhou", (r"小宇宙", r"\bxiaoyuzhou\b")),
    ("github", (r"\bgithub\b", r"\bissue\b", r"\bpull request\b")),
    (
        "x",
        (
            r"推特",
            r"\btwitter\b",
            r"\bx\.com\b",
            r"(?<![A-Za-z])x\s*(?:上|平台|里的|中)",
        ),
    ),
)

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = Path(
    os.environ.get("YICHEN_SKILLS_ROOT", str(SKILL_DIR.parent))
).expanduser()
SCRIPTS_DIR = SKILL_DIR / "scripts"
AIHOT_PLATFORM = "aihot"
AIHOT_ADAPTER = str(SCRIPTS_DIR / "aihot_search.py")
ANYSEARCH_ADAPTER = str(SCRIPTS_DIR / "anysearch_adapter.py")
ZHIHU_ADAPTER = str(SCRIPTS_DIR / "zhihu_adapter.py")
FIRECRAWL_ADAPTER = str(SCRIPTS_DIR / "firecrawl_adapter.py")
YOUTUBE_ADAPTER = str(SCRIPTS_DIR / "youtube_search.py")
WEIBO_ADAPTER = str(SCRIPTS_DIR / "weibo_adapter.py")
X_RESEARCH_MERGER = str(SCRIPTS_DIR / "x_research_merge.py")
GROK_X_RESULT_ADAPTER = str(SCRIPTS_DIR / "grok_x_result_adapter.py")
ANYSEARCH_RUNTIME = Path(
    os.environ.get(
        "YICHEN_ANYSEARCH_RUNTIME_CONF",
        str(SKILLS_ROOT / "anysearch" / "runtime.conf"),
    )
).expanduser()
X_TOOL_MAX_RESULTS = 20
X_TOOL_MAX_HOURS = 168
X_RESEARCH_DEFAULT_MAX_SEARCHES = 8
X_RESEARCH_MAX_SEARCHES = 40
X_RESEARCH_WAVE_SIZE = 5
ZHIHU_SEARCH_MAX_RESULTS = 10
ZHIHU_BATCH_MAX_QUERIES = 5
ZHIHU_HOT_MAX_RESULTS = 30
WEIBO_SEARCH_MAX_RESULTS = 20
WEIBO_BATCH_MAX_QUERIES = 5
WEIBO_MAX_PAGES = 3
AI_TOPIC_PATTERNS = (
    r"(?<![A-Za-z])ai(?![A-Za-z])",
    r"人工智能",
    r"大模型",
    r"\bllm\b",
    r"\bopenai\b",
    r"\banthropic\b",
    r"\bclaude\b",
    r"\bgemini\b",
    r"\bdeepmind\b",
    r"\bchatgpt\b",
    r"\bgpt(?:-[\w.]+)?\b",
    r"\bsora\b",
    r"\bdeepseek\b",
    r"\bqwen\b",
    r"\bllama\b",
    r"\bmistral\b",
    r"\bxai\b",
    r"\bgrok\b",
    r"通义",
    r"豆包",
    r"月之暗面",
    r"智谱",
)
AI_FRESHNESS_PATTERNS = (
    r"今天|今日|当天|昨天|昨日|前天",
    r"最近|最新|过去|近期|这几天|这两天|这周|本周|一周",
    r"新闻|资讯|动态|日报|头条",
    r"发布|上线|更新|新东西|发生了什么|有什么新",
    r"today|latest|recent|news|daily|release|update",
)
AIHOT_EXPLICIT_PATTERNS = (r"\bai\s*hot\b", r"\baihot\b", r"AI 热点")

AIHOT_CATEGORY_PATTERNS = (
    ("paper", (r"论文", r"研究", r"paper")),
    ("ai-models", (r"大模型", r"模型发布", r"模型更新", r"model")),
    ("ai-products", (r"AI 产品", r"产品发布", r"产品更新", r"product")),
    ("industry", (r"行业", r"融资", r"收购", r"政策", r"industry")),
    ("tip", (r"技巧", r"教程", r"观点", r"prompt", r"tip")),
)

AIHOT_KEYWORD_PATTERNS = (
    r"OpenAI",
    r"Anthropic",
    r"Claude",
    r"Google(?: DeepMind)?",
    r"Gemini",
    r"Microsoft",
    r"Meta",
    r"Mistral",
    r"xAI",
    r"Grok",
    r"ChatGPT",
    r"GPT(?:-[\w.]+)?",
    r"Sora",
    r"DeepSeek",
    r"Qwen",
    r"Llama",
    r"RAG",
    r"MCP",
    r"Agent",
    r"通义",
    r"豆包",
    r"Kimi",
    r"MiniMax",
    r"智谱",
    r"GLM(?:-[\w.]+)?",
)


@dataclass(frozen=True)
class Request:
    queries: tuple[str, ...]
    platform: str
    mode: str
    depth: str
    input_kind: str
    limit: int
    days: int | None
    domain: str | None
    hybrid: bool
    login_approved: bool
    private_data: bool
    candidate_url: str | None
    candidate_from_search: bool
    verify_backend: str
    x_include_replies: bool
    x_include_reposts: bool
    x_language: str | None
    x_authors: tuple[str, ...]
    x_min_likes: int | None
    x_min_reposts: int | None
    x_min_replies: int | None
    x_min_views: int | None
    x_sort: str
    target_results: int | None
    max_searches: int


def detect_platform(queries: Iterable[str]) -> str:
    text = " ".join(queries)
    for platform, patterns in PLATFORM_HINTS:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return platform
    if is_aihot_intent(queries):
        return AIHOT_PLATFORM
    return "web"


def is_aihot_intent(queries: Iterable[str]) -> bool:
    """Return true only for explicit AI HOT or current-AI discovery intent."""
    text = " ".join(queries)
    if any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in AIHOT_EXPLICIT_PATTERNS
    ):
        return True
    has_ai_topic = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in AI_TOPIC_PATTERNS
    )
    has_freshness = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in AI_FRESHNESS_PATTERNS
    )
    return has_ai_topic and has_freshness


def infer_aihot_feed(query: str) -> str:
    if re.search(r"日报", query, flags=re.IGNORECASE):
        return "daily"
    if re.search(r"全部|完整|所有|全量|包括老的", query, flags=re.IGNORECASE):
        return "all"
    return "selected"


def infer_aihot_category(query: str) -> str | None:
    for category, patterns in AIHOT_CATEGORY_PATTERNS:
        if any(re.search(pattern, query, flags=re.IGNORECASE) for pattern in patterns):
            return category
    return None


def infer_aihot_keyword(query: str) -> str | None:
    for pattern in AIHOT_KEYWORD_PATTERNS:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def infer_aihot_days(query: str, requested_days: int | None) -> int:
    if requested_days is not None:
        return requested_days
    number_match = re.search(
        r"(?:过去|最近|近)?\s*([1-7])\s*天", query, flags=re.IGNORECASE
    )
    if number_match:
        return int(number_match.group(1))
    if re.search(r"一周|这周|本周|7\s*天", query, flags=re.IGNORECASE):
        return 7
    if re.search(r"最近|近期|这几天", query, flags=re.IGNORECASE):
        return 7
    if re.search(r"昨天|昨日", query, flags=re.IGNORECASE):
        return 2
    return 1


def infer_aihot_date(query: str, today: date | None = None) -> str | None:
    current = today or date.today()
    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", query)
    if iso_match:
        try:
            return date(*(int(value) for value in iso_match.groups())).isoformat()
        except ValueError:
            return None
    chinese_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", query)
    if chinese_match:
        try:
            return date(
                current.year,
                int(chinese_match.group(1)),
                int(chinese_match.group(2)),
            ).isoformat()
        except ValueError:
            return None
    if re.search(r"前天", query):
        return (current - timedelta(days=2)).isoformat()
    if re.search(r"昨天|昨日", query):
        return (current - timedelta(days=1)).isoformat()
    return None


def aihot_steps(request: Request) -> list[dict]:
    steps: list[dict] = []
    for query in request.queries:
        feed = infer_aihot_feed(query)
        argv = [
            "python3",
            AIHOT_ADAPTER,
            "--query",
            query,
            "--feed",
            feed,
            "--limit",
            str(min(request.limit, 100)),
        ]
        if feed == "daily":
            daily_date = infer_aihot_date(query)
            if daily_date:
                argv.extend(["--date", daily_date])
        else:
            argv.extend(["--days", str(infer_aihot_days(query, request.days))])
            category = infer_aihot_category(query)
            if category:
                argv.extend(["--category", category])
            keyword = infer_aihot_keyword(query)
            if keyword:
                argv.extend(["--keyword", keyword])
        steps.append(
            {
                "action": "invoke_existing_adapter",
                "skill_contract": "aihot",
                "backend": "aihot",
                "argv": argv,
            }
        )
    return steps


def is_url(value: str) -> bool:
    return (
        re.fullmatch(r"https?://[^\s]+", value.strip(), flags=re.IGNORECASE)
        is not None
    )


def _normalize_host_uts46(raw_host: str) -> str | None:
    """Normalize one route host without legacy IDNA2003 target changes."""

    host_input = raw_host.rstrip(".")
    if not host_input or "%" in host_input:
        return None
    try:
        literal = ipaddress.ip_address(host_input)
    except ValueError:
        literal = None
    if literal is not None:
        return str(literal).lower()

    if _idna_uts46 is None:
        if any(ord(character) > 0x7F for character in host_input):
            return None
        try:
            return host_input.encode("ascii").decode("ascii").lower()
        except UnicodeError:
            return None
    try:
        return _idna_uts46.encode(
            host_input,
            uts46=True,
            transitional=False,
            std3_rules=True,
        ).decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None


def is_public_http_url(value: str) -> bool:
    """Strict offline check for a literal public HTTP(S) site-map seed."""

    if not isinstance(value, str) or not value.strip():
        return False
    cleaned = value.strip()
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in cleaned):
        return False
    parsed = re.fullmatch(
        r"https?://([^/?#]+)(?:[/?#].*)?", cleaned, flags=re.IGNORECASE
    )
    if parsed is None:
        return False
    authority = parsed.group(1)
    if "@" in authority:
        return False
    port: int | None = None
    if authority.startswith("["):
        closing = authority.find("]")
        if closing <= 1:
            return False
        raw_host = authority[1:closing]
        remainder = authority[closing + 1 :]
        if remainder:
            if not remainder.startswith(":") or not remainder[1:].isdigit():
                return False
            port = int(remainder[1:])
    else:
        if "[" in authority or "]" in authority or authority.count(":") > 1:
            return False
        if ":" in authority:
            raw_host, port_text = authority.rsplit(":", 1)
            if not port_text.isdigit():
                return False
            port = int(port_text)
        else:
            raw_host = authority
    if port is not None and not 1 <= port <= 65535:
        return False
    host = _normalize_host_uts46(raw_host)
    if host is None:
        return False
    if not host or len(host) > 253:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return address.is_global
    if "." not in host:
        return False
    labels = host.split(".")
    if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
        return False
    return all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        is not None
        for label in labels
    )


def contains_url(value: str) -> bool:
    return re.search(r"https?://[^\s]+", value, flags=re.IGNORECASE) is not None


def handoff_content_archive(reason: str) -> dict:
    return {
        "schema_version": "1.0",
        "status": "handoff_required",
        "reason": reason,
        "authorization": "not_applicable",
        "route": None,
        "handoff_skill": "yichen-content-archive",
        "steps": [],
        "limitations": [
            "Known-URL reading, downloading, and archiving are outside unified-search."
        ],
    }


def firecrawl_steps(request: Request) -> list[dict]:
    if request.mode == "site-map":
        return [
            {
                "action": "invoke_existing_adapter",
                "backend": "firecrawl",
                "subcommand": "map",
                "argv": [
                    "python3",
                    FIRECRAWL_ADAPTER,
                    "map",
                    "--url",
                    request.queries[0],
                    "--limit",
                    str(request.limit),
                ],
            }
        ]
    if request.mode == "verify-candidate":
        return [
            {
                "action": "invoke_existing_adapter",
                "backend": "firecrawl",
                "subcommand": "scrape",
                "argv": [
                    "python3",
                    FIRECRAWL_ADAPTER,
                    "scrape",
                    "--candidate-from-search",
                    "<full-current-anysearch-candidate-json-or-@file>",
                ],
                "requested_candidate_url": request.candidate_url,
            }
        ]
    raise ValueError("Firecrawl supports only explicit site-map or candidate verification")


def anysearch_steps(request: Request, queries: list[str]) -> list[dict]:
    max_results = min(request.limit, 10)

    def adapter_step(subcommand: str, argv: list[str], **metadata: object) -> dict:
        return {
            "action": "invoke_existing_adapter",
            "backend": "anysearch",
            "skill_contract": "anysearch",
            "subcommand": subcommand,
            "argv": ["python3", ANYSEARCH_ADAPTER, subcommand, *argv],
            **metadata,
        }

    if request.mode == "verify-candidate":
        if request.candidate_url is None:
            raise ValueError("verify-candidate requires candidate_url")
        return [
            adapter_step(
                "verify",
                [
                    "--candidate-from-search",
                    "<full-current-anysearch-candidate-json-or-@file>",
                ],
                requested_candidate_url=request.candidate_url,
            )
        ]

    steps: list[dict] = []
    if request.domain:
        steps.extend(
            [
                {
                    "action": "read_runtime",
                    "path": str(ANYSEARCH_RUNTIME),
                    "field": "Command",
                },
                {
                    "action": "invoke_anysearch",
                    "subcommand": "get_sub_domains",
                    "argv": ["--domain", request.domain],
                },
            ]
        )

    if request.hybrid or request.mode == "batch" or len(queries) > 1:

        payloads: list[dict] = []
        for query in queries:
            general = {"query": query, "max_results": max_results}
            vertical = {
                **general,
                "domain": request.domain,
                "sub_domain": "<from-get_sub_domains>",
                "sub_domain_params": "<all-required-params>",
            }
            if request.hybrid:
                payloads.extend([general, vertical])
            elif request.domain:
                payloads.append(vertical)
            else:
                payloads.append(general)

        for offset in range(0, len(payloads), 5):
            payload = payloads[offset : offset + 5]
            steps.append(
                adapter_step(
                    "batch",
                    ["--queries", json.dumps(payload, ensure_ascii=False)],
                )
            )
    elif request.domain:
        steps.append(
            adapter_step(
                "search",
                [
                    queries[0],
                    "--max-results",
                    str(max_results),
                    "--domain",
                    request.domain,
                    "--sub-domain",
                    "<from-get_sub_domains>",
                    "--sub-domain-params",
                    "<all-required-params>",
                ],
            )
        )
    else:
        steps.append(
            adapter_step(
                "search",
                [queries[0], "--max-results", str(max_results)],
            )
        )
    return steps


def unique_queries(queries: Iterable[str]) -> list[str]:
    """Trim and case-insensitively deduplicate queries while preserving order."""
    seen: set[str] = set()
    unique: list[str] = []
    for raw_query in queries:
        query = raw_query.strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique


def zhihu_steps(request: Request) -> list[dict]:
    """Build independent calls to the allowlisted local Zhihu CLI adapter."""

    if request.mode == "hot":
        return [
            {
                "action": "invoke_existing_adapter",
                "backend": "zhihu-open-platform-cli",
                "skill_contract": "zhihu-open-platform-cli",
                "subcommand": "hot",
                "argv": [
                    "python3",
                    ZHIHU_ADAPTER,
                    "hot",
                    "--limit",
                    str(request.limit),
                ],
            }
        ]

    return [
        {
            "action": "invoke_existing_adapter",
            "backend": "zhihu-open-platform-cli",
            "skill_contract": "zhihu-open-platform-cli",
            "subcommand": "search",
            "query_index": index,
            "argv": [
                "python3",
                ZHIHU_ADAPTER,
                "search",
                "--query",
                query.strip(),
                "--limit",
                str(min(request.limit, ZHIHU_SEARCH_MAX_RESULTS)),
            ],
        }
        for index, query in enumerate(request.queries, start=1)
    ]


def weibo_steps(request: Request) -> list[dict]:
    """Build bounded calls to the anonymous-first, read-only Weibo adapter."""

    steps: list[dict] = []
    for index, query in enumerate(request.queries, start=1):
        argv = [
            "python3",
            WEIBO_ADAPTER,
            "search",
            "--query",
            query.strip(),
            "--limit",
            str(min(request.limit, WEIBO_SEARCH_MAX_RESULTS)),
            "--max-pages",
            str(WEIBO_MAX_PAGES),
            "--session-mode",
            "auto",
        ]
        if request.days is not None:
            argv.extend(["--days", str(request.days)])
        steps.append(
            {
                "action": "invoke_existing_adapter",
                "backend": "weibo-readonly-auto",
                "skill_contract": "weibo-readonly-auto",
                "subcommand": "search",
                "query_index": index,
                "execution": {
                    "mode": "serial",
                    "minimum_gap_seconds_after_step": 5,
                },
                "argv": argv,
            }
        )
    return steps


def normalized_x_authors(authors: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_author in authors:
        author = raw_author.strip().lstrip("@").lower()
        if not author or author in seen:
            continue
        seen.add(author)
        normalized.append(f"@{author}")
    return normalized


def has_x_option_overrides(request: Request) -> bool:
    return any(
        (
            request.depth != "quick",
            request.x_include_replies,
            request.x_include_reposts,
            request.x_language is not None,
            bool(request.x_authors),
            request.x_min_likes is not None,
            request.x_min_reposts is not None,
            request.x_min_replies is not None,
            request.x_min_views is not None,
            request.target_results is not None,
            request.max_searches != X_RESEARCH_DEFAULT_MAX_SEARCHES,
        )
    ) or request.x_sort != "relevance"


def x_criteria(request: Request) -> str:
    criteria: list[str] = []
    if request.x_include_reposts:
        criteria.append("Reposts/retweets may be included.")
    else:
        criteria.append(
            "Exclude reposts/retweets; original posts and quote posts are allowed."
        )
    if request.x_include_replies:
        criteria.append("Replies may be included when relevant.")
    else:
        criteria.append("Exclude replies.")

    authors = normalized_x_authors(request.x_authors)
    if authors:
        criteria.append(f"Only include posts authored by {', '.join(authors)}.")
    if request.x_language:
        criteria.append(f"Only include posts in language {request.x_language}.")

    thresholds = (
        ("likes", request.x_min_likes),
        ("reposts", request.x_min_reposts),
        ("replies", request.x_min_replies),
        ("views", request.x_min_views),
    )
    for metric, minimum in thresholds:
        if minimum is not None:
            criteria.append(
                f"Only include posts with verifiable {metric} greater than or equal to {minimum}."
            )

    sort_instruction = {
        "relevance": "Rank primarily by relevance, then recency and source quality.",
        "recent": "Rank newest matching posts first.",
        "engagement": (
            "Rank by verifiable total engagement, then views and recency; "
            "do not estimate missing metrics."
        ),
    }[request.x_sort]
    criteria.append(sort_instruction)
    criteria.append("Return exact x.com status URLs only; do not invent missing fields.")
    return " ".join(criteria)


def x_tool_step(
    *,
    query: str,
    request: Request,
    query_index: int,
    phase: str,
) -> dict:
    arguments: dict[str, object] = {
        "query": query,
        "max_results": min(request.limit, X_TOOL_MAX_RESULTS),
        "criteria": x_criteria(request),
        "allow_authenticated_fallback": request.login_approved,
    }
    if request.days is not None:
        arguments["hours"] = request.days * 24
    return {
        "action": "invoke_plugin_tool",
        "backend": "grok-consult",
        "tool": "search_x_with_grok",
        "arguments": arguments,
        "query_index": query_index,
        "research_phase": phase,
        "result_normalizer": {
            "script": GROK_X_RESULT_ADAPTER,
            "argv": [
                "python3",
                GROK_X_RESULT_ADAPTER,
                "--input",
                "-",
                "--query",
                query,
                "--call-index",
                str(query_index),
                "--phase",
                phase,
            ],
            "accepted_result_path": "x_post_time_verification.matched",
        },
        "primary_route": "official_grok_cli_account_quota",
        "account_oauth_used": True,
        "contains_read_only_chain": [
            "official_grok_cli_account_quota",
            "fxtwitter-public",
            "opencli",
            "xreach",
        ],
        "fxtwitter_when": "explicit_account_quota_exhausted_only",
        "authenticated_fallback_when": (
            "explicit_current_task_authorization"
            if request.login_approved
            else "disabled"
        ),
        "must_stop_without_fallback_when": [
            "authentication_error",
            "authorization_error",
            "invalid_request",
            "timeout",
            "network_error",
            "service_error",
            "unverified_native_search",
        ],
    }


def x_research_ready_wave_size(request: Request, queries: list[str]) -> int:
    per_call = min(request.limit, X_TOOL_MAX_RESULTS)
    target = request.target_results or per_call * len(queries)
    minimum_calls_for_target = math.ceil(target / per_call)
    return min(len(queries), X_RESEARCH_WAVE_SIZE, minimum_calls_for_target)


def x_research_protocol(request: Request, queries: list[str]) -> dict:
    per_call = min(request.limit, X_TOOL_MAX_RESULTS)
    target = request.target_results or per_call * len(queries)
    minimum_calls_for_target = math.ceil(target / per_call)
    remaining_search_budget = request.max_searches - len(queries)
    supplementary_template = x_tool_step(
        query="<one-new-focused-gap-query>",
        request=request,
        query_index=0,
        phase="supplementary",
    )
    supplementary_template["query_index"] = "<next-call-index>"
    supplementary_template["result_normalizer"]["argv"][7] = "<next-call-index>"
    ready_wave_size = x_research_ready_wave_size(request, queries)
    wave_slices: list[tuple[int, list[str]]] = [
        (0, queries[:ready_wave_size])
    ]
    for offset in range(ready_wave_size, len(queries), X_RESEARCH_WAVE_SIZE):
        wave_slices.append(
            (offset, queries[offset : offset + X_RESEARCH_WAVE_SIZE])
        )
    initial_waves: list[dict] = []
    for wave_index, (offset, wave_queries) in enumerate(wave_slices, start=1):
        wave_steps = [
            x_tool_step(
                query=query,
                request=request,
                query_index=offset + index,
                phase="initial",
            )
            for index, query in enumerate(wave_queries, start=1)
        ]
        initial_waves.append(
            {
                "wave_index": wave_index,
                "status": "ready" if wave_index == 1 else "gated",
                "queries": wave_queries,
                "step_count": len(wave_steps),
                "execute_from": (
                    "top_level_steps" if wave_index == 1 else "steps_after_gate"
                ),
                "unlock_when": (
                    None
                    if wave_index == 1
                    else "previous_wave_merged_and_no_stop_condition_met"
                ),
                "steps": [] if wave_index == 1 else wave_steps,
            }
        )
    return {
        "strategy": "bounded_multi_query_x_research",
        "initial_query_count": len(queries),
        "per_call_max_results": per_call,
        "target_unique_results": target,
        "minimum_calls_for_target_before_duplicates": minimum_calls_for_target,
        "additional_focused_queries_needed_for_capacity": max(
            0, minimum_calls_for_target - len(queries)
        ),
        "max_searches": request.max_searches,
        "remaining_search_budget": remaining_search_budget,
        "execution_wave_size": X_RESEARCH_WAVE_SIZE,
        "merge_after_each_wave": True,
        "ready_initial_searches": ready_wave_size,
        "gated_initial_searches": max(0, len(queries) - ready_wave_size),
        "initial_waves": initial_waves,
        "max_gap_fill_rounds": 1,
        "max_supplementary_searches": remaining_search_budget,
        "gap_fill_round_semantics": (
            "The single gap-fill round may contain multiple new focused queries, "
            "but never more than the remaining outer-search budget."
        ),
        "dedupe_key": "tweet_id_then_canonical_url",
        "accepted_grok_result_path": "x_post_time_verification.matched",
        "normalization": {
            "script": GROK_X_RESULT_ADAPTER,
            "rule": (
                "Map only time-matched Grok records into the candidate schema before "
                "merging; never merge excluded_outside_window records."
            ),
        },
        "merge": {
            "script": X_RESEARCH_MERGER,
            "sort": request.x_sort,
            "deterministic_filters": {
                "include_reposts": request.x_include_reposts,
                "include_replies": request.x_include_replies,
                "language": request.x_language,
                "authors": normalized_x_authors(request.x_authors),
                "min_likes": request.x_min_likes,
                "min_reposts": request.x_min_reposts,
                "min_replies": request.x_min_replies,
                "min_views": request.x_min_views,
            },
        },
        "gap_analysis": [
            "missing subtopic or source type",
            "missing first-party or independent evidence",
            "language or author coverage gap",
            "insufficient unique candidates after tweet_id deduplication",
        ],
        "supplementary_search_template": supplementary_template,
        "stop_conditions": [
            "target_unique_results_reached",
            "one_gap_fill_round_adds_no_unique_candidates",
            "no_material_coverage_gap_remains",
            "max_searches_reached",
            "any_non_quota_primary_route_failure",
        ],
    }


def native_steps(platform: str, request: Request) -> list[dict]:
    query = request.queries[0]
    limit = request.limit
    days = request.days if request.days is not None else 1
    if platform == "x":
        queries = unique_queries(request.queries)
        if request.depth == "research":
            queries = queries[: x_research_ready_wave_size(request, queries)]
        return [
            x_tool_step(
                query=x_query,
                request=request,
                query_index=index,
                phase="initial",
            )
            for index, x_query in enumerate(queries, start=1)
        ]
    if platform == "youtube":
        command = ["python3", YOUTUBE_ADAPTER]
        if request.mode == "channel":
            command.extend(["channel", query])
        else:
            command.extend(["search", query])
        command.extend(["--limit", str(limit), "--backend", "auto"])
        if request.days not in {None, 0}:
            command.extend(["--days", str(request.days)])
        return [{"action": "invoke_existing_adapter", "argv": command}]
    commands = {
        "github": [
            "gh",
            "search",
            "repos",
            "--visibility",
            "public",
            "--limit",
            str(limit),
            "--",
            query,
        ],
        "wechat": [
            "opencli",
            "weixin",
            "search",
            query,
            "--page",
            "1",
            "--limit",
            str(limit),
        ],
        "xiaohongshu": [
            "opencli",
            "xiaohongshu",
            "search",
            query,
            "--days",
            str(days),
            "--content",
            "all",
            "--limit",
            str(min(limit, 20)),
            "--enrich",
            "--window",
            "background",
            "--site-session",
            "ephemeral",
            "--keep-tab",
            "false",
            "-f",
            "yaml",
        ],
        "douyin": [
            "opencli",
            "douyin",
            "search",
            query,
            "--days",
            str(days),
            "--content",
            "all",
            "--limit",
            str(min(limit, 30)),
            "--enrich",
            "--window",
            "background",
            "--site-session",
            "ephemeral",
            "--keep-tab",
            "false",
            "-f",
            "yaml",
        ],
        "toutiao": [
            "opencli",
            "toutiao",
            "search",
            query,
            "--days",
            str(days),
            "--limit",
            str(min(limit, 50)),
            "-f",
            "yaml",
        ],
        "bilibili": [
            "bili",
            "search",
            query,
            "--type",
            "video",
            "--page",
            "1",
            "-n",
            str(limit),
            "--json",
        ],
    }
    step = {"action": "invoke_existing_adapter", "argv": commands[platform]}
    if platform in {"xiaohongshu", "douyin"}:
        step["execution"] = {
            "mode": "serial",
            "browser_session": "ephemeral",
            "minimum_gap_seconds_after_step": 5,
        }
    return [step]


def plan(request: Request) -> dict:
    if request.private_data:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "reason": "private collections, feeds, messages, drafts, and account backends are out of scope",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": ["This skill only searches public or authenticated-public content."],
        }

    if request.hybrid and not request.domain:
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "hybrid search requires an AnySearch vertical domain",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if request.hybrid and request.mode not in {"search", "batch"}:
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "hybrid search supports only search and batch modes",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if request.mode != "search" and has_x_option_overrides(request):
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "X depth, filters, sorting, and research budgets require --mode search",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }

    if request.mode == "site-map":
        if len(request.queries) != 1 or not is_public_http_url(request.queries[0]):
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "site-map requires exactly one explicit HTTP(S) seed URL",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.platform not in {"auto", "web"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "site-map supports only the public web platform",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if not 1 <= request.limit <= 100:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "site-map limit must be between 1 and 100",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.domain or request.hybrid or request.days is not None:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "site-map cannot be combined with search domains, hybrid mode, or time filters",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": "web",
                "backend": "firecrawl",
                "mode": "site-map",
                "reason": "explicit_site_map",
                "login_state_used": False,
            },
            "steps": firecrawl_steps(request),
            "limitations": [
                "Firecrawl Map is explicit and bounded to the supplied public origin and path; it is never the default search route.",
                "Map discovers site links but does not prove exhaustive indexing or verify page claims.",
            ],
        }

    queries_contain_url = any(contains_url(query) for query in request.queries)
    if request.input_kind == "known-url":
        return handoff_content_archive(
            "the request explicitly classifies its input as known content"
        )
    if (
        queries_contain_url
        and request.input_kind != "url-seed"
        and not (request.mode == "channel" and request.platform == "youtube")
    ):
        return handoff_content_archive(
            "a directly supplied known URL is not a search query"
        )
    if request.input_kind == "url-seed" and not queries_contain_url:
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "input_kind url-seed requires a URL in the search query",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }

    if request.mode == "verify-candidate":
        if request.verify_backend not in {"anysearch", "firecrawl"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "verify backend must be anysearch or firecrawl",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.platform not in {"auto", "web"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "candidate verification supports only the public web platform",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if not request.candidate_url or not is_url(request.candidate_url):
            return handoff_content_archive(
                "candidate verification requires a valid candidate URL"
            )
        if not request.candidate_from_search:
            return handoff_content_archive(
                "the URL was not marked as a candidate produced by the current search"
            )
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": request.platform if request.platform != "auto" else "web",
                "backend": request.verify_backend,
                "mode": "verify-candidate",
                "reason": (
                    "verify_current_candidate_with_firecrawl"
                    if request.verify_backend == "firecrawl"
                    else "verify_candidate_from_current_search"
                ),
                "login_state_used": False,
            },
            "steps": (
                firecrawl_steps(request)
                if request.verify_backend == "firecrawl"
                else anysearch_steps(request, list(request.queries))
            ),
            "limitations": [
                (
                    "Firecrawl Scrape accepts only a complete current AnySearch candidate with a valid short-lived receipt; it never accepts a bare URL."
                    if request.verify_backend == "firecrawl"
                    else "Use extract only for original verification or light enrichment; do not download or archive."
                )
            ],
        }

    platform = detect_platform(request.queries) if request.platform == "auto" else request.platform
    if (
        request.mode == "batch"
        and request.platform == "auto"
        and platform not in {"zhihu", "weibo"}
    ):
        platform = "web"
    x_specific_options = has_x_option_overrides(request)
    if x_specific_options and platform != "x":
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "X research filters and budgets require platform x",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if request.depth == "research" and platform != "x":
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "research depth is currently supported only for native X search",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if platform == "x":
        x_queries = unique_queries(request.queries)
        if not x_queries:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X search requires at least one non-empty query",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if (request.domain or request.hybrid) and x_specific_options:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X-specific depth, filters, sorting, and budgets cannot be combined with AnySearch domain routing",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        invalid_thresholds = [
            name
            for name, value in (
                ("x_min_likes", request.x_min_likes),
                ("x_min_reposts", request.x_min_reposts),
                ("x_min_replies", request.x_min_replies),
                ("x_min_views", request.x_min_views),
            )
            if value is not None and value < 0
        ]
        if invalid_thresholds:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X engagement thresholds must be non-negative",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [f"Invalid fields: {', '.join(invalid_thresholds)}"],
            }
        if request.x_language is not None and not request.x_language.strip():
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X language filter must be non-empty",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.x_sort not in {"relevance", "recent", "engagement"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X sort must be relevance, recent, or engagement",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.days is not None and not 1 <= request.days <= 7:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "X --days must be between 1 and 7 because Grok hours is limited to 168",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.depth != "research" and request.target_results is not None:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "--target-results requires X research depth",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if (
            request.depth != "research"
            and request.max_searches != X_RESEARCH_DEFAULT_MAX_SEARCHES
        ):
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "--max-searches requires X research depth",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.depth == "research":
            if not 1 <= request.max_searches <= X_RESEARCH_MAX_SEARCHES:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": f"X research --max-searches must be between 1 and {X_RESEARCH_MAX_SEARCHES}",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [],
                }
            if request.target_results is not None and not 1 <= request.target_results <= 800:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "X research target results must be between 1 and 800",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [],
                }
            if request.mode != "search":
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "X research depth requires --mode search",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [],
                }
            if request.max_searches < 3:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "X research depth requires a budget of at least 3 searches",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [],
                }
            if len(x_queries) < 3:
                return {
                    "schema_version": "1.0",
                    "status": "needs_query_expansion",
                    "reason": "X research depth requires at least 3 focused independent queries",
                    "authorization": "not_applicable",
                    "route": {
                        "platform": "x",
                        "backend": "grok-consult",
                        "mode": "search",
                        "depth": "research",
                        "reason": "query_decomposition_required",
                        "login_state_used": True,
                    },
                    "query_expansion": {
                        "minimum_queries": 3,
                        "maximum_queries": request.max_searches,
                        "preserve_original_scope": True,
                        "suggested_axes": [
                            "core topic and synonyms",
                            "first-party announcements or primary sources",
                            "technical evidence, benchmarks, or demonstrations",
                            "independent analysis, criticism, or failure reports",
                            "real-world adoption or user experience",
                        ],
                    },
                    "steps": [],
                    "limitations": [
                        "Create focused queries without broadening the user's topic, then rerun the offline router with repeated --query arguments."
                    ],
                }
            if len(x_queries) > request.max_searches:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "initial X queries exceed --max-searches",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [],
                }
            target = request.target_results or min(
                len(x_queries) * min(request.limit, X_TOOL_MAX_RESULTS),
                request.max_searches * X_TOOL_MAX_RESULTS,
            )
            required_calls = math.ceil(target / min(request.limit, X_TOOL_MAX_RESULTS))
            if target > request.max_searches * X_TOOL_MAX_RESULTS or required_calls > request.max_searches:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "target results exceed the bounded X research search budget",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [
                        f"At most {request.max_searches * X_TOOL_MAX_RESULTS} result slots are possible with {request.max_searches} searches."
                    ],
                }
    if request.mode == "channel" and platform != "youtube":
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "channel mode is currently supported only for YouTube",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if request.mode == "hot" and platform != "zhihu":
        return {
            "schema_version": "1.0",
            "status": "invalid_request",
            "reason": "hot mode is supported only for explicit or auto-detected Zhihu",
            "authorization": "not_applicable",
            "route": None,
            "steps": [],
            "limitations": [],
        }
    if platform == "zhihu":
        if request.mode not in {"search", "batch", "hot"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Zhihu supports only search, batch, and explicit hot modes",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.domain or request.hybrid or request.days is not None:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Zhihu CLI routes cannot be combined with AnySearch domains, hybrid mode, or time filters",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if any(not query.strip() for query in request.queries):
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Zhihu search queries must be non-empty",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.mode in {"search", "hot"} and len(request.queries) != 1:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": f"Zhihu {request.mode} mode requires exactly one --query",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.mode == "batch" and not 1 <= len(request.queries) <= ZHIHU_BATCH_MAX_QUERIES:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Zhihu batch mode accepts between 1 and 5 independent queries",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.limit < 1 or (
            request.mode == "hot" and request.limit > ZHIHU_HOT_MAX_RESULTS
        ):
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": (
                    "Zhihu hot limit must be between 1 and 30"
                    if request.mode == "hot"
                    else "Zhihu search limit must be positive"
                ),
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.mode == "hot":
            limitations = [
                "Zhihu hot-list entries are discovery candidates, not verified original content.",
                "The hot list is a current ranking snapshot, not exhaustive event coverage.",
                "The adapter invokes the official hot-list command without sending the routing query text.",
            ]
        else:
            limitations = [
                "Zhihu results are discovery candidates, not verified original content.",
                "The configured Zhihu CLI search surface currently exposes no pagination or time filter.",
                "The query is sent to Zhihu through the separately installed CLI runtime.",
            ]
        if request.mode in {"search", "batch"} and request.limit > ZHIHU_SEARCH_MAX_RESULTS:
            limitations.append(
                "The configured Zhihu CLI search returns at most 10 candidates per query; every adapter call clamps --limit to 10."
            )
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": "zhihu",
                "backend": "zhihu-open-platform-cli",
                "mode": request.mode,
                "reason": (
                    "zhihu_cli_hot_list"
                    if request.mode == "hot"
                    else "zhihu_cli_native_search"
                ),
                "login_state_used": True,
            },
            "steps": zhihu_steps(request),
            "limitations": limitations,
        }
    if platform == "weibo":
        if request.mode not in {"search", "batch"}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo supports only search and batch modes",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.domain or request.hybrid:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "The bounded Weibo adapter route cannot be combined with AnySearch domains or hybrid mode",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if any(
            not query.strip() or len(query.strip()) > 200 for query in request.queries
        ):
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo search queries must contain between 1 and 200 characters",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.mode == "search" and len(request.queries) != 1:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo search mode requires exactly one --query; use batch for multiple queries",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.mode == "batch" and not 1 <= len(request.queries) <= WEIBO_BATCH_MAX_QUERIES:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo batch mode accepts between 1 and 5 independent queries",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.days is not None and not 1 <= request.days <= 180:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo --days must be between 1 and 180",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.limit < 1:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "Weibo search limit must be positive",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        limitations = [
            "Weibo results are discovery candidates, not verified originals or an exhaustive native index.",
            "The adapter tries an ephemeral anonymous visitor session first; only an access-gate failure may trigger one bounded read-only OpenCLI search through the existing Chrome session.",
            "OpenCLI handles the browser session directly; Cookie values are never passed to, printed by, or persisted by the adapter.",
            "Every query is bounded to 3 pages and 20 candidates with a 5-8 second inter-request delay; comments, profiles, and media are not fetched.",
            "The browser fallback is search-only and cannot call publish, delete, comments, favorites, feed, profile, or other account commands.",
        ]
        if request.days is not None:
            limitations.append(
                "Weibo --days is a client-side filter over the bounded returned pages, not a server-side or exhaustive date search."
            )
        if request.limit > WEIBO_SEARCH_MAX_RESULTS:
            limitations.append(
                "The Weibo adapter returns at most 20 candidates per query; every adapter call clamps --limit to 20."
            )
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": "weibo",
                "backend": "weibo-readonly-auto",
                "mode": request.mode,
                "reason": "public_weibo_anonymous_then_readonly_browser_fallback",
                "login_state_used": False,
                "login_state_use": "conditional_on_anonymous_access_gate_failure",
            },
            "steps": weibo_steps(request),
            "limitations": limitations,
        }
    limitations: list[str] = []
    if request.input_kind == "url-seed":
        limitations.append(
            "The URL is used only as a discovery seed; this plan does not read, download, or archive the URL itself."
        )
    if request.days is not None:
        if platform in {"xiaohongshu", "douyin"} and request.days not in {0, 1, 7, 180}:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "xiaohongshu and douyin --days must be one of 0, 1, 7, or 180",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if platform == "toutiao" and not 1 <= request.days <= 30:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "toutiao --days must be between 1 and 30",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }

    if platform == AIHOT_PLATFORM:
        if request.domain:
            return {
                "schema_version": "1.0",
                "status": "invalid_request",
                "reason": "AI HOT does not support AnySearch vertical domains",
                "authorization": "not_applicable",
                "route": None,
                "steps": [],
                "limitations": [],
            }
        if request.days is not None and not 1 <= request.days <= 7:
            if request.platform == "auto":
                platform = "web"
                limitations.append(
                    "AI HOT item windows are limited to the latest 7 days; this longer auto request uses AnySearch instead."
                )
            else:
                return {
                    "schema_version": "1.0",
                    "status": "invalid_request",
                    "reason": "AI HOT item windows must be between 1 and 7 days",
                    "authorization": "not_applicable",
                    "route": None,
                    "steps": [],
                    "limitations": [
                        "Use a dated AI HOT daily archive for older material or switch to public web search."
                    ],
                }
        else:
            return {
                "schema_version": "1.0",
                "status": "ready",
                "authorization": "not_required",
                "route": {
                    "platform": "web",
                    "backend": "aihot",
                    "mode": request.mode,
                    "reason": "ai_realtime_discovery",
                    "login_state_used": False,
                },
                "steps": aihot_steps(request),
                "limitations": [
                    "AI HOT is a curated discovery index, not an exhaustive web index.",
                    "AI HOT summaries may be AI-generated; verify the original URL before citing facts.",
                    "The item endpoint covers at most the latest 7 days; older material requires dated daily archives.",
                ],
            }

    if request.mode == "batch" or request.domain or platform == "web":
        queries = list(request.queries)
        route_reason = "public_web_default"
        if request.hybrid:
            route_reason = "public_web_general_plus_vertical"
            limitations.append(
                "Hybrid mode emits one general and one vertical request for every original query."
            )
        if request.mode == "batch" and platform in PLATFORM_SITES:
            site = PLATFORM_SITES[platform]
            queries = [f"site:{site} {query}" for query in queries]
            route_reason = "platform_batch_via_public_web_index"
            limitations.append(
                "Public site-index results are not equivalent to the platform's native or complete index."
            )
        if request.limit > 10:
            limitations.append(
                "AnySearch returns at most 10 candidates per query; the route plan clamps max_results to 10."
            )
        if request.days is not None:
            limitations.append(
                "The generic AnySearch route does not translate --days; express the time range in the query or discovered vertical parameters."
            )
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": platform,
                "backend": "anysearch",
                "mode": request.mode,
                "reason": route_reason,
                "login_state_used": False,
            },
            "steps": anysearch_steps(request, queries),
            "limitations": limitations,
        }

    if platform == "xiaoyuzhou":
        query = f"site:{PLATFORM_SITES[platform]} {request.queries[0]}"
        return {
            "schema_version": "1.0",
            "status": "ready",
            "authorization": "not_required",
            "route": {
                "platform": platform,
                "backend": "anysearch",
                "mode": "search",
                "reason": "no_native_full_site_keyword_search",
                "login_state_used": False,
            },
            "steps": anysearch_steps(request, [query]),
            "limitations": [
                "This is public web discovery, not Xiaoyuzhou's complete native index.",
                *(
                    [
                        "AnySearch returns at most 10 candidates per query; the route plan clamps max_results to 10."
                    ]
                    if request.limit > 10
                    else []
                ),
            ],
        }

    backend = {
        "github": "gh",
        "wechat": "opencli-weixin-public",
        "xiaohongshu": "opencli",
        "douyin": "opencli",
        "toutiao": "opencli-toutiao-anonymous",
        "x": "grok-consult",
        "bilibili": "bili-cli",
        "youtube": "youtube-public-search",
    }.get(platform)
    if backend is None:
        raise ValueError(f"Unsupported platform: {platform}")

    if platform == "toutiao":
        limitations.append("Single keyword, low frequency, current public non-video results only.")
    if platform == "github":
        limitations.append(
            "The command forces --visibility public; gh may still use its local authentication only to access GitHub's public API."
        )
    if platform == "x":
        limitations.extend(
            [
                "Every X keyword search starts with official Grok CLI account OAuth and native x_search.",
                "Only explicit Grok account quota or usage-limit exhaustion may enter anonymous FxTwitter.",
                "Authentication, authorization, timeout, network, service, zero-result, and unverified-search failures must stop without FxTwitter fallback.",
                "After an eligible quota fallback, FxTwitter remains a third-party public index and is not an official or exhaustive X search.",
                (
                    "The user explicitly authorized authenticated OpenCLI/xreach fallback for this current task."
                    if request.login_approved
                    else "Authenticated OpenCLI/xreach fallback is disabled; stop and request current-task authorization before enabling it."
                ),
                "Repost/reply, author, language, engagement, and sorting criteria guide Grok selection; the offline merger reapplies only fields that are actually present and never invents missing metrics.",
                "Native Grok matched records normally provide URL, author handle, and decoded time but not structured engagement; deterministic minimum-engagement filters require candidates that actually contain those metrics.",
            ]
        )
        if request.limit > X_TOOL_MAX_RESULTS:
            limitations.append(
                "search_x_with_grok returns at most 20 candidates per call; each planned call clamps max_results to 20."
            )
        if not request.x_include_reposts:
            limitations.append(
                "Reposts are excluded by the search criteria and again by the merger when a candidate is explicitly marked as a repost."
            )
        if not request.x_include_replies:
            limitations.append(
                "Replies are excluded by the search criteria and again by the merger when a candidate is explicitly marked as a reply."
            )

    if platform in {"xiaohongshu", "douyin"}:
        limitations.extend(
            [
                "The existing Chrome login state may be used automatically only for bounded read-only public search; no per-run approval is required.",
                "The route runs one keyword at a time in a background ephemeral session, releases the tab, and returns at most 20 Xiaohongshu or 30 Douyin candidates.",
                "The platform --days control is a discovery filter, not a strict time-window guarantee; consumers with a strict window must recheck returned published_at values client-side.",
                "Posting, commenting, liking, collecting, following, messaging, account changes, private feeds, private collections, and verification handling are outside this route and require a separate explicit current-turn request.",
            ]
        )

    result = {
        "schema_version": "1.0",
        "status": "ready",
        "authorization": (
            "current_turn_authenticated_fallback_authorized"
            if platform == "x" and request.login_approved
            else "fallback_requires_current_turn_authorization"
            if platform == "x"
            else "not_required"
        ),
        "route": {
            "platform": platform,
            "backend": backend,
            "mode": request.mode if platform == "x" else "search",
            **({"depth": request.depth} if platform == "x" else {}),
            "reason": (
                "grok_bounded_multi_query_research"
                if platform == "x" and request.depth == "research"
                else "grok_native_x_search_primary"
                if platform == "x"
                else "platform_native_search"
            ),
            "login_state_used": platform in {"github", "xiaohongshu", "douyin", "x"},
            **(
                {"authenticated_fallback_allowed": request.login_approved}
                if platform == "x"
                else {}
            ),
        },
        "steps": native_steps(platform, request),
        "limitations": limitations,
    }
    if platform == "x" and request.depth == "research":
        result["research"] = x_research_protocol(
            request, unique_queries(request.queries)
        )
    return result


def parse_args() -> Request:
    parser = argparse.ArgumentParser(
        description="Create an offline route plan; never invokes a search backend."
    )
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument(
        "--platform",
        default="auto",
        choices=("auto", "web", AIHOT_PLATFORM, *PLATFORM_SITES.keys()),
    )
    parser.add_argument(
        "--mode",
        choices=("search", "batch", "hot", "channel", "verify-candidate", "site-map"),
        default="search",
    )
    parser.add_argument(
        "--depth",
        choices=("quick", "research"),
        default="quick",
        help=(
            "X only: quick runs each supplied query once; research adds a bounded "
            "multi-query, dedupe, and one-round gap-fill protocol."
        ),
    )
    parser.add_argument(
        "--input-kind",
        choices=("auto", "keyword", "url-seed", "known-url"),
        default="auto",
        help=(
            "Classify URLs safely: known-url hands off to content archive; "
            "url-seed keeps a URL inside a discovery query."
        ),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--days", type=int)
    parser.add_argument("--domain")
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help=(
            "With --domain, emit both general-web and vertical-domain searches "
            "for every original query."
        ),
    )
    parser.add_argument(
        "--login-approved",
        action="store_true",
        help=(
            "X only: assert that the user explicitly authorized authenticated "
            "OpenCLI/xreach fallback in the current task. It has no effect on "
            "other routes."
        ),
    )
    parser.add_argument("--private-data", action="store_true")
    parser.add_argument("--candidate-url")
    parser.add_argument(
        "--candidate-from-search",
        action="store_true",
        help="Assert that --candidate-url came from the current unified-search result set.",
    )
    parser.add_argument(
        "--verify-backend",
        choices=("anysearch", "firecrawl"),
        default="anysearch",
        help="Explicit backend for verify-candidate; Firecrawl is never selected by ordinary search.",
    )
    parser.add_argument("--x-include-replies", action="store_true")
    parser.add_argument("--x-include-reposts", action="store_true")
    parser.add_argument("--x-language")
    parser.add_argument("--x-author", action="append", default=[])
    parser.add_argument("--x-min-likes", type=int)
    parser.add_argument("--x-min-reposts", type=int)
    parser.add_argument("--x-min-replies", type=int)
    parser.add_argument("--x-min-views", type=int)
    parser.add_argument(
        "--x-sort",
        choices=("relevance", "recent", "engagement"),
        default="relevance",
    )
    parser.add_argument(
        "--target-results",
        type=int,
        help="X research only: global unique-candidate target after deduplication.",
    )
    parser.add_argument(
        "--max-searches",
        type=int,
        default=X_RESEARCH_DEFAULT_MAX_SEARCHES,
        help="X research only: maximum number of outer search_x_with_grok calls.",
    )
    args = parser.parse_args()
    maximum_limit = (
        100
        if args.mode == "site-map"
        else ZHIHU_HOT_MAX_RESULTS
        if args.mode == "hot"
        else 50
    )
    if not 1 <= args.limit <= maximum_limit:
        parser.error(f"--limit must be between 1 and {maximum_limit}")
    if args.days is not None and not 0 <= args.days <= 180:
        parser.error("--days must be between 0 and 180")
    for option_name in (
        "x_min_likes",
        "x_min_reposts",
        "x_min_replies",
        "x_min_views",
    ):
        option_value = getattr(args, option_name)
        if option_value is not None and option_value < 0:
            parser.error(f"--{option_name.replace('_', '-')} must be non-negative")
    if args.target_results is not None and not 1 <= args.target_results <= 800:
        parser.error("--target-results must be between 1 and 800")
    if not 1 <= args.max_searches <= X_RESEARCH_MAX_SEARCHES:
        parser.error(
            f"--max-searches must be between 1 and {X_RESEARCH_MAX_SEARCHES}"
        )
    if args.x_language is not None:
        args.x_language = args.x_language.strip()
        if not args.x_language or len(args.x_language) > 35:
            parser.error("--x-language must be a non-empty language label")
    if args.mode == "verify-candidate":
        if len(args.query) != 1:
            parser.error("--mode verify-candidate requires exactly one source --query")
        if not args.candidate_url:
            parser.error("--mode verify-candidate requires --candidate-url")
    elif args.mode == "site-map":
        if len(args.query) != 1:
            parser.error("--mode site-map requires exactly one URL --query")
        if not is_public_http_url(args.query[0]):
            parser.error("--mode site-map requires a public HTTP(S) URL --query")
        if args.candidate_url or args.candidate_from_search:
            parser.error("site-map does not accept candidate verification flags")
    elif args.candidate_url or args.candidate_from_search:
        parser.error(
            "--candidate-url and --candidate-from-search require --mode verify-candidate"
        )
    return Request(
        queries=tuple(args.query),
        platform=args.platform,
        mode=args.mode,
        depth=args.depth,
        input_kind=args.input_kind,
        limit=args.limit,
        days=args.days,
        domain=args.domain,
        hybrid=args.hybrid,
        login_approved=args.login_approved,
        private_data=args.private_data,
        candidate_url=args.candidate_url,
        candidate_from_search=args.candidate_from_search,
        verify_backend=args.verify_backend,
        x_include_replies=args.x_include_replies,
        x_include_reposts=args.x_include_reposts,
        x_language=args.x_language,
        x_authors=tuple(args.x_author),
        x_min_likes=args.x_min_likes,
        x_min_reposts=args.x_min_reposts,
        x_min_replies=args.x_min_replies,
        x_min_views=args.x_min_views,
        x_sort=args.x_sort,
        target_results=args.target_results,
        max_searches=args.max_searches,
    )


def main() -> int:
    request = parse_args()
    print(json.dumps(plan(request), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
