#!/usr/bin/env python3
"""Assemble and gate a horizontal/longitudinal research evidence bundle.

The reducer is deliberately offline. It accepts a plan, unified-search candidate
envelopes, explicit source annotations, and claim records. It never searches,
opens URLs, archives content, or writes persistent state.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
AXES = {"longitudinal", "cross_sectional"}
SOURCE_TIERS = {"L0", "L1", "L2", "L3", "unknown"}
SOURCE_ROLES = {
    "primary",
    "authoritative",
    "independent",
    "community",
    "aggregator",
    "unknown",
}
CLAIM_TYPES = {"fact", "decision_logic", "cross_insight", "scenario"}
CLAIM_BASES = {"explicit", "supported_inference", "unknown", "not_applicable"}
RELATIONS = {"supports", "contradicts", "context_only"}
SCENARIO_LABELS = {"most_likely", "danger", "optimistic"}
RESOLUTION_STATUSES = {"resolved", "retained_uncertainty"}
READY_CLAIM_STATUSES = {"ready", "ready_with_uncertainty"}
FUTURE_OPPORTUNITY_TERMS = (
    "future",
    "opportunity",
    "opportunities",
    "outlook",
    "prospect",
    "未来",
    "机会",
    "机遇",
    "前景",
)


class BundleError(ValueError):
    """A public, structural bundle error safe to return to the caller."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise BundleError("duplicate_json_key", f"Duplicate JSON key: {key}")
        output[key] = value
    return output


def _reject_nonfinite_number(value: str) -> None:
    raise BundleError("invalid_json_number", f"Non-finite number is not allowed: {value}")


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleError("invalid_bundle", f"{label} must be a JSON object.")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BundleError("invalid_bundle", f"{label} must be a JSON array.")
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _nonnegative_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BundleError(
            "invalid_plan", "minimum_evidence values must be non-negative integers."
        )
    return value


def _unique_text(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _nonempty_text_array(value: Any, label: str) -> list[str]:
    items = _list(value, label)
    normalized = _unique_text(items)
    if len(normalized) != len(items):
        raise BundleError(
            "invalid_bundle", f"{label} must contain distinct non-empty strings."
        )
    return normalized


def _plan_text_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise BundleError("invalid_plan", f"{label} must be a JSON array.")
    normalized = _unique_text(value)
    if len(normalized) != len(value):
        raise BundleError(
            "invalid_plan", f"{label} must contain distinct non-empty strings."
        )
    return normalized


def _brief_scope_values(value: Any, label: str) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise BundleError("invalid_plan", f"{label} must not be empty.")
        return [] if normalized.casefold() == "unknown" else [normalized]
    if isinstance(value, list):
        normalized = _plan_text_array(value, label)
        if not normalized:
            raise BundleError(
                "invalid_plan", f"{label} must use the explicit string unknown."
            )
        if any(item.casefold() == "unknown" for item in normalized):
            raise BundleError(
                "invalid_plan", f"{label} must not mix unknown with concrete values."
            )
        return normalized
    raise BundleError(
        "invalid_plan", f"{label} must be a string or string array."
    )


def _meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and any(_meaningful(item) for item in value.values())
    if isinstance(value, list):
        return bool(value) and any(_meaningful(item) for item in value)
    return value is not None


def _scope(value: Any, label: str) -> str | dict[str, Any]:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    elif isinstance(value, dict) and value and _meaningful(value):
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise BundleError("invalid_claim", f"{label} object keys must be non-empty.")
        return copy.deepcopy(value)
    raise BundleError(
        "invalid_claim", f"{label} must be a non-empty string or JSON object."
    )


def _date(value: Any, label: str, *, allow_unknown: bool = False) -> str:
    normalized = _text(value)
    if allow_unknown and normalized == "unknown":
        return normalized
    if normalized is None:
        raise BundleError("invalid_date", f"{label} must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise BundleError("invalid_date", f"{label} must be a valid YYYY-MM-DD date.") from exc
    if parsed.isoformat() != normalized:
        raise BundleError("invalid_date", f"{label} must use canonical YYYY-MM-DD.")
    return normalized


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BundleError("invalid_plan", f"Plan is not canonical-JSON serializable: {exc}") from exc


def _expected_plan_id(plan: dict[str, Any]) -> str:
    body = copy.deepcopy(plan)
    body.pop("plan_id", None)
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()[:16]


def _load_json(location: str) -> dict[str, Any]:
    try:
        if location == "-":
            raw = sys.stdin.read(MAX_BUNDLE_BYTES + 1)
        else:
            with Path(location).open("r", encoding="utf-8") as handle:
                raw = handle.read(MAX_BUNDLE_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise BundleError("input_read_error", f"Could not read bundle: {exc}") from exc
    if len(raw.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise BundleError(
            "bundle_too_large", f"Bundle exceeds {MAX_BUNDLE_BYTES} UTF-8 bytes."
        )
    try:
        return _dict(
            json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_number,
            ),
            "bundle",
        )
    except BundleError:
        raise
    except json.JSONDecodeError as exc:
        raise BundleError("invalid_json", f"Bundle is not valid JSON: {exc}") from exc


def _validate_plan(
    plan: Any,
) -> tuple[
    str,
    list[dict[str, Any]],
    dict[str, str],
    str,
    str,
    dict[str, set[str]],
    dict[str, list[str]],
    list[dict[str, Any]],
    bool,
]:
    payload = _dict(plan, "plan")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BundleError("invalid_plan", "plan.schema_version must be 1.0.")
    plan_id = _text(payload.get("plan_id"))
    if plan_id is None:
        raise BundleError("invalid_plan", "plan.plan_id must be non-empty.")
    expected_plan_id = _expected_plan_id(payload)
    if plan_id != expected_plan_id:
        raise BundleError(
            "invalid_plan_id",
            "plan.plan_id does not match the canonical hash of the current plan body.",
        )

    brief = _dict(payload.get("brief"), "plan.brief")
    object_type = _text(brief.get("object_type"))
    goal = _text(brief.get("goal"))
    audience = _text(brief.get("audience"))
    if object_type not in {"entity", "industry"} or goal is None or audience is None:
        raise BundleError(
            "invalid_plan",
            "plan.brief requires object_type entity/industry, goal, and audience.",
        )
    as_of = _date(brief.get("as_of"), "plan.brief.as_of")
    start_date = _date(
        brief.get("start_date"), "plan.brief.start_date", allow_unknown=True
    )
    if start_date != "unknown" and start_date > as_of:
        raise BundleError(
            "invalid_plan",
            "plan.brief.start_date must not be later than plan.brief.as_of.",
        )

    brief_dimensions = {
        "geographies": _brief_scope_values(
            brief.get("geography"), "plan.brief.geography"
        ),
        "languages": _brief_scope_values(
            brief.get("languages"), "plan.brief.languages"
        ),
    }
    coverage_dimensions = _dict(
        payload.get("coverage_dimensions"), "plan.coverage_dimensions"
    )
    required_dimensions = {
        "geographies": _plan_text_array(
            coverage_dimensions.get("geographies"),
            "plan.coverage_dimensions.geographies",
        ),
        "languages": _plan_text_array(
            coverage_dimensions.get("languages"),
            "plan.coverage_dimensions.languages",
        ),
    }
    if required_dimensions != brief_dimensions:
        raise BundleError(
            "invalid_plan",
            "plan.coverage_dimensions geographies/languages must exactly match the known values in plan.brief.",
        )

    expected_scope_gap_dimensions = {
        dimension
        for dimension, is_unknown in (
            ("start_date", start_date == "unknown"),
            ("geography", not brief_dimensions["geographies"]),
            ("languages", not brief_dimensions["languages"]),
            ("audience", audience.casefold() == "unknown"),
        )
        if is_unknown
    }
    scope_gaps: list[dict[str, Any]] = []
    seen_scope_gap_dimensions: set[str] = set()
    raw_scope_gaps = coverage_dimensions.get("gaps")
    if not isinstance(raw_scope_gaps, list):
        raise BundleError(
            "invalid_plan", "plan.coverage_dimensions.gaps must be a JSON array."
        )
    for index, raw_gap in enumerate(raw_scope_gaps, start=1):
        if not isinstance(raw_gap, dict):
            raise BundleError(
                "invalid_plan",
                f"plan.coverage_dimensions.gaps[{index}] must be an object.",
            )
        dimension = _text(raw_gap.get("dimension"))
        status = _text(raw_gap.get("status"))
        reason = _text(raw_gap.get("reason"))
        if (
            dimension not in {"start_date", "geography", "languages", "audience"}
            or dimension in seen_scope_gap_dimensions
            or status != "gap"
            or reason is None
        ):
            raise BundleError(
                "invalid_plan",
                "plan.coverage_dimensions.gaps must contain unique start_date/geography/languages/audience gap records with non-empty reasons.",
            )
        seen_scope_gap_dimensions.add(dimension)
        scope_gaps.append(
            {
                "kind": "scope",
                "dimension": dimension,
                "status": "gap",
                "reason": reason,
                "retained": False,
            }
        )
    if seen_scope_gap_dimensions != expected_scope_gap_dimensions:
        raise BundleError(
            "invalid_plan",
            "plan.coverage_dimensions.gaps must exactly represent unknown start_date/geography/languages/audience fields in plan.brief.",
        )

    report_contract = _dict(payload.get("report_contract"), "plan.report_contract")
    required_sections = _plan_text_array(
        report_contract.get("required_sections"),
        "plan.report_contract.required_sections",
    )
    raw_language_contract = report_contract.get("language_requirements")
    if not isinstance(raw_language_contract, dict):
        raise BundleError(
            "invalid_plan", "plan.report_contract.language_requirements must be an object."
        )
    expected_delivery_languages = brief_dimensions["languages"]
    expected_language_status = (
        "required" if expected_delivery_languages else "gap_unknown"
    )
    declared_language_status = _text(raw_language_contract.get("status"))
    declared_language_derivation = _text(
        raw_language_contract.get("derived_from")
    )
    declared_all_delivery_languages_required = raw_language_contract.get(
        "all_delivery_languages_required"
    )
    declared_search_languages = _plan_text_array(
        raw_language_contract.get("search_languages"),
        "plan.report_contract.language_requirements.search_languages",
    )
    declared_delivery_languages = _plan_text_array(
        raw_language_contract.get("delivery_languages"),
        "plan.report_contract.language_requirements.delivery_languages",
    )
    raw_per_language = raw_language_contract.get("per_language_requirements")
    if not isinstance(raw_per_language, list):
        raise BundleError(
            "invalid_plan",
            "plan.report_contract.language_requirements.per_language_requirements must be an array.",
        )
    per_language_requirements: list[dict[str, Any]] = []
    seen_delivery_languages: set[str] = set()
    for index, raw_requirement in enumerate(raw_per_language, start=1):
        if not isinstance(raw_requirement, dict):
            raise BundleError(
                "invalid_plan",
                f"plan.report_contract.language_requirements.per_language_requirements[{index}] must be an object.",
            )
        language = _text(raw_requirement.get("language"))
        if language is None or language in seen_delivery_languages:
            raise BundleError(
                "invalid_plan",
                "Per-language delivery requirements need unique non-empty language values.",
            )
        seen_delivery_languages.add(language)
        per_language_requirements.append(
            {
                "language": language,
                "search_required": raw_requirement.get("search_required"),
                "delivery_required": raw_requirement.get("delivery_required"),
                "scope_matched_citations_required": raw_requirement.get(
                    "scope_matched_citations_required"
                ),
            }
        )
    expected_per_language_requirements = [
        {
            "language": language,
            "search_required": True,
            "delivery_required": True,
            "scope_matched_citations_required": True,
        }
        for language in expected_delivery_languages
    ]
    if (
        declared_language_status != expected_language_status
        or declared_language_derivation != "brief.languages"
        or declared_all_delivery_languages_required
        is not bool(expected_delivery_languages)
        or declared_search_languages != expected_delivery_languages
        or declared_delivery_languages != expected_delivery_languages
        or per_language_requirements != expected_per_language_requirements
    ):
        raise BundleError(
            "invalid_plan",
            "plan.report_contract language delivery requirements must be derived exactly from plan.brief.languages and remain required for every known language.",
        )
    normalized_goal = goal.casefold()
    opportunity_required = object_type == "industry" and any(
        term in normalized_goal for term in FUTURE_OPPORTUNITY_TERMS
    )
    raw_opportunity_contract = report_contract.get("opportunity_map")
    if not isinstance(raw_opportunity_contract, dict):
        raise BundleError(
            "invalid_plan", "plan.report_contract.opportunity_map must be an object."
        )
    declared_opportunity_required = raw_opportunity_contract.get("required")
    declared_opportunity_section = _text(raw_opportunity_contract.get("section"))
    if (
        declared_opportunity_required is not opportunity_required
        or ("opportunity_map" in required_sections) is not opportunity_required
        or declared_opportunity_section
        != ("opportunity_map" if opportunity_required else None)
    ):
        raise BundleError(
            "invalid_plan",
            "plan.report_contract opportunity_map requirement must match industry future/opportunity intent derived from plan.brief.",
        )

    workstreams = _list(payload.get("workstreams"), "plan.workstreams")
    if not workstreams:
        raise BundleError("invalid_plan", "plan.workstreams must not be empty.")

    normalized: list[dict[str, Any]] = []
    axes: dict[str, str] = {}
    query_group_ids: dict[str, set[str]] = {}
    for index, raw_workstream in enumerate(workstreams, start=1):
        workstream = _dict(raw_workstream, f"plan.workstreams[{index}]")
        workstream_id = _text(workstream.get("id"))
        axis = _text(workstream.get("axis"))
        if workstream_id is None:
            raise BundleError("invalid_plan", "Each workstream requires a non-empty id.")
        if workstream_id in axes:
            raise BundleError("invalid_plan", f"Duplicate workstream id: {workstream_id}")
        if axis not in AXES:
            raise BundleError(
                "invalid_plan", f"Workstream {workstream_id} has an invalid axis."
            )
        minimum = workstream.get("minimum_evidence", {})
        if not isinstance(minimum, dict):
            raise BundleError(
                "invalid_plan",
                f"Workstream {workstream_id} minimum_evidence must be an object.",
            )
        group_ids: set[str] = set()
        for group_index, raw_group in enumerate(
            _list(workstream.get("query_groups", []), "workstream.query_groups"),
            start=1,
        ):
            group = _dict(raw_group, f"workstream.query_groups[{group_index}]")
            group_id = _text(group.get("id"))
            if group_id is None or group_id in group_ids:
                raise BundleError(
                    "invalid_plan",
                    f"Workstream {workstream_id} query group IDs must be non-empty and unique.",
                )
            group_ids.add(group_id)
        normalized.append(copy.deepcopy(workstream))
        axes[workstream_id] = axis
        query_group_ids[workstream_id] = group_ids
    return (
        plan_id,
        normalized,
        axes,
        as_of,
        start_date,
        query_group_ids,
        required_dimensions,
        scope_gaps,
        opportunity_required,
    )


def _source_identity(candidate: dict[str, Any]) -> str:
    for field in ("canonical_url", "url", "candidate_id"):
        identity = _text(candidate.get(field))
        if identity is not None:
            return identity
    raise BundleError(
        "invalid_envelope", "Every candidate needs candidate_id, canonical_url, or url."
    )


def _queries(candidate: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    if isinstance(candidate.get("queries"), list):
        values.extend(candidate["queries"])
    values.append(candidate.get("query"))
    return _unique_text(values)


def _verified(candidate: dict[str, Any]) -> bool:
    verification = candidate.get("verification")
    return (
        isinstance(verification, dict)
        and verification.get("status") == "verified"
        and verification.get("opened_original") is True
    )


def _merge_envelopes(
    entries: Any,
    *,
    plan_id: str,
    axes: dict[str, str],
    query_group_ids: dict[str, set[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    sources: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for envelope_index, raw_entry in enumerate(
        _list(entries, "envelopes"), start=1
    ):
        entry = _dict(raw_entry, f"envelopes[{envelope_index}]")
        workstream_id = _text(entry.get("workstream_id"))
        if workstream_id not in axes:
            raise BundleError(
                "invalid_envelope",
                f"Envelope {envelope_index} references an unknown workstream.",
            )
        envelope = _dict(entry.get("envelope"), f"envelopes[{envelope_index}].envelope")
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise BundleError(
                "invalid_envelope", "Candidate envelope schema_version must be 1.0."
            )
        context = _dict(envelope.get("research_context"), "envelope.research_context")
        context_plan_id = _text(context.get("plan_id"))
        context_workstream_id = _text(context.get("workstream_id"))
        if context_plan_id != plan_id:
            raise BundleError(
                "invalid_envelope",
                "Envelope research_context plan_id must be present and match exactly.",
            )
        if context_workstream_id != workstream_id:
            raise BundleError(
                "invalid_envelope",
                "Envelope research_context workstream_id must be present and match exactly.",
            )
        query_group_id = _text(context.get("query_group_id"))
        if query_group_id is not None and query_group_id not in query_group_ids[
            workstream_id
        ]:
            raise BundleError(
                "invalid_envelope",
                "Envelope research_context query_group_id is not in the planned workstream.",
            )
        candidates = _list(envelope.get("candidates"), "envelope.candidates")
        for candidate_index, raw_candidate in enumerate(candidates, start=1):
            candidate = _dict(raw_candidate, "candidate")
            dedup_key = _source_identity(candidate)
            candidate_id = _text(candidate.get("candidate_id"))
            public_source_id = candidate_id or dedup_key
            source = sources.setdefault(
                dedup_key,
                {
                    "source_id": public_source_id,
                    "candidate_id": candidate_id,
                    "candidate_ids": [],
                    "title": _text(candidate.get("title")),
                    "url": _text(candidate.get("url")),
                    "canonical_url": _text(candidate.get("canonical_url")),
                    "platforms": [],
                    "backends": [],
                    "queries": [],
                    "workstream_ids": [],
                    "source_tier": "unknown",
                    "source_role": "unknown",
                    "independence_group": None,
                    "geographies": [],
                    "languages": [],
                    "pre_scope_context": False,
                    "pre_scope_event_dates": [],
                    "in_scope_event_dates": [],
                    "temporal_eligible": False,
                    "verification": {
                        "verified": False,
                        "opened_original": False,
                        "statuses": [],
                    },
                    "observations": [],
                    "limitations": [],
                },
            )
            alias_values = _unique_text(
                [
                    dedup_key,
                    candidate.get("candidate_id"),
                    candidate.get("canonical_url"),
                    candidate.get("url"),
                    source["source_id"],
                ]
            )
            for alias in alias_values:
                existing_key = aliases.get(alias)
                if existing_key is not None and existing_key != dedup_key:
                    raise BundleError(
                        "invalid_envelope",
                        f"Source alias {alias} refers to more than one deduplicated source.",
                    )
                aliases[alias] = dedup_key
            source["candidate_ids"] = _unique_text(
                [*source["candidate_ids"], candidate_id]
            )
            source["platforms"] = _unique_text(
                [*source["platforms"], candidate.get("platform")]
            )
            source["backends"] = _unique_text(
                [*source["backends"], candidate.get("backend")]
            )
            source["queries"] = _unique_text([*source["queries"], *_queries(candidate)])
            source["workstream_ids"] = _unique_text(
                [*source["workstream_ids"], workstream_id]
            )
            verification = candidate.get("verification")
            if isinstance(verification, dict):
                status = _text(verification.get("status"))
                if status is not None:
                    source["verification"]["statuses"] = _unique_text(
                        [*source["verification"]["statuses"], status]
                    )
                source["verification"]["opened_original"] = (
                    source["verification"]["opened_original"]
                    or verification.get("opened_original") is True
                )
            source["verification"]["verified"] = (
                source["verification"]["verified"] or _verified(candidate)
            )
            source["observations"].append(
                {
                    "envelope_index": envelope_index,
                    "candidate_index": candidate_index,
                    "workstream_id": workstream_id,
                    "query_group_id": query_group_id,
                    "rank": candidate.get("rank"),
                }
            )
            if isinstance(candidate.get("limitations"), list):
                source["limitations"] = _unique_text(
                    [*source["limitations"], *candidate["limitations"]]
                )
    for dedup_key, source in sources.items():
        source["independence_group"] = f"source:{dedup_key}"
    return sources, aliases


def _resolve_source_key(
    reference: Any, sources: dict[str, dict[str, Any]], aliases: dict[str, str]
) -> str:
    source_reference = _text(reference)
    if source_reference is None:
        raise BundleError("invalid_source_reference", "Source reference must be non-empty.")
    if source_reference in sources:
        return source_reference
    source_key = aliases.get(source_reference)
    if source_key is None:
        raise BundleError("invalid_source_reference", "Source reference is unknown.")
    return source_key


def _apply_annotations(
    sources: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    annotations: Any,
    *,
    as_of: str,
    start_date: str,
) -> None:
    seen: set[str] = set()
    for index, raw_annotation in enumerate(
        _list(annotations, "source_annotations"), start=1
    ):
        annotation = _dict(raw_annotation, f"source_annotations[{index}]")
        source_id = _text(annotation.get("source_id"))
        try:
            source_key = _resolve_source_key(source_id, sources, aliases)
        except BundleError as exc:
            raise BundleError(
                "invalid_annotation", "Every annotation must reference a known source_id."
            ) from exc
        if source_key in seen:
            raise BundleError("invalid_annotation", f"Duplicate annotation: {source_id}")
        seen.add(source_key)
        tier = _text(annotation.get("source_tier")) or "unknown"
        if tier not in SOURCE_TIERS:
            raise BundleError(
                "invalid_annotation", f"Invalid source_tier for {source_id}: {tier}"
            )
        sources[source_key]["source_tier"] = tier
        role = _text(annotation.get("source_role")) or "unknown"
        if role not in SOURCE_ROLES:
            raise BundleError(
                "invalid_annotation", f"Invalid source_role for {source_id}: {role}"
            )
        sources[source_key]["source_role"] = role

        published_at = None
        if annotation.get("published_at") is not None:
            published_at = _date(
                annotation.get("published_at"), f"annotation {source_id} published_at"
            )
        retrospective = annotation.get("retrospective", False)
        if not isinstance(retrospective, bool):
            raise BundleError(
                "invalid_annotation", f"retrospective for {source_id} must be boolean."
            )
        if published_at is not None and published_at > as_of and not retrospective:
            raise BundleError(
                "invalid_annotation",
                f"Source {source_id} was published after plan as_of and requires retrospective=true to be retained.",
            )
        event_dates: list[str] = []
        if "event_dates" in annotation:
            for event_index, value in enumerate(
                _list(annotation.get("event_dates"), "annotation.event_dates"), start=1
            ):
                event_date = _date(
                    value, f"annotation {source_id} event_dates[{event_index}]"
                )
                if event_date > as_of:
                    raise BundleError(
                        "invalid_annotation",
                        f"Source {source_id} event_dates must not be later than plan as_of.",
                    )
                event_dates.append(event_date)
        pre_scope_context = annotation.get("pre_scope_context", False)
        if not isinstance(pre_scope_context, bool):
            raise BundleError(
                "invalid_annotation",
                f"pre_scope_context for {source_id} must be boolean.",
            )
        pre_scope_event_dates = (
            [event_date for event_date in event_dates if event_date < start_date]
            if start_date != "unknown"
            else []
        )
        in_scope_event_dates = (
            [event_date for event_date in event_dates if event_date >= start_date]
            if start_date != "unknown"
            else list(event_dates)
        )
        only_pre_scope_dates = bool(event_dates) and bool(pre_scope_event_dates) and not in_scope_event_dates
        if only_pre_scope_dates and not pre_scope_context:
            raise BundleError(
                "invalid_annotation",
                f"Source {source_id} whose event_dates are all earlier than plan start_date requires pre_scope_context=true.",
            )
        if pre_scope_context and not only_pre_scope_dates:
            raise BundleError(
                "invalid_annotation",
                f"Source {source_id} pre_scope_context=true requires non-empty event_dates all earlier than a known plan start_date.",
            )
        independence_group = _text(annotation.get("independence_group"))
        if independence_group is not None:
            sources[source_key]["independence_group"] = independence_group
        geographies = _nonempty_text_array(
            annotation.get("geographies", []),
            f"annotation {source_id} geographies",
        )
        languages = _nonempty_text_array(
            annotation.get("languages", []),
            f"annotation {source_id} languages",
        )
        sources[source_key]["geographies"] = geographies
        sources[source_key]["languages"] = languages
        sources[source_key]["pre_scope_context"] = pre_scope_context
        sources[source_key]["pre_scope_event_dates"] = pre_scope_event_dates
        sources[source_key]["in_scope_event_dates"] = in_scope_event_dates
        event_window_eligible = (
            not event_dates
            or start_date == "unknown"
            or bool(in_scope_event_dates)
        )
        sources[source_key]["temporal_eligible"] = (
            published_at is not None and published_at <= as_of
            and event_window_eligible
            and not pre_scope_context
        )
        sources[source_key]["annotation"] = {
            key: copy.deepcopy(annotation[key])
            for key in (
                "publisher_kind",
                "selection_reason",
            )
            if key in annotation
        }
        sources[source_key]["annotation"].update(
            {
                "published_at": published_at,
                "event_dates": event_dates,
                "pre_scope_context": pre_scope_context,
                "pre_scope_event_dates": pre_scope_event_dates,
                "in_scope_event_dates": in_scope_event_dates,
                "independence_group": sources[source_key]["independence_group"],
                "geographies": geographies,
                "languages": languages,
                "retrospective": retrospective,
                "available_as_of": sources[source_key]["temporal_eligible"],
            }
        )


def _coverage(
    workstreams: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    required_dimensions: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for workstream in workstreams:
        workstream_id = workstream["id"]
        selected = [
            source
            for source in sources.values()
            if workstream_id in source["workstream_ids"]
        ]
        verified = [
            source
            for source in selected
            if source["verification"]["verified"] and source["temporal_eligible"]
        ]
        primary = [
            source for source in verified if source["source_tier"] in {"L0", "L1"}
        ]
        independent = [
            source for source in verified if source["source_role"] == "independent"
        ]
        minimum = workstream.get("minimum_evidence", {})
        required = {
            "verified_sources": _nonnegative_int(
                minimum.get("verified_sources"), 2
            ),
            "primary_sources": _nonnegative_int(minimum.get("primary_sources"), 0),
            "independent_sources": _nonnegative_int(
                minimum.get("independent_sources"), 1
            ),
        }
        counts = {
            "candidate_sources": len(selected),
            "verified_sources": len(verified),
            "primary_sources": len(primary),
            "independent_sources": len(
                {source["independence_group"] for source in independent}
            ),
            "retrospective_sources": len(
                [
                    source
                    for source in selected
                    if source["verification"]["verified"]
                    and not source["temporal_eligible"]
                ]
            ),
        }
        missing = {
            field: required[field] - counts[field]
            for field in required
            if counts[field] < required[field]
        }
        dimension_counts = {
            dimension: {
                required_value: len(
                    [
                        source
                        for source in verified
                        if required_value in source[dimension]
                    ]
                )
                for required_value in required_dimensions[dimension]
            }
            for dimension in ("geographies", "languages")
        }
        missing_dimensions = {
            dimension: [
                required_value
                for required_value, count in dimension_counts[dimension].items()
                if count == 0
            ]
            for dimension in ("geographies", "languages")
        }
        missing_dimensions = {
            dimension: values
            for dimension, values in missing_dimensions.items()
            if values
        }
        status = "covered" if not missing and not missing_dimensions else "gap"
        rows.append(
            {
                "workstream_id": workstream_id,
                "axis": workstream["axis"],
                "facet": workstream.get("facet"),
                "counts": counts,
                "minimum_evidence": required,
                "dimension_counts": dimension_counts,
                "required_dimensions": copy.deepcopy(required_dimensions),
                "status": status,
                "missing": missing,
                "missing_dimensions": missing_dimensions,
            }
        )
        if missing or missing_dimensions:
            gaps.append(
                {
                    "gap_key": f"coverage:{workstream_id}",
                    "kind": "workstream_coverage",
                    "workstream_id": workstream_id,
                    "missing": missing,
                    "missing_dimensions": missing_dimensions,
                }
            )
    return rows, gaps


def _claim_evidence(
    raw_evidence: Any,
    sources: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    *,
    as_of: str,
    start_date: str,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    evidence_rows: list[dict[str, Any]] = []
    supports: list[str] = []
    contradicts: list[str] = []
    for raw_link in _list(raw_evidence, "claim.evidence"):
        link = _dict(raw_link, "claim evidence link")
        source_reference = _text(link.get("source_id"))
        relation = _text(link.get("relation"))
        try:
            source_key = _resolve_source_key(source_reference, sources, aliases)
        except BundleError as exc:
            raise BundleError(
                "invalid_claim", "Claim evidence references an unknown source."
            ) from exc
        if relation not in RELATIONS:
            raise BundleError("invalid_claim", "Claim evidence relation is invalid.")
        pre_scope_context = link.get("pre_scope_context", False)
        if not isinstance(pre_scope_context, bool):
            raise BundleError(
                "invalid_claim", "Claim evidence pre_scope_context must be boolean."
            )
        locator = _text(link.get("locator"))
        if relation in {"supports", "contradicts"} and locator is None:
            raise BundleError(
                "invalid_claim",
                "Supporting and contradicting evidence links require a non-empty locator.",
            )
        event_date = None
        if relation in {"supports", "contradicts"} and link.get("event_date") is None:
            raise BundleError(
                "invalid_claim",
                "Supporting and contradicting evidence links require event_date.",
            )
        if link.get("event_date") is not None:
            event_date = _date(link.get("event_date"), "claim evidence event_date")
            if event_date > as_of:
                raise BundleError(
                    "invalid_claim", "Claim evidence event_date must not be later than plan as_of."
                )
        is_pre_scope = (
            event_date is not None
            and start_date != "unknown"
            and event_date < start_date
        )
        if is_pre_scope and not pre_scope_context:
            raise BundleError(
                "invalid_claim",
                "Claim evidence event_date earlier than plan start_date requires pre_scope_context=true.",
            )
        if pre_scope_context and not is_pre_scope:
            raise BundleError(
                "invalid_claim",
                "Claim evidence pre_scope_context=true requires an event_date earlier than a known plan start_date.",
            )
        scope = None
        if relation in {"supports", "contradicts"} and link.get("scope") is None:
            raise BundleError(
                "invalid_claim",
                "Supporting and contradicting evidence links require scope.",
            )
        if link.get("scope") is not None:
            scope = _scope(link.get("scope"), "Claim evidence scope")
        notes = None
        if link.get("notes") is not None:
            notes = _text(link.get("notes"))
            if notes is None:
                raise BundleError("invalid_claim", "Claim evidence notes must be non-empty text.")
        source = sources[source_key]
        link_temporal_eligible = source["temporal_eligible"] and not is_pre_scope
        row = {
            "source_id": source["source_id"],
            "source_reference": source_reference,
            "relation": relation,
            "locator": locator,
            "event_date": event_date,
            "pre_scope_context": pre_scope_context,
            "in_scope": not is_pre_scope,
            "scope": scope,
            "notes": notes,
            "verified": source["verification"]["verified"],
            "available_as_of": source["temporal_eligible"],
            "temporal_eligible": link_temporal_eligible,
            "eligible_evidence": (
                source["verification"]["verified"]
                and link_temporal_eligible
            ),
            "source_tier": source["source_tier"],
            "source_role": source["source_role"],
            "independence_group": source["independence_group"],
        }
        evidence_rows.append(row)
        if row["eligible_evidence"] and relation == "supports":
            supports.append(source_key)
        if row["eligible_evidence"] and relation == "contradicts":
            contradicts.append(source_key)
    return evidence_rows, _unique_text(supports), _unique_text(contradicts)


def _axes_supported(
    source_ids: list[str], sources: dict[str, dict[str, Any]], axes: dict[str, str]
) -> set[str]:
    supported: set[str] = set()
    for source_id in source_ids:
        for workstream_id in sources[source_id]["workstream_ids"]:
            axis = axes.get(workstream_id)
            if axis is not None:
                supported.add(axis)
    return supported


def _claims(
    raw_claims: Any,
    *,
    sources: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    axes: dict[str, str],
    as_of: str,
    start_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_claim in enumerate(_list(raw_claims, "claims"), start=1):
        claim = _dict(raw_claim, f"claims[{index}]")
        claim_id = _text(claim.get("claim_id"))
        statement = _text(claim.get("statement"))
        claim_type = _text(claim.get("claim_type"))
        basis = _text(claim.get("basis"))
        if claim_id is None or statement is None:
            raise BundleError("invalid_claim", "Each claim needs claim_id and statement.")
        if claim_id in seen:
            raise BundleError("invalid_claim", f"Duplicate claim_id: {claim_id}")
        seen.add(claim_id)
        if claim_type not in CLAIM_TYPES or basis not in CLAIM_BASES:
            raise BundleError("invalid_claim", f"Claim {claim_id} type or basis is invalid.")
        pre_scope_context = claim.get("pre_scope_context", False)
        if not isinstance(pre_scope_context, bool):
            raise BundleError(
                "invalid_claim", f"Claim {claim_id} pre_scope_context must be boolean."
            )
        claim_as_of = _date(claim.get("as_of"), f"claim {claim_id} as_of")
        if claim_as_of != as_of:
            raise BundleError(
                "invalid_claim", f"Claim {claim_id} as_of must equal plan.brief.as_of."
            )
        event_date = None
        if claim.get("event_date") is not None:
            event_date = _date(claim.get("event_date"), f"claim {claim_id} event_date")
            if event_date > as_of:
                raise BundleError(
                    "invalid_claim",
                    f"Claim {claim_id} event_date must not be later than plan.brief.as_of.",
                )
        is_pre_scope = (
            event_date is not None
            and start_date != "unknown"
            and event_date < start_date
        )
        if is_pre_scope and not pre_scope_context:
            raise BundleError(
                "invalid_claim",
                f"Claim {claim_id} event_date earlier than plan.brief.start_date requires pre_scope_context=true.",
            )
        if pre_scope_context and not is_pre_scope:
            raise BundleError(
                "invalid_claim",
                f"Claim {claim_id} pre_scope_context=true requires an event_date earlier than a known plan.brief.start_date.",
            )
        workstream_ids = _unique_text(
            _list(claim.get("workstream_ids"), "claim.workstream_ids")
        )
        if not workstream_ids or any(value not in axes for value in workstream_ids):
            raise BundleError(
                "invalid_claim", f"Claim {claim_id} has unknown or empty workstreams."
            )
        evidence, supports, contradicts = _claim_evidence(
            claim.get("evidence", []),
            sources,
            aliases,
            as_of=as_of,
            start_date=start_date,
        )
        supported_axes = _axes_supported(supports, sources, axes)
        support_groups = {
            sources[source_key]["independence_group"] for source_key in supports
        }

        reasons: list[str] = []
        if basis == "unknown":
            reasons.append("claim_basis_is_unknown")
        elif not supports:
            reasons.append("no_verified_supporting_source")
        if basis == "supported_inference" and len(support_groups) < 2:
            reasons.append("supported_inference_requires_two_independent_evidence_groups")
        if claim_type in {"fact", "decision_logic"}:
            unsupported_workstreams = [
                workstream_id
                for workstream_id in workstream_ids
                if not any(
                    workstream_id in sources[source_key]["workstream_ids"]
                    for source_key in supports
                )
            ]
            if unsupported_workstreams:
                reasons.append("base_claim_requires_verified_support_for_each_workstream")
        if claim_type == "decision_logic" and basis == "explicit":
            if not any(
                sources[source_id]["source_tier"] in {"L0", "L1"}
                for source_id in supports
            ):
                reasons.append("explicit_decision_logic_requires_verified_primary_source")
        if claim_type in {"cross_insight", "scenario"}:
            if basis != "supported_inference":
                reasons.append("cross_axis_claim_requires_supported_inference_basis")
            if supported_axes != AXES:
                reasons.append("cross_axis_claim_requires_verified_support_from_both_axes")

        cross_link = None
        if claim_type == "cross_insight":
            cross_link = _dict(claim.get("cross_link"), f"claim {claim_id} cross_link")
            cross_link = {
                "past_event": _text(cross_link.get("past_event")),
                "present_effect": _text(cross_link.get("present_effect")),
                "implication": _text(cross_link.get("implication")),
            }
            if any(value is None for value in cross_link.values()):
                reasons.append("cross_link_requires_past_event_present_effect_implication")

        scenario = None
        if claim_type == "scenario":
            scenario = _dict(claim.get("scenario"), f"claim {claim_id} scenario")
            label = _text(scenario.get("label"))
            horizon = _text(scenario.get("horizon"))
            triggers = _unique_text(
                _list(scenario.get("triggers", []), "scenario.triggers")
            )
            invalidators = _unique_text(
                _list(scenario.get("invalidators", []), "scenario.invalidators")
            )
            starting_conditions = _unique_text(
                _list(
                    scenario.get("starting_conditions", []),
                    "scenario.starting_conditions",
                )
            )
            causal_path = _unique_text(
                _list(scenario.get("causal_path", []), "scenario.causal_path")
            )
            implications = _unique_text(
                _list(scenario.get("implications", []), "scenario.implications")
            )
            if label not in SCENARIO_LABELS:
                reasons.append("scenario_label_invalid")
            if horizon is None:
                reasons.append("scenario_horizon_missing")
            if not triggers:
                reasons.append("scenario_triggers_missing")
            if not invalidators:
                reasons.append("scenario_invalidators_missing")
            if not starting_conditions:
                reasons.append("scenario_starting_conditions_missing")
            if len(causal_path) < 2:
                reasons.append("scenario_causal_path_requires_at_least_two_steps")
            if not implications:
                reasons.append("scenario_implications_missing")
            scenario = {
                "label": label,
                "horizon": horizon,
                "starting_conditions": starting_conditions,
                "causal_path": causal_path,
                "triggers": triggers,
                "invalidators": invalidators,
                "implications": implications,
            }

        resolution = claim.get("contradiction_resolution")
        resolution_status = None
        if resolution is not None:
            resolution = _dict(resolution, "claim.contradiction_resolution")
            resolution_status = _text(resolution.get("status"))
            if resolution_status not in RESOLUTION_STATUSES or _text(
                resolution.get("note")
            ) is None:
                raise BundleError(
                    "invalid_claim",
                    "Contradiction resolution needs a valid status and non-empty note.",
                )
        unresolved_contradiction = bool(contradicts) and resolution_status is None
        if unresolved_contradiction:
            reasons.append("verified_contradiction_unresolved")

        status = "ready"
        if reasons:
            status = "unknown" if basis == "unknown" else "insufficient"
        if unresolved_contradiction:
            status = "contested"
        if contradicts and resolution_status is not None and not [
            reason for reason in reasons if reason != "verified_contradiction_unresolved"
        ]:
            status = "ready_with_uncertainty"

        result = {
            "claim_id": claim_id,
            "statement": statement,
            "claim_type": claim_type,
            "basis": basis,
            "workstream_ids": workstream_ids,
            "event_date": event_date,
            "pre_scope_context": pre_scope_context,
            "in_scope": not is_pre_scope,
            "as_of": claim_as_of,
            "evidence": evidence,
            "verified_supporting_sources": [
                sources[source_key]["source_id"] for source_key in supports
            ],
            "verified_contradicting_sources": [
                sources[source_key]["source_id"] for source_key in contradicts
            ],
            "independent_support_groups": sorted(support_groups),
            "supported_axes": sorted(supported_axes),
            "cross_link": cross_link,
            "scenario": scenario,
            "contradiction_resolution": copy.deepcopy(resolution),
            "status": status,
            "reasons": _unique_text(reasons),
        }
        output.append(result)
        if status not in {"ready", "ready_with_uncertainty"}:
            gaps.append(
                {
                    "gap_key": f"claim:{claim_id}",
                    "kind": "claim",
                    "claim_id": claim_id,
                    "status": status,
                    "reasons": result["reasons"],
                }
            )
    return output, gaps


def _retained_disclosures(
    raw_retained: Any,
    actual_gaps: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    actual_by_key = {
        gap["gap_key"]: gap for gap in actual_gaps if _text(gap.get("gap_key"))
    }
    retained: dict[str, dict[str, Any]] = {}
    for index, raw_item in enumerate(
        _list(raw_retained, "retained_gaps"), start=1
    ):
        item = _dict(raw_item, f"retained_gaps[{index}]")
        gap_key = _text(item.get("gap_key"))
        if gap_key is None or gap_key not in actual_by_key:
            raise BundleError(
                "invalid_retained_gap",
                "Each retained gap must match an actual coverage or claim gap_key.",
            )
        if gap_key in retained:
            raise BundleError(
                "invalid_retained_gap", f"Duplicate retained gap: {gap_key}"
            )
        attempts: list[dict[str, Any]] = []
        for attempt_index, raw_attempt in enumerate(
            _list(item.get("search_attempts"), "retained_gap.search_attempts"),
            start=1,
        ):
            if not isinstance(raw_attempt, dict):
                raise BundleError(
                    "invalid_retained_gap",
                    f"Retained gap {gap_key} search attempts must be objects.",
                )
            attempt = raw_attempt
            query_or_path = _text(attempt.get("query_or_path"))
            route = _text(attempt.get("route"))
            if query_or_path is None or route is None:
                raise BundleError(
                    "invalid_retained_gap",
                    f"Retained gap {gap_key} search attempts need query_or_path and route.",
                )
            normalized_attempt = copy.deepcopy(attempt)
            normalized_attempt["query_or_path"] = query_or_path
            normalized_attempt["route"] = route
            attempts.append(normalized_attempt)
        distinct_queries = {attempt["query_or_path"] for attempt in attempts}
        distinct_routes = {attempt["route"] for attempt in attempts}
        if (
            len(attempts) < 2
            or len(distinct_queries) != len(attempts)
            or len(distinct_routes) != len(attempts)
        ):
            raise BundleError(
                "invalid_retained_gap",
                f"Retained gap {gap_key} needs at least two attempts with distinct query_or_path and route values.",
            )
        disclosure = {
            "gap_key": gap_key,
            "search_attempts": attempts,
            "impact": _text(item.get("impact")),
            "disclosure": _text(item.get("disclosure")),
            "bounded_conclusion": _text(item.get("bounded_conclusion")),
        }
        if any(
            disclosure[field] is None
            for field in ("impact", "disclosure", "bounded_conclusion")
        ):
            raise BundleError(
                "invalid_retained_gap",
                f"Retained gap {gap_key} needs impact, disclosure, and bounded_conclusion.",
            )
        retained[gap_key] = disclosure
    return retained


def _opportunity_map(
    raw_opportunities: Any,
    *,
    required: bool,
    claims: list[dict[str, Any]],
    axes: dict[str, str],
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
    if not required:
        return [], True, []
    if not isinstance(raw_opportunities, list) or not raw_opportunities:
        return (
            [],
            False,
            [
                {
                    "kind": "structure",
                    "reason": "nonempty_opportunity_map_required_by_plan",
                    "retained": False,
                }
            ],
        )

    ready_by_id = {
        claim["claim_id"]: claim
        for claim in claims
        if claim["status"] in READY_CLAIM_STATUSES
        and claim.get("in_scope") is True
    }
    ready_base_by_id = {
        claim_id: claim
        for claim_id, claim in ready_by_id.items()
        if claim["claim_type"] in {"fact", "decision_logic"}
        and claim.get("in_scope") is True
    }
    output: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_opportunities, start=1):
        item = _dict(raw_item, f"opportunity_map[{index}]")
        opportunity_id = _text(item.get("opportunity_id"))
        if opportunity_id is None or opportunity_id in seen:
            raise BundleError(
                "invalid_opportunity_map",
                "Opportunity IDs must be non-empty and unique.",
            )
        seen.add(opportunity_id)
        reasons: list[str] = []
        text_fields = ("opportunity", "historical_driver", "current_condition")
        normalized: dict[str, Any] = {"opportunity_id": opportunity_id}
        for field in text_fields:
            normalized[field] = _text(item.get(field))
            if normalized[field] is None:
                reasons.append(f"opportunity_{field}_missing")

        basis = _unique_text(
            _list(item.get("evidence_basis", []), "opportunity.evidence_basis")
        )
        if not basis or any(claim_id not in ready_by_id for claim_id in basis):
            reasons.append("opportunity_evidence_basis_requires_ready_claim_ids")
        normalized["evidence_basis"] = basis
        base_claims = [
            ready_base_by_id[claim_id]
            for claim_id in basis
            if claim_id in ready_base_by_id
        ]
        supported_axes = {
            axes[workstream_id]
            for claim in base_claims
            for workstream_id in claim["workstream_ids"]
        }
        if supported_axes != AXES:
            reasons.append(
                "opportunity_requires_longitudinal_and_cross_sectional_ready_base_claims"
            )

        for field in (
            "beneficiaries",
            "constraints",
            "leading_indicators",
            "invalidators",
        ):
            normalized[field] = copy.deepcopy(item.get(field))
            if not _meaningful(normalized[field]):
                reasons.append(f"opportunity_{field}_missing")
        normalized["supported_axes"] = sorted(supported_axes)
        normalized["status"] = "ready" if not reasons else "insufficient"
        normalized["reasons"] = reasons
        output.append(normalized)
        if reasons:
            gaps.append(
                {
                    "kind": "structure",
                    "reason": "opportunity_map_item_insufficient",
                    "opportunity_id": opportunity_id,
                    "reasons": reasons,
                    "retained": False,
                }
            )
    return output, not gaps, gaps


def assemble(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise BundleError("invalid_bundle", "bundle.schema_version must be 1.0.")
    (
        plan_id,
        workstreams,
        axes,
        as_of,
        start_date,
        query_group_ids,
        required_dimensions,
        scope_gaps,
        opportunity_required,
    ) = _validate_plan(bundle.get("plan"))
    declared_plan_id = _text(bundle.get("plan_id"))
    if declared_plan_id != plan_id:
        raise BundleError(
            "invalid_bundle",
            "bundle.plan_id must be present and exactly match canonical plan.plan_id.",
        )

    sources, aliases = _merge_envelopes(
        bundle.get("envelopes", []),
        plan_id=plan_id,
        axes=axes,
        query_group_ids=query_group_ids,
    )
    _apply_annotations(
        sources,
        aliases,
        bundle.get("source_annotations", []),
        as_of=as_of,
        start_date=start_date,
    )
    coverage, coverage_gaps = _coverage(
        workstreams, sources, required_dimensions
    )
    claims, claim_gaps = _claims(
        bundle.get("claims", []),
        sources=sources,
        aliases=aliases,
        axes=axes,
        as_of=as_of,
        start_date=start_date,
    )

    retained = _retained_disclosures(
        bundle.get("retained_gaps", []), [*coverage_gaps, *claim_gaps]
    )
    for row in coverage:
        gap_key = f"coverage:{row['workstream_id']}"
        if row["status"] == "gap" and gap_key in retained:
            row["status"] = "retained_gap"
            row["retained_disclosure"] = copy.deepcopy(retained[gap_key])
    for claim in claims:
        gap_key = f"claim:{claim['claim_id']}"
        if claim["status"] not in READY_CLAIM_STATUSES and gap_key in retained:
            claim["status"] = "retained_with_disclosure"
            claim["retained_disclosure"] = copy.deepcopy(retained[gap_key])

    opportunities, opportunity_map_ready, opportunity_gaps = _opportunity_map(
        bundle.get("opportunity_map"),
        required=opportunity_required,
        claims=claims,
        axes=axes,
    )

    ready_claims = [
        claim
        for claim in claims
        if claim["status"] in READY_CLAIM_STATUSES
    ]
    in_scope_ready_claims = [
        claim for claim in ready_claims if claim["in_scope"]
    ]
    ready_base_claims = [
        claim
        for claim in in_scope_ready_claims
        if claim["claim_type"] in {"fact", "decision_logic"}
    ]
    base_claim_workstreams = {
        workstream_id
        for claim in ready_base_claims
        for workstream_id in claim["workstream_ids"]
    }
    missing_base_claim_workstreams = sorted(set(axes) - base_claim_workstreams)
    timeline_ready = any(
        claim["event_date"] is not None
        and any(axes[value] == "longitudinal" for value in claim["workstream_ids"])
        for claim in ready_base_claims
    )
    cross_sectional_ready = any(
        any(axes[value] == "cross_sectional" for value in claim["workstream_ids"])
        for claim in ready_base_claims
    )
    cross_axis_supported = any(
        claim["claim_type"] == "cross_insight" for claim in in_scope_ready_claims
    )
    scenario_labels = {
        claim["scenario"]["label"]
        for claim in in_scope_ready_claims
        if claim["claim_type"] == "scenario" and claim["scenario"] is not None
    }
    scenarios_bounded = scenario_labels == SCENARIO_LABELS
    contradictions_resolved = not any(
        "verified_contradiction_unresolved" in claim["reasons"] for claim in claims
    )
    unretained_coverage_gaps = [
        gap for gap in coverage_gaps if gap["gap_key"] not in retained
    ]
    unretained_claim_gaps = [
        gap for gap in claim_gaps if gap["gap_key"] not in retained
    ]
    gates = {
        "scope_complete": not scope_gaps,
        "coverage_complete": not unretained_coverage_gaps,
        "base_claims_complete": not missing_base_claim_workstreams,
        "timeline_ready": timeline_ready,
        "cross_sectional_ready": cross_sectional_ready,
        "opportunity_map_ready": opportunity_map_ready,
        "contradictions_resolved_or_retained": contradictions_resolved,
        "cross_axis_supported": cross_axis_supported,
        "scenarios_bounded": scenarios_bounded,
    }
    gates["final_report_ready"] = all(gates.values()) and not unretained_claim_gaps

    gaps: list[dict[str, Any]] = [copy.deepcopy(gap) for gap in scope_gaps]
    for gap in [*coverage_gaps, *claim_gaps]:
        output_gap = copy.deepcopy(gap)
        output_gap["retained"] = gap["gap_key"] in retained
        if output_gap["retained"]:
            output_gap["retained_disclosure"] = copy.deepcopy(
                retained[gap["gap_key"]]
            )
        gaps.append(output_gap)
    if missing_base_claim_workstreams:
        gaps.append(
            {
                "kind": "structure",
                "reason": "ready_base_claim_required_for_every_workstream",
                "missing_workstream_ids": missing_base_claim_workstreams,
                "retained": False,
            }
        )
    if not timeline_ready:
        gaps.append(
            {
                "kind": "structure",
                "reason": "dated_ready_longitudinal_base_claim_required",
                "retained": False,
            }
        )
    if not cross_sectional_ready:
        gaps.append(
            {
                "kind": "structure",
                "reason": "ready_cross_sectional_base_claim_required",
                "retained": False,
            }
        )
    gaps.extend(opportunity_gaps)
    if not cross_axis_supported:
        gaps.append({"kind": "synthesis", "reason": "no_ready_cross_insight"})
    if not scenarios_bounded:
        gaps.append(
            {
                "kind": "scenarios",
                "reason": "three_bounded_scenarios_required",
                "missing_labels": sorted(SCENARIO_LABELS - scenario_labels),
            }
        )

    ready_statuses = READY_CLAIM_STATUSES
    views = {
        "timeline": [
            {
                "claim_id": claim["claim_id"],
                "event_date": claim["event_date"],
                "statement": claim["statement"],
                "status": claim["status"],
            }
            for claim in claims
            if claim["event_date"] is not None
            and claim["in_scope"]
            and claim["status"] in ready_statuses
            and any(axes[value] == "longitudinal" for value in claim["workstream_ids"])
        ],
        "cross_sectional": [
            {
                "claim_id": claim["claim_id"],
                "statement": claim["statement"],
                "workstream_ids": claim["workstream_ids"],
                "status": claim["status"],
            }
            for claim in claims
            if claim["claim_type"] in {"fact", "decision_logic"}
            and claim["in_scope"]
            and claim["status"] in ready_statuses
            and any(
                axes[value] == "cross_sectional" for value in claim["workstream_ids"]
            )
        ],
        "cross_synthesis": [
            {
                "claim_id": claim["claim_id"],
                **claim["cross_link"],
                "status": claim["status"],
            }
            for claim in claims
            if claim["claim_type"] == "cross_insight"
            and claim["in_scope"]
            and claim["status"] in ready_statuses
            and claim["cross_link"] is not None
        ],
        "scenarios": [
            {
                "claim_id": claim["claim_id"],
                **claim["scenario"],
                "status": claim["status"],
            }
            for claim in claims
            if claim["claim_type"] == "scenario"
            and claim["in_scope"]
            and claim["status"] in ready_statuses
            and claim["scenario"] is not None
        ],
        "opportunity_map": opportunities,
    }
    views["timeline"].sort(key=lambda row: str(row["event_date"]))

    status = "blocking"
    if gates["final_report_ready"]:
        status = "ready_with_disclosure" if retained else "ready"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "plan_id": plan_id,
        "research_window": {"start_date": start_date, "as_of": as_of},
        "sources": sorted(sources.values(), key=lambda source: source["source_id"]),
        "workstream_coverage": coverage,
        "claims": claims,
        "views": views,
        "gates": gates,
        "gaps": gaps,
        "retained_disclosures": [
            copy.deepcopy(retained[key]) for key in sorted(retained)
        ],
        "limitations": [
            "Offline reducer only; no search, page opening, archiving, or account-state change was performed.",
            "Source tiers and roles are explicit annotations, never inferred from titles, domains, or snippets.",
            "Candidate snippets and opened_original alone do not prove a material claim.",
            "Narrative length is not a completion gate; evidence coverage and unresolved gaps are.",
        ],
        "errors": [],
    }


def _error_payload(error: BundleError) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid_bundle",
        "plan_id": None,
        "sources": [],
        "workstream_coverage": [],
        "claims": [],
        "views": {
            "timeline": [],
            "cross_sectional": [],
            "cross_synthesis": [],
            "scenarios": [],
            "opportunity_map": [],
        },
        "gates": {
            "scope_complete": False,
            "coverage_complete": False,
            "base_claims_complete": False,
            "timeline_ready": False,
            "cross_sectional_ready": False,
            "opportunity_map_ready": False,
            "contradictions_resolved_or_retained": False,
            "cross_axis_supported": False,
            "scenarios_bounded": False,
            "final_report_ready": False,
        },
        "gaps": [],
        "retained_disclosures": [],
        "limitations": [
            "Offline reducer only; no search, page opening, archiving, or account-state change was performed."
        ],
        "errors": [{"category": error.category, "message": error.message}],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble and gate a horizontal/longitudinal evidence bundle offline."
    )
    parser.add_argument(
        "--bundle", required=True, help="JSON bundle path, or - to read once from stdin."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = assemble(_load_json(args.bundle))
    except BundleError as exc:
        print(json.dumps(_error_payload(exc), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
