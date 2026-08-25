#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RouterContractTests(unittest.TestCase):
    def test_router_names_all_children(self) -> None:
        source = (ROOT / "yichen-web-research/SKILL.md").read_text(encoding="utf-8")
        for name in (
            "yichen-unified-search",
            "yichen-content-archive",
            "yichen-bookmarks-export",
            "yichen-asr",
        ):
            self.assertIn(name, source)

    def test_router_is_the_only_top_level_entry(self) -> None:
        retired_name = "agent" + "-reach"
        self.assertFalse((ROOT / retired_name).exists())
        source = (ROOT / "yichen-web-research/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("唯一的互联网研究总入口", source)
        self.assertIn("Use when an internet-research request", source)

    def test_download_executors_have_single_source(self) -> None:
        archive_scripts = ROOT / "yichen-content-archive/scripts"
        router_scripts = ROOT / "yichen-web-research/scripts"
        for name in (
            "wechat_mp_local.py",
            "xiaoyuzhou_stepfun.py",
            "xiaoyuzhou_opencli.py",
            "x_known_url.py",
        ):
            self.assertTrue((archive_scripts / name).is_file())
            self.assertFalse((router_scripts / name).exists())
        self.assertEqual(
            {path.name for path in router_scripts.glob("*.py")},
            {
                "assemble_hengzong_evidence.py",
                "doctor_yichen.py",
                "plan_hengzong_research.py",
                "validate_family.py",
            },
        )

    def test_search_and_archive_do_not_auto_chain(self) -> None:
        router = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        search = (ROOT / "yichen-unified-search/SKILL.md").read_text(
            encoding="utf-8"
        )
        archive = (ROOT / "yichen-content-archive/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("仅在用户明确要求归档且范围已限定时", router)
        self.assertIn("搜索结束后不得自动归档或下载", router)
        self.assertNotIn(
            "-> 用户确认或原请求已明确选择范围\n  -> yichen-content-archive",
            router,
        )
        self.assertIn("不下载媒体、不归档", search)
        self.assertIn("不得执行关键词搜索", archive)

    def test_x_search_and_known_url_have_separate_children(self) -> None:
        router = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Grok CLI 原生 `x_search` 优先", router)
        self.assertIn("匿名 FxTwitter → Jina 优先", router)

    def test_asr_uses_unified_child_route(self) -> None:
        router = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        asr = (ROOT / "yichen-asr/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("| `$yichen-asr` |", router)
        self.assertIn("Step ASR 与豆包 ASR", asr)
        self.assertIn("不得跨服务商重提", asr)

    def test_trigger_matrix_has_unambiguous_expected_skill(self) -> None:
        matrix = json.loads(
            (ROOT / "yichen-web-research/tests/trigger_matrix.json").read_text(
                encoding="utf-8"
            )
        )
        by_case = {row["case"]: row["expected_skill"] for row in matrix}
        self.assertEqual(
            by_case["four_platform_search_only"],
            "yichen-unified-search",
        )
        self.assertEqual(
            by_case["search_then_archive"],
            "yichen-web-research",
        )
        self.assertEqual(
            by_case["horizontal_vertical_deep_research"],
            "yichen-web-research",
        )
        self.assertEqual(
            by_case["bounded_site_map"],
            "yichen-unified-search",
        )
        self.assertEqual(
            by_case["explicit_zhihu_search"],
            "yichen-unified-search",
        )
        self.assertEqual(
            by_case["negative_opinion_daily_report"],
            "public-opinion-monitor",
        )
        self.assertEqual(len(by_case), len(matrix))

    def test_hengzong_research_is_offline_evidence_protocol(self) -> None:
        root = ROOT / "yichen-web-research"
        source = (root / "SKILL.md").read_text(encoding="utf-8")
        reference = (root / "references/hengzong-research.md").read_text(
            encoding="utf-8"
        )
        planner = (root / "scripts/plan_hengzong_research.py").read_text(
            encoding="utf-8"
        )
        assembler = (root / "scripts/assemble_hengzong_evidence.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("横纵研究模式", source)
        self.assertIn("past_event -> present_effect -> implication", source)
        self.assertIn("固定 1–3 万字不是完成标准", source)
        self.assertIn("搜索完成本身绝不转移归档授权", source)
        self.assertIn("claim-source ledger", reference)
        self.assertIn("event_date", reference)
        self.assertIn("published_at", reference)
        self.assertIn("supported_inference", reference)
        self.assertIn("invalidators", reference)
        for marker in (
            "query_groups",
            "independence_group",
            "retrospective",
            "ready_with_disclosure",
            "bounded_conclusion",
            "query_or_path",
            "opportunity_map",
            "双语报告契约",
            "temporal-eligible verified source",
            "contested",
            "query_text",
            "localization_status=native",
            "geography_localization_status",
        ):
            self.assertIn(marker, reference)

        for marker in (
            '"query_groups"',
            '"coverage_dimensions"',
            '"opportunity_map"',
            '"opportunity_id"',
            '"delivery_languages"',
            '"source_annotation_fields"',
            '"evidence_link_requirements"',
            '"retained_gap_contract"',
            '"subject_localization_status"',
            '"geography_localization_status"',
            '"geography_localization_gap"',
        ):
            self.assertIn(marker, planner)

        for marker in (
            "canonical hash of the current plan body",
            "bundle.plan_id must be present and exactly match canonical plan.plan_id",
            "Envelope research_context plan_id must be present and match exactly",
            "plan.brief.start_date",
            "plan.brief.as_of",
            "Supporting and contradicting evidence links require a non-empty locator",
            "Supporting and contradicting evidence links require event_date",
            "Supporting and contradicting evidence links require scope",
            '"event_date": event_date',
            '"scope": scope',
            '"notes": notes',
            '"geographies": geographies',
            '"languages": languages',
            "dimension_counts",
            "retained_gaps",
            "search_attempts",
            "query_or_path",
            "distinct query_or_path and route values",
            "bounded_conclusion",
            "independence_group",
            "retrospective",
            "base_claims_complete",
            "timeline_ready",
            "cross_sectional_ready",
            "opportunity_map_ready",
            'status = "contested"',
            'status = "blocking"',
            '"ready_with_disclosure"',
        ):
            self.assertIn(marker, assembler)

        for script in (planner, assembler):
            for forbidden in (
                "import requests",
                "from requests",
                "urllib.request",
                "httpx",
                "opencli ",
            ):
                self.assertNotIn(forbidden, script)
        self.assertIn("Offline reducer only", assembler)

    def test_firecrawl_is_explicit_bounded_and_key_check_is_offline(self) -> None:
        source = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        doctor = (
            ROOT / "yichen-web-research/scripts/doctor_yichen.py"
        ).read_text(encoding="utf-8")
        self.assertIn("不进入默认搜索链", source)
        self.assertIn("最多 100 条", source)
        self.assertIn("只保留同源", source)
        self.assertIn("不声明支持 Crawl", source)
        self.assertIn("network_probe_performed", doctor)
        self.assertIn("FIRECRAWL_KEY_FILE.lstat()", doctor)
        self.assertNotIn("api.firecrawl.dev", doctor)

    def test_zhihu_is_explicit_public_backend_with_offline_doctor(self) -> None:
        source = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        doctor = (
            ROOT / "yichen-web-research/scripts/doctor_yichen.py"
        ).read_text(encoding="utf-8")
        adapter = ROOT / "yichen-unified-search/scripts/zhihu_adapter.py"

        self.assertTrue(adapter.is_file())
        self.assertIn("显式 `zhihu` 平台后端", source)
        self.assertIn("不替换 AnySearch", source)
        for forbidden_route in ("global_search", "zhida", "answer", "`me`"):
            self.assertIn(forbidden_route, source)
        self.assertIn('os.environ.get("ZHIHU_CLI")', doctor)
        self.assertIn("SAFE_METADATA_ENV_NAMES", doctor)
        self.assertIn("environment = safe_metadata_environment()", doctor)
        self.assertNotIn("environment = dict(os.environ)", doctor)
        self.assertIn('zhihu_metadata(("version",))', doctor)
        self.assertIn('zhihu_metadata(("capabilities",))', doctor)
        self.assertIn('zhihu_metadata(("auth", "status"))', doctor)
        self.assertNotIn('zhihu_metadata(("search"', doctor)
        self.assertNotIn('zhihu_metadata(("hot"', doctor)

    def test_bounded_public_session_reuse_keeps_high_risk_gate(self) -> None:
        source = (ROOT / "yichen-web-research/SKILL.md").read_text(
            encoding="utf-8"
        )
        doctor = (
            ROOT / "yichen-web-research/scripts/doctor_yichen.py"
        ).read_text(encoding="utf-8")
        self.assertIn("小红书最多 20 条", source)
        self.assertIn("抖音最多 30 条", source)
        self.assertIn("请求间隔不少于 5 秒", source)
        self.assertIn("私域读取必须停下", source)
        self.assertIn('"current_turn_authorization_required": False', doctor)
        self.assertIn(
            '"write_or_private_scope_authorization_required": True',
            doctor,
        )

    def test_portable_doctor_has_no_personal_absolute_path(self) -> None:
        doctor = (
            ROOT / "yichen-web-research/scripts/doctor_yichen.py"
        ).read_text(encoding="utf-8")
        self.assertIn("YICHEN_SKILLS_ROOT", doctor)
        self.assertIn("FIRECRAWL_KEY_FILE", doctor)
        self.assertIn("CODEX_CONFIG", doctor)
        self.assertNotIn("/" + "Users/", doctor)

    def test_public_opinion_does_not_claim_generic_search(self) -> None:
        path = ROOT / "public-opinion-monitor/SKILL.md"
        if not path.is_file():
            self.skipTest("optional public-opinion-monitor is not installed")
        source = path.read_text(
            encoding="utf-8"
        )
        frontmatter = source.split("---", 2)[1]
        self.assertNotIn("“四平台搜索”", frontmatter)
        self.assertIn("普通跨平台关键词搜索", frontmatter)
        self.assertIn("yichen-unified-search", frontmatter)
        self.assertIn("当轮明确授权", source)
        self.assertIn("--allow-chrome-login", source)

    def test_bookmark_backend_contains_no_download_commands(self) -> None:
        source = (
            ROOT / "yichen-bookmarks-export/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("不得下载媒体、正文、字幕或附件", source)
        self.assertIn("导出授权不等于下载授权", source)


if __name__ == "__main__":
    unittest.main()
