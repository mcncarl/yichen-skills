#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "assemble_hengzong_evidence.py"
PLANNER_SCRIPT = SKILL_ROOT / "scripts" / "plan_hengzong_research.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module("assemble_hengzong_evidence", SCRIPT)
PLANNER = load_module("plan_hengzong_research_for_contract", PLANNER_SCRIPT)
AS_OF = "2026-08-20"


def real_plan() -> dict:
    return PLANNER.build_plan(
        {
            "subject": "Example Research System",
            "object_type": "entity",
            "subtype": "research product",
            "goal": "Explain history, current structure, and bounded scenarios.",
            "as_of": AS_OF,
            "geography": ["China", "United States"],
            "languages": ["zh", "en"],
            "audience": "research lead",
            "start_date": "2015-01-01",
        }
    )


def future_industry_plan() -> dict:
    return PLANNER.build_plan(
        {
            "subject": "Legal Technology Industry",
            "object_type": "industry",
            "subtype": "software and services",
            "goal": "Explain history, current structure, and future opportunities.",
            "as_of": AS_OF,
            "geography": ["China", "United States"],
            "languages": ["zh", "en"],
            "audience": "industry strategy lead",
            "start_date": "2015-01-01",
            "horizontal_facets": ["value_chain", "players", "regulation"],
        }
    )


def unknown_scope_plan() -> dict:
    return PLANNER.build_plan(
        {
            "subject": "Example Research System",
            "object_type": "entity",
            "subtype": "research product",
            "goal": "Explain history, current structure, and bounded scenarios.",
            "as_of": AS_OF,
            "geography": "unknown",
            "languages": "unknown",
            "audience": "research lead",
            "start_date": "2015-01-01",
        }
    )


def source_id(workstream_id: str, number: int) -> str:
    return f"src:{workstream_id}:{number}"


def candidate(candidate_id: str, *, verified: bool = True, canonical_url: str | None = None) -> dict:
    url = canonical_url or f"https://example.com/{candidate_id.replace(':', '-')}"
    return {
        "candidate_id": candidate_id,
        "query": f"query for {candidate_id}",
        "platform": "web",
        "backend": "anysearch",
        "rank": 1,
        "title": candidate_id,
        "url": url,
        "canonical_url": url,
        "verification": {
            "status": "verified" if verified else "candidate",
            "opened_original": verified,
        },
        "limitations": [],
    }


def envelope(*candidates: dict, research_context: dict) -> dict:
    return {
        "schema_version": "1.0",
        "request": {},
        "routes": [],
        "candidates": list(candidates),
        "coverage": [],
        "errors": [],
        "research_context": research_context,
    }


def evidence_link(reference: str, *, relation: str = "supports") -> dict:
    return {
        "source_id": reference,
        "relation": relation,
        "locator": "section 2, paragraph 3",
        "event_date": "2025-12-31",
        "scope": "China and United States",
        "notes": "Directly supports the bounded statement.",
    }


def scenario_claim(label: str, vertical_id: str, horizontal_id: str) -> dict:
    return {
        "claim_id": f"scenario-{label}",
        "statement": f"Scenario {label}",
        "claim_type": "scenario",
        "basis": "supported_inference",
        "as_of": AS_OF,
        "workstream_ids": [vertical_id, horizontal_id],
        "evidence": [
            evidence_link(source_id(vertical_id, 1)),
            evidence_link(source_id(horizontal_id, 1)),
        ],
        "scenario": {
            "label": label,
            "horizon": "12-24 months",
            "starting_conditions": ["current conditions remain observable"],
            "causal_path": ["trigger changes behavior", "behavior changes outcome"],
            "triggers": ["observable trigger"],
            "invalidators": ["observable invalidator"],
            "implications": ["decision implication"],
        },
    }


def ready_bundle(plan: dict | None = None) -> dict:
    plan = plan or real_plan()
    envelopes = []
    annotations = []
    base_claims = []
    for workstream in plan["workstreams"]:
        workstream_id = workstream["id"]
        count = workstream["minimum_evidence"]["verified_sources"]
        candidates = [candidate(source_id(workstream_id, n)) for n in range(1, count + 1)]
        query_groups = workstream.get("query_groups", [])
        context = {
            "plan_id": plan["plan_id"],
            "workstream_id": workstream_id,
        }
        if query_groups:
            context["query_group_id"] = query_groups[0]["id"]
        envelopes.append(
            {
                "workstream_id": workstream_id,
                "envelope": envelope(*candidates, research_context=context),
            }
        )
        for number in range(1, count + 1):
            annotations.append(
                {
                    "source_id": source_id(workstream_id, number),
                    "source_tier": "L1" if number == 1 else "L2",
                    "source_role": "primary" if number == 1 else "independent",
                    "published_at": "2026-01-15",
                    "independence_group": f"publisher:{workstream_id}:{number}",
                    "geographies": list(plan["coverage_dimensions"]["geographies"]),
                    "languages": list(plan["coverage_dimensions"]["languages"]),
                }
            )
        claim = {
            "claim_id": f"base:{workstream_id}",
            "statement": f"A bounded base fact for {workstream_id}.",
            "claim_type": "fact",
            "basis": "explicit",
            "as_of": AS_OF,
            "workstream_ids": [workstream_id],
            "evidence": [evidence_link(source_id(workstream_id, 1))],
        }
        if workstream["axis"] == "longitudinal":
            claim["event_date"] = "2020-01-01"
        base_claims.append(claim)

    vertical_id = next(item["id"] for item in plan["workstreams"] if item["axis"] == "longitudinal")
    horizontal_id = next(item["id"] for item in plan["workstreams"] if item["axis"] == "cross_sectional")
    cross_claim = {
        "claim_id": "cross-1",
        "statement": "A past event shaped the present market position.",
        "claim_type": "cross_insight",
        "basis": "supported_inference",
        "as_of": AS_OF,
        "workstream_ids": [vertical_id, horizontal_id],
        "evidence": [
            evidence_link(source_id(vertical_id, 1)),
            evidence_link(source_id(horizontal_id, 1)),
        ],
        "cross_link": {
            "past_event": "A verified past event",
            "present_effect": "A verified current effect",
            "implication": "A bounded implication",
        },
    }
    scenarios = [
        scenario_claim(label, vertical_id, horizontal_id)
        for label in ("most_likely", "danger", "optimistic")
    ]
    return {
        "schema_version": "1.0",
        "plan_id": plan["plan_id"],
        "plan": plan,
        "envelopes": envelopes,
        "source_annotations": annotations,
        "claims": [*base_claims, cross_claim, *scenarios],
        "retained_gaps": [],
    }


def rebind_plan(bundle: dict) -> None:
    plan_id = MODULE._expected_plan_id(bundle["plan"])
    bundle["plan"]["plan_id"] = plan_id
    bundle["plan_id"] = plan_id
    for entry in bundle["envelopes"]:
        entry["envelope"]["research_context"]["plan_id"] = plan_id


def find_claim(bundle: dict, claim_id: str) -> dict:
    return next(claim for claim in bundle["claims"] if claim["claim_id"] == claim_id)


def add_ready_opportunity_map(bundle: dict) -> None:
    vertical_id = next(
        item["id"]
        for item in bundle["plan"]["workstreams"]
        if item["axis"] == "longitudinal"
    )
    horizontal_id = next(
        item["id"]
        for item in bundle["plan"]["workstreams"]
        if item["axis"] == "cross_sectional"
    )
    bundle["opportunity_map"] = [
        {
            "opportunity_id": "opp-1",
            "opportunity": "A bounded workflow opportunity.",
            "historical_driver": "A dated structural transition.",
            "current_condition": "A verified current market constraint.",
            "evidence_basis": [f"base:{vertical_id}", f"base:{horizontal_id}"],
            "beneficiaries": ["regulated professional teams"],
            "constraints": ["procurement and data controls"],
            "leading_indicators": ["verified adoption disclosures"],
            "invalidators": ["no measured workflow adoption"],
        }
    ]


class HengzongEvidenceTests(unittest.TestCase):
    def test_real_planner_to_assembler_contract_is_ready(self) -> None:
        bundle = ready_bundle()
        result = MODULE.assemble(bundle)
        self.assertEqual(result["plan_id"], bundle["plan"]["plan_id"])
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["gates"]["final_report_ready"])
        self.assertTrue(result["gates"]["base_claims_complete"])
        self.assertTrue(result["gates"]["timeline_ready"])
        self.assertTrue(result["gates"]["cross_sectional_ready"])
        self.assertEqual(len(result["views"]["scenarios"]), 3)

    def test_plan_id_is_recomputed_and_binds_current_plan_body(self) -> None:
        bundle = ready_bundle()
        bundle["plan"]["brief"]["goal"] = "Tampered after plan creation"
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan_id")

    def test_bundle_plan_id_is_mandatory_and_exact(self) -> None:
        bundle = ready_bundle()
        bundle.pop("plan_id")
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_bundle")
        bundle = ready_bundle()
        bundle["plan_id"] = "0000000000000000"
        with self.assertRaises(MODULE.BundleError):
            MODULE.assemble(bundle)

    def test_envelope_research_context_is_mandatory_and_bound(self) -> None:
        mutations = (
            lambda context: context.clear(),
            lambda context: context.update(plan_id="0000000000000000"),
            lambda context: context.update(workstream_id="not-the-workstream"),
            lambda context: context.update(query_group_id="not-a-planned-group"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = ready_bundle()
                context = bundle["envelopes"][0]["envelope"]["research_context"]
                mutation(context)
                with self.assertRaises(MODULE.BundleError) as error:
                    MODULE.assemble(bundle)
                self.assertEqual(error.exception.category, "invalid_envelope")

    def test_plan_window_is_validated_after_a_valid_rehash(self) -> None:
        bundle = ready_bundle()
        bundle["plan"]["brief"]["start_date"] = "2026-08-21"
        bundle["plan"]["plan_id"] = MODULE._expected_plan_id(bundle["plan"])
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

    def test_pre_start_claim_and_evidence_dates_fail_closed_by_default(self) -> None:
        bundle = ready_bundle()
        first_vertical = next(
            claim
            for claim in bundle["claims"]
            if claim["claim_id"].startswith("base:v")
        )
        first_vertical["event_date"] = "2014-12-31"
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_claim")

        bundle = ready_bundle()
        first_vertical = next(
            claim
            for claim in bundle["claims"]
            if claim["claim_id"].startswith("base:v")
        )
        first_vertical["evidence"][0]["event_date"] = "2014-12-31"
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_claim")

    def test_explicit_pre_scope_context_is_preserved_but_never_structural(self) -> None:
        bundle = ready_bundle()
        for claim in bundle["claims"]:
            if not claim["claim_id"].startswith("base:v"):
                continue
            claim["event_date"] = "2014-12-31"
            claim["pre_scope_context"] = True
            claim["evidence"][0]["event_date"] = "2014-12-31"
            claim["evidence"][0]["pre_scope_context"] = True

        result = MODULE.assemble(bundle)
        first_vertical = next(
            claim
            for claim in result["claims"]
            if claim["claim_id"].startswith("base:v")
        )
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["base_claims_complete"])
        self.assertFalse(result["gates"]["timeline_ready"])
        self.assertEqual(result["views"]["timeline"], [])
        self.assertTrue(first_vertical["pre_scope_context"])
        self.assertFalse(first_vertical["in_scope"])
        self.assertTrue(first_vertical["evidence"][0]["pre_scope_context"])
        self.assertFalse(first_vertical["evidence"][0]["in_scope"])
        self.assertFalse(first_vertical["evidence"][0]["temporal_eligible"])
        self.assertFalse(first_vertical["evidence"][0]["eligible_evidence"])

    def test_pre_scope_source_annotations_never_satisfy_structure_gates(self) -> None:
        bundle = ready_bundle(future_industry_plan())
        add_ready_opportunity_map(bundle)
        for annotation in bundle["source_annotations"]:
            annotation["event_dates"] = ["2014-12-31"]
            annotation["pre_scope_context"] = True

        result = MODULE.assemble(bundle)

        self.assertEqual(result["status"], "blocking")
        for gate in (
            "coverage_complete",
            "base_claims_complete",
            "timeline_ready",
            "cross_sectional_ready",
            "opportunity_map_ready",
            "cross_axis_supported",
            "scenarios_bounded",
            "final_report_ready",
        ):
            with self.subTest(gate=gate):
                self.assertFalse(result["gates"][gate])
        self.assertEqual(result["views"]["timeline"], [])
        self.assertEqual(result["views"]["cross_sectional"], [])
        self.assertEqual(result["views"]["cross_synthesis"], [])
        self.assertEqual(result["views"]["scenarios"], [])
        self.assertTrue(
            all(row["counts"]["verified_sources"] == 0 for row in result["workstream_coverage"])
        )
        self.assertTrue(all(not source["temporal_eligible"] for source in result["sources"]))
        first_source = result["sources"][0]
        self.assertTrue(first_source["annotation"]["pre_scope_context"])
        self.assertEqual(first_source["annotation"]["pre_scope_event_dates"], ["2014-12-31"])
        self.assertEqual(first_source["annotation"]["in_scope_event_dates"], [])

    def test_pre_scope_source_annotation_requires_explicit_context_flag(self) -> None:
        bundle = ready_bundle()
        bundle["source_annotations"][0]["event_dates"] = ["2014-12-31"]
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_annotation")

        bundle = ready_bundle()
        bundle["source_annotations"][0]["event_dates"] = ["2020-01-01"]
        bundle["source_annotations"][0]["pre_scope_context"] = True
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_annotation")

    def test_mixed_source_annotation_dates_only_use_in_scope_portion(self) -> None:
        bundle = ready_bundle()
        annotation = bundle["source_annotations"][0]
        annotation["event_dates"] = ["2014-12-31", "2020-01-01"]
        result = MODULE.assemble(bundle)
        source = next(
            item for item in result["sources"] if item["source_id"] == annotation["source_id"]
        )
        self.assertTrue(source["temporal_eligible"])
        self.assertEqual(source["annotation"]["pre_scope_event_dates"], ["2014-12-31"])
        self.assertEqual(source["annotation"]["in_scope_event_dates"], ["2020-01-01"])
        self.assertEqual(result["status"], "ready")

    def test_material_links_require_locator_event_date_and_scope(self) -> None:
        for relation in ("supports", "contradicts"):
            for field in ("locator", "event_date", "scope"):
                with self.subTest(relation=relation, field=field):
                    bundle = ready_bundle()
                    link = bundle["claims"][0]["evidence"][0]
                    link["relation"] = relation
                    link.pop(field)
                    with self.assertRaises(MODULE.BundleError) as context:
                        MODULE.assemble(bundle)
                    self.assertEqual(context.exception.category, "invalid_claim")

    def test_evidence_metadata_is_preserved(self) -> None:
        link = MODULE.assemble(ready_bundle())["claims"][0]["evidence"][0]
        self.assertEqual(link["event_date"], "2025-12-31")
        self.assertEqual(link["scope"], "China and United States")
        self.assertEqual(link["notes"], "Directly supports the bounded statement.")
        bundle = ready_bundle()
        bundle["claims"][0]["evidence"][0]["scope"] = {
            "geographies": ["China"],
            "period": "2025",
        }
        object_scope = MODULE.assemble(bundle)["claims"][0]["evidence"][0]["scope"]
        self.assertEqual(object_scope["period"], "2025")

    def test_claim_and_evidence_dates_fail_closed_at_as_of(self) -> None:
        edits = [
            ("as_of", "2026-08-19"),
            ("event_date", "2026-08-21"),
        ]
        for field, value in edits:
            bundle = ready_bundle()
            bundle["claims"][0][field] = value
            with self.assertRaises(MODULE.BundleError):
                MODULE.assemble(bundle)
        bundle = ready_bundle()
        bundle["claims"][0]["evidence"][0]["event_date"] = "2026-08-21"
        with self.assertRaises(MODULE.BundleError):
            MODULE.assemble(bundle)

    def test_post_as_of_source_requires_retrospective_and_never_counts(self) -> None:
        bundle = ready_bundle()
        annotation = bundle["source_annotations"][0]
        annotation["published_at"] = "2026-08-21"
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_annotation")
        annotation["retrospective"] = True
        result = MODULE.assemble(bundle)
        source = next(item for item in result["sources"] if item["source_id"] == annotation["source_id"])
        self.assertFalse(source["temporal_eligible"])
        self.assertEqual(result["status"], "blocking")
        self.assertIn("no_verified_supporting_source", result["claims"][0]["reasons"])

        bundle = ready_bundle()
        bundle["source_annotations"][0]["event_dates"] = ["2026-08-21"]
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_annotation")

    def test_missing_or_non_iso_published_at_never_silently_counts(self) -> None:
        bundle = ready_bundle()
        annotation = bundle["source_annotations"][0]
        annotation.pop("published_at")
        result = MODULE.assemble(bundle)
        source = next(
            item
            for item in result["sources"]
            if item["source_id"] == annotation["source_id"]
        )
        first_claim = result["claims"][0]
        self.assertFalse(source["temporal_eligible"])
        self.assertEqual(source["annotation"]["published_at"], None)
        self.assertFalse(first_claim["evidence"][0]["available_as_of"])
        self.assertIn("no_verified_supporting_source", first_claim["reasons"])
        self.assertEqual(result["status"], "blocking")

        bundle = ready_bundle()
        bundle["source_annotations"][0]["published_at"] = "2026/01/15"
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_date")

    def test_same_url_deduplicates_and_candidate_aliases_resolve(self) -> None:
        bundle = ready_bundle()
        first_entry = bundle["envelopes"][0]
        original = first_entry["envelope"]["candidates"][0]
        alias = "alias:duplicate-url"
        first_entry["envelope"]["candidates"].append(
            candidate(alias, canonical_url=original["canonical_url"])
        )
        original_id = original["candidate_id"]
        next(item for item in bundle["source_annotations"] if item["source_id"] == original_id)["source_id"] = alias
        find_claim(bundle, f"base:{first_entry['workstream_id']}")["evidence"][0]["source_id"] = alias
        expected = sum(
            item["minimum_evidence"]["verified_sources"] for item in bundle["plan"]["workstreams"]
        )
        result = MODULE.assemble(bundle)
        self.assertEqual(len(result["sources"]), expected)
        merged = next(item for item in result["sources"] if alias in item["candidate_ids"])
        self.assertIn(original_id, merged["candidate_ids"])
        self.assertEqual(len(merged["observations"]), 2)
        self.assertEqual(result["status"], "ready")

    def test_supported_inference_counts_independence_groups(self) -> None:
        bundle = ready_bundle()
        references = {link["source_id"] for link in find_claim(bundle, "cross-1")["evidence"]}
        for annotation in bundle["source_annotations"]:
            if annotation["source_id"] in references:
                annotation["independence_group"] = "same-publisher"
        result = MODULE.assemble(bundle)
        cross = next(item for item in result["claims"] if item["claim_id"] == "cross-1")
        self.assertIn(
            "supported_inference_requires_two_independent_evidence_groups",
            cross["reasons"],
        )
        self.assertFalse(result["gates"]["cross_axis_supported"])

    def test_missing_independence_group_defaults_to_each_deduplicated_source(self) -> None:
        bundle = ready_bundle()
        references = {link["source_id"] for link in find_claim(bundle, "cross-1")["evidence"]}
        for annotation in bundle["source_annotations"]:
            if annotation["source_id"] in references:
                annotation.pop("independence_group", None)
        result = MODULE.assemble(bundle)
        cross = next(item for item in result["claims"] if item["claim_id"] == "cross-1")
        self.assertEqual(len(cross["independent_support_groups"]), 2)
        self.assertEqual(result["status"], "ready")

    def test_each_workstream_needs_ready_base_claim(self) -> None:
        bundle = ready_bundle()
        removed = bundle["claims"].pop(0)
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["base_claims_complete"])
        gap = next(
            item for item in result["gaps"]
            if item.get("reason") == "ready_base_claim_required_for_every_workstream"
        )
        self.assertIn(removed["workstream_ids"][0], gap["missing_workstream_ids"])

    def test_timeline_and_cross_matrix_are_structural_gates(self) -> None:
        bundle = ready_bundle()
        for claim in bundle["claims"]:
            if claim["claim_id"].startswith("base:v"):
                claim.pop("event_date", None)
        self.assertFalse(MODULE.assemble(bundle)["gates"]["timeline_ready"])
        bundle = ready_bundle()
        bundle["claims"] = [
            claim for claim in bundle["claims"] if not claim["claim_id"].startswith("base:h")
        ]
        self.assertFalse(MODULE.assemble(bundle)["gates"]["cross_sectional_ready"])

    def test_planned_geography_and_language_coverage_is_executed(self) -> None:
        bundle = ready_bundle()
        target_id = bundle["plan"]["workstreams"][1]["id"]
        for annotation in bundle["source_annotations"]:
            if annotation["source_id"].startswith(f"src:{target_id}:"):
                annotation["geographies"] = ["China"]
                annotation["languages"] = ["zh"]
        result = MODULE.assemble(bundle)
        row = next(
            item
            for item in result["workstream_coverage"]
            if item["workstream_id"] == target_id
        )
        self.assertEqual(result["status"], "blocking")
        self.assertEqual(row["missing_dimensions"]["geographies"], ["United States"])
        self.assertEqual(row["missing_dimensions"]["languages"], ["en"])
        gap = next(item for item in result["gaps"] if item.get("gap_key") == f"coverage:{target_id}")
        self.assertEqual(gap["missing_dimensions"], row["missing_dimensions"])

    def test_unknown_planner_scope_is_nonretained_and_blocks_final_readiness(self) -> None:
        bundle = ready_bundle(unknown_scope_plan())
        result = MODULE.assemble(bundle)
        scope_gaps = [gap for gap in result["gaps"] if gap.get("kind") == "scope"]
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["scope_complete"])
        self.assertFalse(result["gates"]["final_report_ready"])
        self.assertEqual(
            {gap["dimension"] for gap in scope_gaps},
            {"geography", "languages"},
        )
        self.assertTrue(all(gap["retained"] is False for gap in scope_gaps))
        self.assertTrue(all("gap_key" not in gap for gap in scope_gaps))

        bundle["retained_gaps"] = [
            {
                "gap_key": "scope:geography",
                "search_attempts": [
                    {"query_or_path": "regional source query", "route": "official_site"},
                    {"query_or_path": "regional database query", "route": "database"},
                ],
                "impact": "The geography remains unknown.",
                "disclosure": "No geography was inferred.",
                "bounded_conclusion": "Do not generalize geographically.",
            }
        ]
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_retained_gap")

    def test_unknown_start_date_or_audience_is_nonretained_scope_gap(self) -> None:
        for field in ("start_date", "audience"):
            with self.subTest(field=field):
                brief = {
                    "subject": "Example Research System",
                    "object_type": "entity",
                    "subtype": "research product",
                    "goal": "Explain history, current structure, and bounded scenarios.",
                    "as_of": AS_OF,
                    "geography": ["China", "United States"],
                    "languages": ["zh", "en"],
                    "audience": "research lead",
                    "start_date": "2015-01-01",
                }
                brief[field] = "unknown"
                bundle = ready_bundle(PLANNER.build_plan(brief))
                result = MODULE.assemble(bundle)
                scope_gap = next(
                    gap
                    for gap in result["gaps"]
                    if gap.get("kind") == "scope" and gap.get("dimension") == field
                )
                self.assertEqual(result["status"], "blocking")
                self.assertFalse(result["gates"]["scope_complete"])
                self.assertFalse(result["gates"]["final_report_ready"])
                self.assertFalse(scope_gap["retained"])
                self.assertNotIn("gap_key", scope_gap)

                bundle["retained_gaps"] = [
                    {
                        "gap_key": f"scope:{field}",
                        "search_attempts": [
                            {"query_or_path": "one", "route": "official_site"},
                            {"query_or_path": "two", "route": "database"},
                        ],
                        "impact": "The scope remains unknown.",
                        "disclosure": "No value was inferred.",
                        "bounded_conclusion": "Do not assume the missing scope.",
                    }
                ]
                with self.assertRaises(MODULE.BundleError) as context:
                    MODULE.assemble(bundle)
                self.assertEqual(context.exception.category, "invalid_retained_gap")

    def test_coverage_dimensions_and_scope_gaps_must_match_brief(self) -> None:
        bundle = ready_bundle()
        bundle["plan"]["coverage_dimensions"]["geographies"] = ["Moon"]
        rebind_plan(bundle)
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

        bundle = ready_bundle(unknown_scope_plan())
        bundle["plan"]["coverage_dimensions"]["gaps"] = []
        rebind_plan(bundle)
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

        bundle = ready_bundle()
        bundle["plan"]["coverage_dimensions"]["gaps"] = [
            {
                "dimension": "geography",
                "status": "gap",
                "reason": "Contradicts the known brief scope.",
            }
        ]
        rebind_plan(bundle)
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

    def test_required_opportunity_map_binds_ready_base_claims_from_both_axes(self) -> None:
        bundle = ready_bundle(future_industry_plan())
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["opportunity_map_ready"])

        vertical_id = next(
            item["id"] for item in bundle["plan"]["workstreams"] if item["axis"] == "longitudinal"
        )
        horizontal_id = next(
            item["id"] for item in bundle["plan"]["workstreams"] if item["axis"] == "cross_sectional"
        )
        bundle["opportunity_map"] = [
            {
                "opportunity_id": "opp-1",
                "opportunity": "A bounded workflow opportunity.",
                "historical_driver": "A dated structural transition.",
                "current_condition": "A verified current market constraint.",
                "evidence_basis": [f"base:{vertical_id}", f"base:{horizontal_id}"],
                "beneficiaries": ["regulated professional teams"],
                "constraints": ["procurement and data controls"],
                "leading_indicators": ["verified adoption disclosures"],
                "invalidators": ["no measured workflow adoption"],
            }
        ]
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["gates"]["opportunity_map_ready"])
        self.assertEqual(result["views"]["opportunity_map"][0]["supported_axes"], ["cross_sectional", "longitudinal"])

        bundle["opportunity_map"][0]["evidence_basis"] = [f"base:{vertical_id}"]
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["opportunity_map_ready"])

    def test_opportunity_requirement_is_derived_from_brief_and_plan_must_agree(self) -> None:
        bundle = ready_bundle(future_industry_plan())
        contract = bundle["plan"]["report_contract"]
        contract["required_sections"].remove("opportunity_map")
        contract["opportunity_map"]["required"] = False
        contract["opportunity_map"]["section"] = None
        rebind_plan(bundle)
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

        bundle = ready_bundle()
        contract = bundle["plan"]["report_contract"]
        contract["required_sections"].append("opportunity_map")
        contract["opportunity_map"]["required"] = True
        contract["opportunity_map"]["section"] = "opportunity_map"
        rebind_plan(bundle)
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_plan")

    def test_delivery_language_contract_is_derived_from_brief(self) -> None:
        mutations = (
            lambda contract: contract.update(delivery_languages=["zh"]),
            lambda contract: contract.update(status="optional"),
            lambda contract: contract.update(derived_from="caller_override"),
            lambda contract: contract.update(all_delivery_languages_required=False),
            lambda contract: contract["per_language_requirements"][1].update(
                delivery_required=False
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = ready_bundle()
                contract = bundle["plan"]["report_contract"]["language_requirements"]
                self.assertEqual(contract["delivery_languages"], ["zh", "en"])
                mutation(contract)
                rebind_plan(bundle)
                with self.assertRaises(MODULE.BundleError) as context:
                    MODULE.assemble(bundle)
                self.assertEqual(context.exception.category, "invalid_plan")

        bundle = ready_bundle()
        contract = bundle["plan"]["report_contract"]["language_requirements"]
        contract["status"] = "optional"
        rebind_plan(bundle)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--bundle", "-"],
            input=json.dumps(bundle),
            text=True,
            capture_output=True,
            check=False,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(payload["status"], "invalid_bundle")
        self.assertFalse(payload["gates"]["final_report_ready"])
        self.assertEqual(payload["errors"][0]["category"], "invalid_plan")

    def test_compliant_retained_gap_yields_ready_with_disclosure(self) -> None:
        bundle = ready_bundle()
        scenario_workstreams = set(bundle["claims"][-1]["workstream_ids"])
        target = next(
            item for item in bundle["plan"]["workstreams"]
            if item["minimum_evidence"]["verified_sources"] == 2
            and item["id"] not in scenario_workstreams
        )
        entry = next(item for item in bundle["envelopes"] if item["workstream_id"] == target["id"])
        removed_ids = {item["candidate_id"] for item in entry["envelope"]["candidates"][1:]}
        entry["envelope"]["candidates"] = entry["envelope"]["candidates"][:1]
        bundle["source_annotations"] = [
            item for item in bundle["source_annotations"] if item["source_id"] not in removed_ids
        ]
        bundle["retained_gaps"] = [
            {
                "gap_key": f"coverage:{target['id']}",
                "search_attempts": [
                    {"query_or_path": "official archive query", "route": "official_site"},
                    {"query_or_path": "independent database query", "route": "database"},
                ],
                "impact": "The planned corroboration threshold is not fully met.",
                "disclosure": "Only one verified source was obtainable by the cutoff.",
                "bounded_conclusion": "Retain only the directly supported narrow fact.",
            }
        ]
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "ready_with_disclosure")
        self.assertTrue(result["gates"]["final_report_ready"])

    def test_retained_gap_is_strict_and_cannot_waive_base_gate(self) -> None:
        bundle = ready_bundle()
        base = bundle["claims"][0]
        base["basis"] = "unknown"
        bundle["retained_gaps"] = [
            {
                "gap_key": f"claim:{base['claim_id']}",
                "search_attempts": [
                    {"query_or_path": "official archive query", "route": "official_site"},
                    {"query_or_path": "database query", "route": "database"},
                ],
                "impact": "The claim cannot be established.",
                "disclosure": "The claim remains unknown.",
                "bounded_conclusion": "Do not state this claim as fact.",
            }
        ]
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["base_claims_complete"])
        bundle = ready_bundle()
        bundle["retained_gaps"] = [
            {
                "gap_key": "coverage:not-real",
                "search_attempts": [
                    {"query_or_path": "one", "route": "route_one"},
                    {"query_or_path": "two", "route": "route_two"},
                ],
                "impact": "impact",
                "disclosure": "disclosure",
                "bounded_conclusion": "bounded",
            }
        ]
        with self.assertRaises(MODULE.BundleError) as context:
            MODULE.assemble(bundle)
        self.assertEqual(context.exception.category, "invalid_retained_gap")

    def test_retained_attempts_need_distinct_queries_and_distinct_routes(self) -> None:
        for attempts in (
            [
                {"query_or_path": "query one", "route": "same_route"},
                {"query_or_path": "query two", "route": "same_route"},
            ],
            [
                {"query_or_path": "same query", "route": "route_one"},
                {"query_or_path": "same query", "route": "route_two"},
            ],
            ["query one", "query two"],
        ):
            with self.subTest(attempts=attempts):
                bundle = ready_bundle()
                base = bundle["claims"][0]
                base["basis"] = "unknown"
                bundle["retained_gaps"] = [
                    {
                        "gap_key": f"claim:{base['claim_id']}",
                        "search_attempts": attempts,
                        "impact": "The claim cannot be established.",
                        "disclosure": "The claim remains unknown.",
                        "bounded_conclusion": "Do not state this as fact.",
                    }
                ]
                with self.assertRaises(MODULE.BundleError) as context:
                    MODULE.assemble(bundle)
                self.assertEqual(context.exception.category, "invalid_retained_gap")

    def test_retained_gap_cannot_waive_unresolved_contradiction(self) -> None:
        bundle = ready_bundle()
        base = bundle["claims"][0]
        workstream_id = base["workstream_ids"][0]
        base["evidence"].append(
            evidence_link(source_id(workstream_id, 2), relation="contradicts")
        )
        bundle["retained_gaps"] = [
            {
                "gap_key": f"claim:{base['claim_id']}",
                "search_attempts": [
                    {"query_or_path": "official archive query", "route": "official_site"},
                    {"query_or_path": "database query", "route": "database"},
                ],
                "impact": "Verified sources conflict.",
                "disclosure": "The contradiction remains unresolved.",
                "bounded_conclusion": "Do not choose one account as settled fact.",
            }
        ]
        result = MODULE.assemble(bundle)
        self.assertEqual(result["status"], "blocking")
        self.assertFalse(result["gates"]["contradictions_resolved_or_retained"])

    def test_cli_rejects_invalid_json_duplicate_keys_and_nan(self) -> None:
        cases = [
            ("not json", "invalid_json"),
            ('{"schema_version":"1.0","schema_version":"1.0"}', "duplicate_json_key"),
            ('{"schema_version":"1.0","value":NaN}', "invalid_json_number"),
        ]
        for raw, category in cases:
            with self.subTest(category=category):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), "--bundle", "-"],
                    input=raw,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2)
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["errors"][0]["category"], category)


if __name__ == "__main__":
    unittest.main()
