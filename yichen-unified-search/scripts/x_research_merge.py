#!/usr/bin/env python3
"""Merge unified X candidate envelopes without network or persistent state.

The reducer is deliberately backend-agnostic.  It accepts one or more schema
1.0 candidate envelopes, groups duplicate X posts, applies deterministic
filters/sorts, and emits another schema 1.0 envelope.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO
from urllib.parse import urlsplit, urlunsplit


BACKEND = "x-research-merge"
SCHEMA_VERSION = "1.0"
STATUS_ID_RE = re.compile(r"/status(?:es)?/(\d+)(?:[/?#]|$)", re.IGNORECASE)
PUBLIC_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
CANDIDATE_ID_RE = re.compile(
    r"^(?:x|twitter|tweet|status)(?::[^:]+)*:(\d+)$", re.IGNORECASE
)

UNKNOWN_REPOST_LIMITATION = (
    "Repost status is unknown; the candidate was retained because no explicit "
    "repost marker was present."
)
UNKNOWN_REPLY_LIMITATION = (
    "Reply status is unknown; the candidate was retained because no explicit "
    "reply marker was present."
)
ENGAGEMENT_FORMULA = "likes + reposts + replies"


class MergeError(RuntimeError):
    """A safe, structured reducer error."""

    def __init__(self, category: str, message: str, source: str | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.source = source


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _append_limitation(candidate: dict[str, Any], message: str) -> None:
    limitations = candidate.get("limitations")
    if not isinstance(limitations, list):
        limitations = []
        candidate["limitations"] = limitations
    if message not in limitations:
        limitations.append(message)


def _status_id_from_url(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    match = STATUS_ID_RE.search(text)
    return match.group(1) if match else None


def _public_x_url(value: Any) -> bool:
    text = _text(value)
    if text is None:
        return False
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in PUBLIC_X_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port is None
    )


def _numeric_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    text = _text(value)
    if text is None:
        return None
    if text.isdigit():
        return str(int(text))
    prefixed = CANDIDATE_ID_RE.fullmatch(text)
    if prefixed:
        return str(int(prefixed.group(1)))
    return _status_id_from_url(text)


def tweet_id(candidate: dict[str, Any]) -> str | None:
    """Return a stable tweet ID using the documented priority order."""

    provenance = candidate.get("provenance")
    if isinstance(provenance, dict):
        source_id = _numeric_id(provenance.get("source_id"))
        if source_id is not None:
            return source_id

    candidate_id = candidate.get("candidate_id")
    direct = _numeric_id(candidate_id)
    if direct is not None:
        return direct
    candidate_id_text = _text(candidate_id)
    if candidate_id_text is not None:
        match = CANDIDATE_ID_RE.fullmatch(candidate_id_text)
        if match:
            return str(int(match.group(1)))

    for field in ("canonical_url", "url"):
        status_id = _status_id_from_url(candidate.get(field))
        if status_id is not None:
            return str(int(status_id))
    return None


def _observed_tweet_ids(candidate: dict[str, Any]) -> set[str]:
    """Collect every explicit tweet identity before selecting a merge key."""

    observed: set[str] = set()
    provenance = candidate.get("provenance")
    if isinstance(provenance, dict):
        if (value := _numeric_id(provenance.get("source_id"))) is not None:
            observed.add(value)
    if (value := _numeric_id(candidate.get("candidate_id"))) is not None:
        observed.add(value)
    platform_fields = candidate.get("platform_fields")
    if isinstance(platform_fields, dict):
        x_fields = platform_fields.get("x")
        if isinstance(x_fields, dict):
            if (value := _numeric_id(x_fields.get("tweet_id"))) is not None:
                observed.add(value)
    for field in ("canonical_url", "url"):
        if (value := _status_id_from_url(candidate.get(field))) is not None:
            observed.add(value)
    return observed


def _canonical_url_key(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if not parsed.scheme or not parsed.netloc:
        return text
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, "")
    )


def _identity(candidate: dict[str, Any], ordinal: int) -> tuple[str, str]:
    stable_id = tweet_id(candidate)
    if stable_id is not None:
        return ("tweet_id", stable_id)
    canonical = _canonical_url_key(candidate.get("canonical_url"))
    if canonical is not None:
        return ("canonical_url", canonical)
    return ("unkeyed", str(ordinal))


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _containers(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [candidate]
    platform_fields = candidate.get("platform_fields")
    if isinstance(platform_fields, dict):
        containers.append(platform_fields)
        nested_x = platform_fields.get("x")
        if isinstance(nested_x, dict):
            containers.append(nested_x)
    return containers


def _marked_state(
    candidate: dict[str, Any],
    *,
    boolean_keys: tuple[str, ...],
    reference_keys: tuple[str, ...],
    positive_content_types: set[str],
    negative_content_types: set[str] | None = None,
) -> bool | None:
    markers: list[bool] = []
    content_type = (_text(candidate.get("content_type")) or "").casefold()
    if content_type in positive_content_types:
        markers.append(True)
    if negative_content_types and content_type in negative_content_types:
        markers.append(False)

    for container in _containers(candidate):
        for key in boolean_keys:
            if key in container:
                marker = _explicit_bool(container.get(key))
                if marker is not None:
                    markers.append(marker)
        for key in reference_keys:
            if key not in container:
                continue
            value = container.get(key)
            if value is None or value is False or value == "":
                markers.append(False)
            else:
                markers.append(True)

    if True in markers:
        return True
    if False in markers:
        return False
    return None


def repost_state(candidate: dict[str, Any]) -> bool | None:
    return _marked_state(
        candidate,
        boolean_keys=("is_repost", "is_retweet", "retweeted", "reposted"),
        reference_keys=(
            "repost_of",
            "repost_of_id",
            "retweet_of",
            "retweet_of_id",
            "retweeted_status",
            "retweeted_status_id",
        ),
        positive_content_types={"x_repost", "x_retweet"},
        negative_content_types={"x_quote_post", "x_article"},
    )


def reply_state(candidate: dict[str, Any]) -> bool | None:
    return _marked_state(
        candidate,
        boolean_keys=("is_reply", "replied"),
        reference_keys=(
            "in_reply_to",
            "in_reply_to_id",
            "in_reply_to_status_id",
            "in_reply_to_tweet_id",
            "reply_to",
            "reply_to_id",
        ),
        positive_content_types={"x_reply"},
    )


def _queries(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    query = _text(candidate.get("query"))
    if query is not None:
        values.append(query)
    queries = candidate.get("queries")
    if isinstance(queries, list):
        values.extend(value for item in queries if (value := _text(item)) is not None)
    return _unique(values)


def _rank(candidate: dict[str, Any]) -> int | float | None:
    value = _number(candidate.get("rank"))
    return value


def _timestamp(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc).timestamp()
    except (OverflowError, OSError, ValueError):
        return None


METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "likes": ("likes", "favorites", "favourites"),
    "reposts": ("shares", "reposts", "retweets"),
    "replies": ("comments", "replies"),
    "views": ("views", "impressions"),
}


def _metric(candidate: dict[str, Any], name: str) -> int | float | None:
    metrics = candidate.get("metrics")
    if not isinstance(metrics, dict):
        return None
    for key in METRIC_ALIASES[name]:
        value = _number(metrics.get(key))
        if value is not None:
            return value
    return None


def _observed_authors(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    author = candidate.get("author")
    if isinstance(author, str):
        values.append(author)
    elif isinstance(author, dict):
        for key in ("name", "screen_name", "username", "handle"):
            value = _text(author.get(key))
            if value is not None:
                values.append(value)

    platform_fields = candidate.get("platform_fields")
    if isinstance(platform_fields, dict):
        for key in ("screen_name", "username", "handle"):
            value = _text(platform_fields.get(key))
            if value is not None:
                values.append(value)
        nested_author = platform_fields.get("author")
        if isinstance(nested_author, dict):
            for key in ("name", "screen_name", "username", "handle"):
                value = _text(nested_author.get(key))
                if value is not None:
                    values.append(value)
    return _unique(values)


def _normalize_author(value: str) -> str:
    return value.strip().lstrip("@").casefold()


def _fill_missing(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key not in target or target[key] is None or target[key] == "":
            target[key] = copy.deepcopy(value)
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _fill_missing(target[key], value)


def _source_record(observation: dict[str, Any]) -> dict[str, Any]:
    candidate = observation["candidate"]
    return {
        "input_index": observation["input_index"],
        "candidate_index": observation["candidate_index"],
        "candidate_id": copy.deepcopy(candidate.get("candidate_id")),
        "backend": copy.deepcopy(candidate.get("backend")),
        "rank": copy.deepcopy(candidate.get("rank")),
        "queries": _queries(candidate),
        "provenance": copy.deepcopy(candidate.get("provenance")),
    }


def _combine_group(
    identity: tuple[str, str], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    observations = sorted(observations, key=lambda item: item["ordinal"])
    winner = min(
        observations,
        key=lambda item: (
            _rank(item["candidate"]) is None,
            _rank(item["candidate"]) or 0,
            item["ordinal"],
        ),
    )
    candidate = copy.deepcopy(winner["candidate"])

    for observation in observations:
        source_candidate = observation["candidate"]
        for field in (
            "title",
            "url",
            "canonical_url",
            "snippet",
            "author",
            "published_at",
            "content_type",
            "language",
            "access",
            "verification",
            "platform_fields",
        ):
            if field in source_candidate:
                _fill_missing(candidate, {field: source_candidate[field]})

    all_queries: list[str] = []
    for observation in observations:
        observed = _queries(observation["candidate"])
        if not observed:
            observed = observation["request_queries"]
        all_queries.extend(observed)
    all_queries = _unique(all_queries)
    candidate["queries"] = all_queries
    if _text(candidate.get("query")) is None and all_queries:
        candidate["query"] = all_queries[0]

    metrics = candidate.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    else:
        metrics = copy.deepcopy(metrics)
    metric_keys = set(metrics)
    for observation in observations:
        value = observation["candidate"].get("metrics")
        if isinstance(value, dict):
            metric_keys.update(value)
    for key in metric_keys:
        known = []
        for observation in observations:
            value = observation["candidate"].get("metrics")
            if isinstance(value, dict):
                number = _number(value.get(key))
                if number is not None:
                    known.append(number)
        if known:
            metrics[key] = max(known)

    canonical_metrics = {
        "likes": "likes",
        "reposts": "shares",
        "replies": "comments",
        "views": "views",
    }
    for logical_name, schema_name in canonical_metrics.items():
        known = [
            value
            for observation in observations
            if (value := _metric(observation["candidate"], logical_name)) is not None
        ]
        if known:
            metrics[schema_name] = max(known)
        elif schema_name not in metrics:
            metrics[schema_name] = None
    candidate["metrics"] = metrics

    timestamps = [
        (timestamp, observation["candidate"].get("published_at"))
        for observation in observations
        if (
            timestamp := _timestamp(observation["candidate"].get("published_at"))
        )
        is not None
    ]
    if timestamps:
        candidate["published_at"] = max(timestamps, key=lambda item: item[0])[1]

    limitations: list[Any] = []
    for observation in observations:
        value = observation["candidate"].get("limitations")
        if isinstance(value, list):
            limitations.extend(copy.deepcopy(value))
    candidate["limitations"] = _unique(limitations)

    provenance = candidate.get("provenance")
    provenance = copy.deepcopy(provenance) if isinstance(provenance, dict) else {}
    provenance["merged_sources"] = [
        _source_record(observation) for observation in observations
    ]
    if identity[0] == "tweet_id":
        provenance["tweet_id"] = identity[1]
        candidate["candidate_id"] = f"x:{identity[1]}"
    candidate["provenance"] = provenance

    repost_markers = [observation["repost_state"] for observation in observations]
    reply_markers = [observation["reply_state"] for observation in observations]

    def combined(markers: list[bool | None]) -> bool | None:
        if True in markers:
            return True
        if False in markers:
            return False
        return None

    combined_repost = combined(repost_markers)
    combined_reply = combined(reply_markers)
    if combined_repost is None:
        _append_limitation(candidate, UNKNOWN_REPOST_LIMITATION)
    if combined_reply is None:
        _append_limitation(candidate, UNKNOWN_REPLY_LIMITATION)
    if True in repost_markers and False in repost_markers:
        _append_limitation(
            candidate,
            "Duplicate observations disagreed on repost status; the conservative repost=true value was used.",
        )
    if True in reply_markers and False in reply_markers:
        _append_limitation(
            candidate,
            "Duplicate observations disagreed on reply status; the conservative reply=true value was used.",
        )
    if identity[0] == "unkeyed":
        _append_limitation(
            candidate,
            "No tweet ID or canonical URL was available; this candidate could not be deduplicated.",
        )
    if len(observations) > 1:
        _append_limitation(
            candidate,
            "Duplicate observations were merged; numeric metrics use the maximum known value per field.",
        )

    platform_fields = candidate.get("platform_fields")
    platform_fields = (
        copy.deepcopy(platform_fields) if isinstance(platform_fields, dict) else {}
    )
    engagement_components = {
        name: _metric(candidate, name) for name in ("likes", "reposts", "replies")
    }
    engagement_score = sum(value or 0 for value in engagement_components.values())
    platform_fields["x_research_merge"] = {
        "identity_type": identity[0],
        "tweet_id": identity[1] if identity[0] == "tweet_id" else None,
        "repost_status": (
            "true" if combined_repost is True else "false" if combined_repost is False else "unknown"
        ),
        "reply_status": (
            "true" if combined_reply is True else "false" if combined_reply is False else "unknown"
        ),
        "engagement_formula": ENGAGEMENT_FORMULA,
        "engagement_components": engagement_components,
        "engagement_score": engagement_score,
    }
    candidate["platform_fields"] = platform_fields
    candidate["_merge_repost_state"] = combined_repost
    candidate["_merge_reply_state"] = combined_reply
    candidate["_merge_best_rank"] = min(
        (
            rank
            for observation in observations
            if (rank := _rank(observation["candidate"])) is not None
        ),
        default=None,
    )
    candidate["_merge_authors"] = _unique(
        author
        for observation in observations
        for author in _observed_authors(observation["candidate"])
    )
    candidate["_merge_languages"] = _unique(
        language
        for observation in observations
        if (language := _text(observation["candidate"].get("language"))) is not None
    )
    return candidate


def _stable_sort_key(candidate: dict[str, Any]) -> str:
    return (
        _text(candidate.get("candidate_id"))
        or _text(candidate.get("canonical_url"))
        or _text(candidate.get("url"))
        or ""
    )


def _sort_candidates(candidates: list[dict[str, Any]], sort_mode: str) -> None:
    def relevance_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        rank = candidate.get("_merge_best_rank")
        return (rank is None, rank or 0, _stable_sort_key(candidate))

    def recent_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        timestamp = _timestamp(candidate.get("published_at"))
        return (
            timestamp is None,
            -(timestamp or 0),
            *relevance_key(candidate),
        )

    def engagement_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        fields = candidate.get("platform_fields", {}).get("x_research_merge", {})
        score = _number(fields.get("engagement_score")) or 0
        views = _metric(candidate, "views")
        timestamp = _timestamp(candidate.get("published_at"))
        return (
            -score,
            views is None,
            -(views or 0),
            timestamp is None,
            -(timestamp or 0),
            *relevance_key(candidate),
        )

    key = {
        "relevance": relevance_key,
        "recent": recent_key,
        "engagement": engagement_key,
    }[sort_mode]
    candidates.sort(key=key)


def validate_envelope(envelope: Any, source: str = "input") -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise MergeError("invalid_envelope", "Envelope root must be a JSON object.", source)
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise MergeError(
            "unsupported_schema",
            "Envelope schema_version must be exactly '1.0'.",
            source,
        )
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list):
        raise MergeError(
            "invalid_envelope", "Envelope candidates must be a JSON array.", source
        )
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise MergeError(
                "invalid_candidate",
                f"Candidate {index} must be a JSON object.",
                source,
            )
        if candidate.get("platform") != "x":
            raise MergeError(
                "invalid_platform",
                f"Candidate {index} has platform={candidate.get('platform')!r}; only platform='x' is accepted.",
                source,
            )
        candidate_urls = [
            value
            for field in ("canonical_url", "url")
            if (value := _text(candidate.get(field))) is not None
        ]
        if not candidate_urls or any(not _public_x_url(value) for value in candidate_urls):
            raise MergeError(
                "invalid_x_url",
                f"Candidate {index} must contain only public HTTPS x.com/twitter.com URLs.",
                source,
            )
        observed_ids = _observed_tweet_ids(candidate)
        if len(observed_ids) > 1:
            raise MergeError(
                "inconsistent_x_tweet_id",
                f"Candidate {index} contains conflicting X tweet identities.",
                source,
            )
        access = candidate.get("access")
        if not isinstance(access, dict) or access.get("visibility") not in {
            "public",
            "authenticated_public",
        }:
            raise MergeError(
                "invalid_visibility",
                f"Candidate {index} must be explicitly public or authenticated_public.",
                source,
            )
        provenance = candidate.get("provenance")
        if candidate.get("backend") == "grok-consult":
            if (
                not isinstance(provenance, dict)
                or provenance.get("grok_time_verification_bucket") != "matched"
                or provenance.get("grok_native_x_search_verified") is not True
            ):
                raise MergeError(
                    "invalid_grok_provenance",
                    f"Candidate {index} from grok-consult must come through the matched-result adapter.",
                    source,
                )
            url_ids = {
                status_id
                for value in candidate_urls
                if (status_id := _status_id_from_url(value)) is not None
            }
            stable_id = next(iter(observed_ids), None)
            if stable_id is None or url_ids != {stable_id}:
                raise MergeError(
                    "inconsistent_grok_tweet_id",
                    f"Candidate {index} has inconsistent Grok tweet IDs or a non-status URL.",
                    source,
                )
    for field in ("routes", "coverage", "errors"):
        value = envelope.get(field, [])
        if not isinstance(value, list):
            raise MergeError(
                "invalid_envelope", f"Envelope {field} must be a JSON array.", source
            )
    request = envelope.get("request", {})
    if not isinstance(request, dict):
        raise MergeError(
            "invalid_envelope", "Envelope request must be a JSON object.", source
        )
    return envelope


def load_envelopes(
    input_paths: list[str], *, stdin: TextIO | None = None
) -> list[dict[str, Any]]:
    """Read and validate envelopes from files and, at most once, stdin."""

    if not input_paths:
        raise MergeError("missing_input", "At least one --input is required.")
    stdin = stdin or sys.stdin
    stdin_used = False
    envelopes = []
    for input_path in input_paths:
        if input_path == "-":
            if stdin_used:
                raise MergeError(
                    "duplicate_stdin", "The '-' stdin input may only be used once.", "stdin"
                )
            stdin_used = True
            source = "stdin"
            try:
                raw = stdin.read()
            except (OSError, UnicodeError) as exc:
                raise MergeError("input_read_error", "Could not read stdin.", source) from exc
        else:
            source = input_path
            try:
                raw = Path(input_path).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise MergeError(
                    "input_read_error", f"Could not read input file: {input_path}", source
                ) from exc
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MergeError(
                "invalid_json",
                f"Input is not valid JSON (line {exc.lineno}, column {exc.colno}).",
                source,
            ) from exc
        envelopes.append(validate_envelope(envelope, source))
    return envelopes


def _validate_merge_arguments(
    *,
    sort: str,
    limit: int | None,
    thresholds: dict[str, int | None],
) -> None:
    if sort not in {"relevance", "recent", "engagement"}:
        raise MergeError("invalid_argument", f"Unsupported sort mode: {sort}")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise MergeError("invalid_argument", "limit must be a positive integer.")
    for name, value in thresholds.items():
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise MergeError(
                "invalid_argument", f"min_{name} must be a non-negative integer."
            )


def merge_envelopes(
    envelopes: list[dict[str, Any]],
    *,
    include_reposts: bool = False,
    include_replies: bool = False,
    authors: Iterable[str] = (),
    languages: Iterable[str] = (),
    min_likes: int | None = None,
    min_reposts: int | None = None,
    min_replies: int | None = None,
    min_views: int | None = None,
    sort: str = "relevance",
    limit: int | None = None,
) -> dict[str, Any]:
    """Merge already-loaded candidate envelopes into one offline research pool."""

    thresholds = {
        "likes": min_likes,
        "reposts": min_reposts,
        "replies": min_replies,
        "views": min_views,
    }
    _validate_merge_arguments(sort=sort, limit=limit, thresholds=thresholds)
    for index, envelope in enumerate(envelopes, start=1):
        validate_envelope(envelope, f"input {index}")

    author_filters = {
        _normalize_author(value)
        for item in authors
        if (value := _text(item)) is not None
    }
    language_filters = {
        value.casefold()
        for item in languages
        if (value := _text(item)) is not None
    }

    merged_routes: list[Any] = []
    merged_coverage: list[Any] = []
    merged_errors: list[Any] = []
    source_requests: list[dict[str, Any]] = []
    request_queries: list[str] = []
    time_ranges: list[Any] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordinal = 0

    for input_index, envelope in enumerate(envelopes, start=1):
        merged_routes.extend(copy.deepcopy(envelope.get("routes", [])))
        merged_coverage.extend(copy.deepcopy(envelope.get("coverage", [])))
        merged_errors.extend(copy.deepcopy(envelope.get("errors", [])))
        request = copy.deepcopy(envelope.get("request", {}))
        source_requests.append(request)
        queries = request.get("queries")
        envelope_queries = (
            [value for item in queries if (value := _text(item)) is not None]
            if isinstance(queries, list)
            else []
        )
        request_queries.extend(envelope_queries)
        if "time_range" in request:
            time_ranges.append(copy.deepcopy(request.get("time_range")))

        for candidate_index, candidate in enumerate(envelope["candidates"], start=1):
            ordinal += 1
            request_queries.extend(_queries(candidate))
            identity = _identity(candidate, ordinal)
            groups.setdefault(identity, []).append(
                {
                    "candidate": candidate,
                    "input_index": input_index,
                    "candidate_index": candidate_index,
                    "ordinal": ordinal,
                    "request_queries": envelope_queries,
                    "repost_state": repost_state(candidate),
                    "reply_state": reply_state(candidate),
                }
            )

    candidates = [
        _combine_group(identity, observations)
        for identity, observations in groups.items()
    ]
    input_candidate_count = ordinal
    duplicate_count = input_candidate_count - len(candidates)
    unknown_repost_count = sum(
        candidate["_merge_repost_state"] is None for candidate in candidates
    )
    unknown_reply_count = sum(
        candidate["_merge_reply_state"] is None for candidate in candidates
    )

    filtered_counts = {
        "reposts": 0,
        "replies": 0,
        "author": 0,
        "language": 0,
        "min_likes": 0,
        "min_reposts": 0,
        "min_replies": 0,
        "min_views": 0,
    }
    retained: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["_merge_repost_state"] is True and not include_reposts:
            filtered_counts["reposts"] += 1
            continue
        if candidate["_merge_reply_state"] is True and not include_replies:
            filtered_counts["replies"] += 1
            continue

        if author_filters:
            observed = {
                _normalize_author(value) for value in candidate["_merge_authors"]
            }
            if not observed.intersection(author_filters):
                filtered_counts["author"] += 1
                continue
        if language_filters:
            observed = {
                value.casefold() for value in candidate["_merge_languages"]
            }
            if not observed.intersection(language_filters):
                filtered_counts["language"] += 1
                continue

        rejected = False
        for metric_name, threshold in thresholds.items():
            if threshold is None:
                continue
            value = _metric(candidate, metric_name)
            if value is None or value < threshold:
                filtered_counts[f"min_{metric_name}"] += 1
                rejected = True
                break
        if rejected:
            continue
        retained.append(candidate)

    _sort_candidates(retained, sort)
    before_limit = len(retained)
    if limit is not None:
        retained = retained[:limit]
    truncated = len(retained) < before_limit

    for rank, candidate in enumerate(retained, start=1):
        candidate["rank"] = rank
        for internal in (
            "_merge_repost_state",
            "_merge_reply_state",
            "_merge_best_rank",
            "_merge_authors",
            "_merge_languages",
        ):
            candidate.pop(internal, None)

    route_limitations = [
        "Offline reducer only; no X search or original-page verification was performed."
    ]
    if sort == "engagement":
        route_limitations.append(
            f"Engagement sort uses {ENGAGEMENT_FORMULA}; unknown components are treated as zero for ordering only."
        )
    merged_routes.append(
        {
            "platform": "x",
            "backend": BACKEND,
            "mode": "offline_merge",
            "login_state_used": False,
            "status": "completed",
            "limitations": route_limitations,
        }
    )
    merged_coverage.append(
        {
            "platform": "x",
            "backend": BACKEND,
            "input_envelopes": len(envelopes),
            "input_candidates": input_candidate_count,
            "unique_candidates": len(candidates),
            "duplicate_observations_merged": duplicate_count,
            "unknown_repost_status": unknown_repost_count,
            "unknown_reply_status": unknown_reply_count,
            "filtered": filtered_counts,
            "sort": sort,
            "requested_limit": limit,
            "eligible_before_limit": before_limit,
            "returned": len(retained),
            "truncated": truncated,
            "login_state_used": False,
            "limitations": route_limitations,
        }
    )

    unique_time_ranges = _unique(time_ranges)
    request = {
        "queries": _unique(request_queries),
        "platforms": ["x"],
        "time_range": unique_time_ranges[0] if len(unique_time_ranges) == 1 else None,
        "requested_limit": limit,
        "source_requests": source_requests,
        "filters": {
            "include_reposts": include_reposts,
            "include_replies": include_replies,
            "authors": sorted(author_filters),
            "languages": sorted(language_filters),
            **thresholds,
        },
        "sort": sort,
    }
    if len(unique_time_ranges) > 1:
        request["time_ranges"] = unique_time_ranges

    return {
        "schema_version": SCHEMA_VERSION,
        "request": request,
        "routes": merged_routes,
        "candidates": retained,
        "coverage": merged_coverage,
        "errors": merged_errors,
    }


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline merge/filter/sort for unified X candidate envelopes."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Schema 1.0 envelope JSON path; repeat for multiple files or use '-' once for stdin.",
    )
    parser.add_argument("--include-reposts", action="store_true")
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--language", "--lang", action="append", default=[])
    parser.add_argument("--min-likes", type=_nonnegative_integer)
    parser.add_argument("--min-reposts", type=_nonnegative_integer)
    parser.add_argument("--min-replies", type=_nonnegative_integer)
    parser.add_argument("--min-views", type=_nonnegative_integer)
    parser.add_argument(
        "--sort", choices=("relevance", "recent", "engagement"), default="relevance"
    )
    parser.add_argument("--limit", type=_positive_integer)
    return parser


def _error_envelope(error: MergeError) -> dict[str, Any]:
    detail = {"category": error.category, "message": error.message}
    if error.source is not None:
        detail["source"] = error.source
    return {
        "schema_version": SCHEMA_VERSION,
        "request": {
            "queries": [],
            "platforms": ["x"],
            "time_range": None,
            "requested_limit": None,
        },
        "routes": [
            {
                "platform": "x",
                "backend": BACKEND,
                "mode": "offline_merge",
                "login_state_used": False,
                "status": "failed",
                "limitations": [
                    "No network fallback was attempted after the local input error."
                ],
            }
        ],
        "candidates": [],
        "coverage": [],
        "errors": [detail],
    }


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    stdout = stdout or sys.stdout
    try:
        envelopes = load_envelopes(args.input, stdin=stdin)
        envelope = merge_envelopes(
            envelopes,
            include_reposts=args.include_reposts,
            include_replies=args.include_replies,
            authors=args.author,
            languages=args.language,
            min_likes=args.min_likes,
            min_reposts=args.min_reposts,
            min_replies=args.min_replies,
            min_views=args.min_views,
            sort=args.sort,
            limit=args.limit,
        )
    except MergeError as exc:
        json.dump(_error_envelope(exc), stdout, ensure_ascii=False, indent=2)
        stdout.write("\n")
        return 2
    json.dump(envelope, stdout, ensure_ascii=False, indent=2)
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
