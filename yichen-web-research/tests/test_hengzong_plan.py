#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLANNER_PATH = SKILL_ROOT / "scripts" / "plan_hengzong_research.py"
ASSEMBLER_PATH = SKILL_ROOT / "scripts" / "assemble_hengzong_evidence.py"


def load_planner():
    spec = importlib.util.spec_from_file_location(
        "test_plan_hengzong_research", PLANNER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load plan_hengzong_research.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


planner = load_planner()


def load_assembler():
    spec = importlib.util.spec_from_file_location(
        "test_planner_assembler_contract", ASSEMBLER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load assemble_hengzong_evidence.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def base_brief(**overrides):
    brief = {
        "subject": "Example Research Subject",
        "object_type": "entity",
        "subtype": "company",
        "goal": "Understand the subject's position and future trajectory",
        "as_of": "2026-08-20",
        "geography": "global",
        "languages": ["zh-CN", "en"],
        "audience": "strategy team",
        "start_date": "2020-01-01",
    }
    brief.update(overrides)
    return brief


class HengzongPlanTests(unittest.TestCase):
    def test_entity_plan_has_fixed_vertical_and_horizontal_coverage(self) -> None:
        payload = planner.build_plan(base_brief())

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertRegex(payload["plan_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(
            payload["classification"]["vertical_facets"],
            ["origin", "launch", "evolution", "decision_logic"],
        )
        self.assertEqual(
            payload["classification"]["horizontal_facets"],
            [
                "competition",
                "differentiation",
                "users",
                "ecosystem",
                "trajectory",
            ],
        )
        self.assertEqual(len(payload["workstreams"]), 9)
        self.assertEqual(
            set(payload["workstreams"][0]),
            {
                "id",
                "axis",
                "facet",
                "questions",
                "query_groups",
                "source_priorities",
                "minimum_evidence",
                "stop_conditions",
            },
        )

        decision = next(
            item
            for item in payload["workstreams"]
            if item["facet"] == "decision_logic"
        )
        self.assertEqual(
            decision["minimum_evidence"],
            {
                "verified_sources": 2,
                "primary_sources": 1,
                "independent_sources": 1,
            },
        )
        self.assertEqual(
            payload["evidence_policy"]["claim_requirements"]["decision_logic"][
                "allowed_labels"
            ],
            ["explicit", "supported_inference", "unknown"],
        )
        self.assertFalse(payload["gates"]["word_count_is_completion_gate"])
        self.assertEqual(
            payload["gates"]["completion_basis"],
            ["coverage", "contradiction", "gap"],
        )
        self.assertEqual(
            {item["axis"] for item in payload["workstreams"]},
            {"longitudinal", "cross_sectional"},
        )
        for item in payload["workstreams"]:
            self.assertEqual(
                set(item["source_priorities"]), {"L0", "L1", "L2", "L3"}
            )
            self.assertEqual(
                set(item["minimum_evidence"]),
                {"verified_sources", "primary_sources", "independent_sources"},
            )
        self.assertEqual(
            [tier["tier"] for tier in payload["evidence_policy"]["source_tiers"]],
            ["L0", "L1", "L2", "L3"],
        )
        self.assertEqual(payload["errors"], [])

    def test_industry_explicit_facets_preserve_valid_order(self) -> None:
        payload = planner.build_plan(
            base_brief(
                object_type="industry",
                subtype="software market",
                horizontal_facets=[
                    "players",
                    "business_models",
                    "regulation",
                    "capital",
                ],
            )
        )

        self.assertEqual(
            payload["classification"]["vertical_facets"],
            ["origin", "stages", "turning_points", "drivers"],
        )
        self.assertEqual(
            payload["classification"]["horizontal_facets"],
            ["players", "business_models", "regulation", "capital"],
        )
        selection = payload["classification"]["horizontal_selection"]
        self.assertEqual(selection["mode"], "explicit")
        self.assertEqual(selection["selection_rule"], "user_supplied")
        self.assertEqual(len(payload["workstreams"]), 8)

    def test_industry_default_facets_are_goal_sensitive_and_explained(self) -> None:
        payload = planner.build_plan(
            base_brief(
                object_type="industry",
                subtype="regulated services",
                goal="比较监管政策与合规风险",
            )
        )

        self.assertEqual(
            payload["classification"]["horizontal_facets"],
            ["regulation", "players", "value_chain", "regions", "users"],
        )
        selection = payload["classification"]["horizontal_selection"]
        self.assertEqual(selection["mode"], "goal_default")
        self.assertEqual(selection["selection_rule"], "regulation_policy")
        self.assertIn("监管", selection["matched_goal_terms"])
        self.assertTrue(selection["selection_reason"])

    def test_invalid_type_date_and_facet_counts_fail_closed(self) -> None:
        invalid_cases = (
            (
                base_brief(object_type="person"),
                "invalid_object_type",
            ),
            (
                base_brief(as_of="2026-02-30"),
                "invalid_date",
            ),
            (
                base_brief(
                    object_type="industry",
                    horizontal_facets=["players", "users"],
                ),
                "invalid_facet_count",
            ),
            (
                base_brief(
                    object_type="industry",
                    horizontal_facets=[
                        "value_chain",
                        "segments",
                        "business_models",
                        "players",
                        "regions",
                        "users",
                    ],
                ),
                "invalid_facet_count",
            ),
        )

        for brief, expected_code in invalid_cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(planner.PlannerError) as raised:
                    planner.build_plan(brief)
                self.assertEqual(raised.exception.code, expected_code)

    def test_plan_id_is_stable_for_equivalent_json_key_order(self) -> None:
        first = base_brief(
            geography=["China", "United States"],
            languages=["zh-CN", "en"],
            audience="strategy team",
            start_date="2020-01-01",
        )
        second = {key: first[key] for key in reversed(list(first))}

        first_plan = planner.build_plan(first)
        second_plan = planner.build_plan(second)
        self.assertEqual(first_plan["plan_id"], second_plan["plan_id"])
        self.assertEqual(first_plan, second_plan)

        body = {key: value for key, value in first_plan.items() if key != "plan_id"}
        expected = planner.hashlib.sha256(
            planner.canonical_json(body).encode("utf-8")
        ).hexdigest()[: planner.PLAN_ID_LENGTH]
        self.assertEqual(first_plan["plan_id"], expected)

    def test_explicit_unknown_scope_is_preserved_and_disclosed(self) -> None:
        payload = planner.build_plan(
            base_brief(
                geography=[],
                languages="unknown",
                audience=None,
                start_date="",
            )
        )

        for field in ("geography", "languages", "audience", "start_date"):
            self.assertEqual(payload["brief"][field], "unknown")
        self.assertEqual(
            payload["classification"]["scope_status"]["unknown_fields"],
            ["start_date", "geography", "languages", "audience"],
        )
        self.assertTrue(
            payload["classification"]["scope_status"]["scope_gap_required"]
        )
        limitations = "\n".join(payload["limitations"])
        for field in ("geography", "languages", "audience", "start_date"):
            self.assertIn(field, limitations)
        self.assertEqual(payload["coverage_dimensions"]["geographies"], [])
        self.assertEqual(payload["coverage_dimensions"]["languages"], [])
        self.assertEqual(
            {
                gap["dimension"]
                for gap in payload["coverage_dimensions"]["gaps"]
            },
            {"start_date", "geography", "languages", "audience"},
        )
        self.assertEqual(
            payload["coverage_dimensions"]["query_group_matrix"]["status"],
            "blocked_by_scope_gap",
        )
        self.assertEqual(
            payload["coverage_dimensions"]["query_group_matrix"][
                "blocking_dimensions"
            ],
            ["start_date", "geography", "languages", "audience"],
        )
        self.assertTrue(
            all(not item["query_groups"] for item in payload["workstreams"])
        )
        self.assertEqual(
            payload["report_contract"]["geography_requirements"]["status"],
            "gap_unknown",
        )
        self.assertEqual(
            payload["report_contract"]["language_requirements"]["status"],
            "gap_unknown",
        )

    def test_unknown_start_date_and_audience_block_query_matrix(self) -> None:
        payload = planner.build_plan(
            base_brief(start_date="unknown", audience="unknown")
        )

        scope_status = payload["classification"]["scope_status"]
        self.assertEqual(
            scope_status["unknown_fields"], ["start_date", "audience"]
        )
        self.assertTrue(scope_status["scope_gap_required"])
        dimensions = payload["coverage_dimensions"]
        self.assertEqual(
            [gap["dimension"] for gap in dimensions["gaps"]],
            ["start_date", "audience"],
        )
        self.assertEqual(
            dimensions["query_group_matrix"]["status"],
            "blocked_by_scope_gap",
        )
        self.assertEqual(
            dimensions["query_group_matrix"]["blocking_dimensions"],
            ["start_date", "audience"],
        )
        self.assertGreater(
            dimensions["query_group_matrix"]["groups_per_workstream"], 0
        )

    def test_china_us_bilingual_scope_generates_bounded_query_matrix(self) -> None:
        payload = planner.build_plan(
            base_brief(
                subject="人工智能产业 / Artificial Intelligence Industry",
                geography=["China", "United States"],
                languages=["zh-CN", "en"],
            )
        )

        dimensions = payload["coverage_dimensions"]
        self.assertEqual(dimensions["geographies"], ["China", "United States"])
        self.assertEqual(dimensions["languages"], ["zh-CN", "en"])
        self.assertEqual(dimensions["query_group_matrix"]["groups_per_workstream"], 4)
        self.assertEqual(dimensions["gaps"], [])
        self.assertEqual(
            [item["geography"] for item in dimensions["geography_requirements"]],
            ["China", "United States"],
        )
        self.assertTrue(
            all(
                item["cross_geography_comparison_required"]
                for item in dimensions["geography_requirements"]
            )
        )
        self.assertEqual(
            [item["language"] for item in dimensions["language_requirements"]],
            ["zh-CN", "en"],
        )
        self.assertTrue(
            all(
                item["search_required"] and item["delivery_required"]
                for item in dimensions["language_requirements"]
            )
        )

        expected_pairs = {
            ("China", "zh-CN"),
            ("China", "en"),
            ("United States", "zh-CN"),
            ("United States", "en"),
        }
        for workstream in payload["workstreams"]:
            groups = workstream["query_groups"]
            self.assertEqual(
                {(group["geography"], group["language"]) for group in groups},
                expected_pairs,
            )
            self.assertEqual(len(groups), 4)
            for group in groups:
                self.assertEqual(len(group["queries"]), 2)
                self.assertEqual(group["bounds"]["max_query_waves"], 2)
                self.assertEqual(group["bounds"]["max_queries_per_group"], 2)
                self.assertEqual(group["bounds"]["max_results_per_query"], 10)
                self.assertFalse(group["bounds"]["allow_unbounded_pagination"])
                for query in group["queries"]:
                    query_text = query["query_text"]
                    for pseudo_operator in (
                        "facet:",
                        "axis:",
                        "search_language:",
                        "time_scope:",
                        "evidence_intent:",
                    ):
                        self.assertNotIn(pseudo_operator, query_text)
                    self.assertRegex(query_text, r"20\d{2}")
                    if group["language_family"] == "zh":
                        self.assertIn("人工智能产业", query_text)
                        self.assertNotIn("Artificial Intelligence Industry", query_text)
                    else:
                        self.assertIn("Artificial Intelligence Industry", query_text)
                        self.assertNotIn("人工智能产业", query_text)
                self.assertNotEqual(
                    group["queries"][0]["query_text"],
                    group["queries"][1]["query_text"],
                )
                self.assertEqual(
                    group["localization_status"],
                    "native",
                )
                self.assertEqual(
                    group["subject_localization_status"],
                    "native_bilingual_subject_segment",
                )
                self.assertTrue(
                    group["geography_localization_status"].startswith("native_")
                )

        zh_geographies = {
            group["geography"]: group["geography_for_query"]
            for group in payload["workstreams"][0]["query_groups"]
            if group["language_family"] == "zh"
        }
        self.assertEqual(
            zh_geographies,
            {"China": "中国", "United States": "美国"},
        )

        origin = payload["workstreams"][0]
        zh_origin = next(
            group
            for group in origin["query_groups"]
            if group["language_family"] == "zh"
        )
        en_origin = next(
            group
            for group in origin["query_groups"]
            if group["language_family"] == "en"
        )
        self.assertIn("起源 前史", zh_origin["queries"][0]["query_text"])
        self.assertIn("官方档案", zh_origin["queries"][0]["query_text"])
        self.assertIn("独立报道", zh_origin["queries"][1]["query_text"])
        self.assertIn(
            "origin and antecedents", en_origin["queries"][0]["query_text"]
        )
        self.assertIn(
            "official archives", en_origin["queries"][0]["query_text"]
        )
        self.assertIn(
            "independent reporting", en_origin["queries"][1]["query_text"]
        )

        language_contract = payload["report_contract"]["language_requirements"]
        self.assertEqual(language_contract["status"], "required")
        self.assertEqual(language_contract["derived_from"], "brief.languages")
        self.assertEqual(language_contract["search_languages"], ["zh-CN", "en"])
        self.assertEqual(language_contract["delivery_languages"], ["zh-CN", "en"])
        self.assertEqual(language_contract["derived_from"], "brief.languages")
        self.assertTrue(language_contract["all_delivery_languages_required"])
        self.assertTrue(language_contract["all_delivery_languages_required"])
        self.assertNotIn("optional_delivery_languages", language_contract)
        self.assertTrue(
            all(
                item["delivery_required"]
                for item in language_contract["per_language_requirements"]
            )
        )
        self.assertEqual(
            payload["gates"]["coverage"]["required_geographies"],
            ["China", "United States"],
        )

    def test_untranslated_subject_and_neutral_language_are_disclosed(self) -> None:
        payload = planner.build_plan(
            base_brief(
                subject="OpenAI",
                geography="China",
                languages=["zh-CN", "ja"],
            )
        )
        groups = payload["workstreams"][0]["query_groups"]
        for group in groups:
            self.assertEqual(
                group["localization_status"], "source_subject_untranslated"
            )
            self.assertTrue(group["localization_gap"])
            self.assertIn("OpenAI", group["queries"][0]["query_text"])
        neutral = next(group for group in groups if group["language"] == "ja")
        self.assertEqual(neutral["language_family"], "neutral")
        self.assertIn(
            "official records original documents",
            neutral["queries"][0]["query_text"],
        )

    def test_chinese_geographies_are_reliably_localized_to_english(self) -> None:
        payload = planner.build_plan(
            base_brief(
                subject="人工智能产业 / Artificial Intelligence Industry",
                geography=["中国", "美国"],
                languages=["en"],
            )
        )
        groups = payload["workstreams"][0]["query_groups"]
        by_geography = {group["geography"]: group for group in groups}

        self.assertEqual(by_geography["中国"]["geography_for_query"], "in China")
        self.assertEqual(
            by_geography["美国"]["geography_for_query"], "in United States"
        )
        for source_geography, group in by_geography.items():
            self.assertEqual(group["localization_status"], "native")
            self.assertNotIn("geography_localization_gap", group)
            for query in group["queries"]:
                self.assertNotIn(source_geography, query["query_text"])
                self.assertIn("Artificial Intelligence Industry", query["query_text"])

    def test_unknown_chinese_geography_in_english_is_retained_as_gap(self) -> None:
        payload = planner.build_plan(
            base_brief(
                subject="人工智能产业 / Artificial Intelligence Industry",
                geography="川渝地区",
                languages=["en"],
            )
        )
        group = payload["workstreams"][0]["query_groups"][0]

        self.assertEqual(
            group["localization_status"], "source_geography_untranslated"
        )
        self.assertEqual(
            group["geography_localization_status"],
            "source_geography_untranslated",
        )
        self.assertEqual(group["geography_for_query"], "川渝地区")
        self.assertTrue(group["geography_localization_gap"])
        for query in group["queries"]:
            self.assertIn("川渝地区", query["query_text"])
            self.assertIn("Artificial Intelligence Industry", query["query_text"])
            for pseudo_operator in (
                "facet:",
                "axis:",
                "search_language:",
                "time_scope:",
                "evidence_intent:",
            ):
                self.assertNotIn(pseudo_operator, query["query_text"])

    def test_generated_plan_is_accepted_by_assembler_plan_validator(self) -> None:
        assembler = load_assembler()
        plan = planner.build_plan(base_brief())

        validated = assembler._validate_plan(plan)
        self.assertEqual(validated[0], plan["plan_id"])
        self.assertEqual(
            {item["axis"] for item in validated[1]},
            {"longitudinal", "cross_sectional"},
        )

    def test_industry_future_goal_requires_opportunity_map_without_extra_facet(self) -> None:
        payload = planner.build_plan(
            base_brief(
                object_type="industry",
                subtype="market",
                goal="评估行业未来机会与 future opportunity",
            )
        )

        horizontal_facets = payload["classification"]["horizontal_facets"]
        self.assertGreaterEqual(len(horizontal_facets), 3)
        self.assertLessEqual(len(horizontal_facets), 5)
        self.assertNotIn("opportunity_map", horizontal_facets)
        self.assertIn(
            "opportunity_map",
            payload["report_contract"]["required_sections"],
        )
        opportunity = payload["report_contract"]["opportunity_map"]
        self.assertTrue(opportunity["required"])
        self.assertTrue(opportunity["not_a_horizontal_facet"])
        self.assertEqual(opportunity["section"], "opportunity_map")
        self.assertIn("opportunity_id", opportunity["required_fields"])
        self.assertIn("未来", opportunity["trigger_terms"])
        self.assertIn("opportunity", opportunity["trigger_terms"])

    def test_report_contract_matches_evidence_and_retained_gap_schema(self) -> None:
        contract = planner.build_plan(base_brief())["report_contract"]

        self.assertEqual(
            contract["evidence_link_fields"],
            [
                "source_id",
                "relation",
                "locator",
                "event_date",
                "scope",
                "notes",
            ],
        )
        link_requirements = contract["evidence_link_requirements"][
            "supports_or_contradicts"
        ]
        self.assertEqual(
            link_requirements["required_fields"],
            ["source_id", "relation", "locator", "event_date", "scope"],
        )
        self.assertEqual(link_requirements["optional_fields"], ["notes"])

        annotations = contract["source_annotation_fields"]
        for field in (
            "geographies",
            "languages",
            "retrospective",
            "pre_scope_context",
        ):
            self.assertIn(field, annotations)

        retained = contract["retained_gap_contract"]
        self.assertEqual(retained["bundle_field"], "retained_gaps")
        attempts = retained["search_attempts"]
        self.assertEqual(attempts["type"], "array_of_objects")
        self.assertEqual(
            attempts["item_required_fields"], ["query_or_path", "route"]
        )
        self.assertEqual(attempts["minimum_items"], 2)
        self.assertEqual(attempts["minimum_distinct_query_or_path_values"], 2)
        self.assertEqual(attempts["minimum_distinct_route_values"], 2)
        self.assertTrue(attempts["all_query_or_path_values_must_be_distinct"])
        self.assertTrue(attempts["all_route_values_must_be_distinct"])

    def test_scope_keys_must_be_present_even_when_unknown(self) -> None:
        brief = base_brief()
        brief.pop("geography")
        with self.assertRaises(planner.PlannerError) as raised:
            planner.build_plan(brief)
        self.assertEqual(raised.exception.code, "missing_required_fields")
        self.assertEqual(raised.exception.field, "geography")

    def test_stdin_cli_returns_json_and_nonzero_json_errors(self) -> None:
        success = subprocess.run(
            [sys.executable, str(PLANNER_PATH), "--brief", "-"],
            input=json.dumps(base_brief(), ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(success.stderr, "")
        payload = json.loads(success.stdout)
        self.assertEqual(payload["brief"]["subject"], "Example Research Subject")
        self.assertEqual(payload["errors"], [])

        failure = subprocess.run(
            [sys.executable, str(PLANNER_PATH), "--brief", "-"],
            input=json.dumps(base_brief(as_of="08/20/2026")),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(failure.returncode, 0)
        error_payload = json.loads(failure.stdout)
        self.assertIsNone(error_payload["plan_id"])
        self.assertEqual(error_payload["errors"][0]["code"], "invalid_date")
        self.assertEqual(
            set(error_payload),
            {
                "schema_version",
                "plan_id",
                "brief",
                "classification",
                "workstreams",
                "coverage_dimensions",
                "evidence_policy",
                "gates",
                "report_contract",
                "limitations",
                "errors",
            },
        )


if __name__ == "__main__":
    unittest.main()
