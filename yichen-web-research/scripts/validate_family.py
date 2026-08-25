#!/usr/bin/env python3
"""Validate the local Yichen web-research Skill family without private reads."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = Path(
    os.environ.get("YICHEN_SKILLS_ROOT", str(REPOSITORY_ROOT))
).expanduser()
FAMILY = (
    "yichen-web-research",
    "yichen-unified-search",
    "yichen-content-archive",
    "yichen-bookmarks-export",
    "yichen-asr",
)
CLIENT_ROOTS = tuple(
    Path(value).expanduser()
    for value in os.environ.get("YICHEN_VALIDATE_CLIENT_ROOTS", "").split(
        os.pathsep
    )
    if value
)
VALIDATOR = Path(
    os.environ.get(
        "SKILL_QUICK_VALIDATE",
        str(
            Path.home()
            / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"
        ),
    )
).expanduser()


def run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def frontmatter_name(skill_file: Path) -> str | None:
    text = skill_file.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*([a-z0-9-]+)\s*$", text)
    return match.group(1) if match else None


def check_doctor() -> dict:
    doctor = SKILLS_ROOT / "yichen-web-research/scripts/doctor_yichen.py"
    result = run([sys.executable, str(doctor)], timeout=45)
    if result.returncode:
        return {
            "ok": False,
            "error": result.stderr.strip() or f"exit={result.returncode}",
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"invalid doctor JSON: {exc}"}

    zhihu = payload.get("zhihu", {})
    firecrawl = payload.get("web", {}).get("firecrawl", {})
    invariants = {
        "xiaohongshu_bounded_readonly_reuse": payload.get("xiaohongshu", {}).get(
            "current_turn_authorization_required"
        )
        is False,
        "douyin_bounded_readonly_reuse": payload.get("douyin", {}).get(
            "current_turn_authorization_required"
        )
        is False,
        "xiaohongshu_dangerous_scope_still_requires_authorization": payload.get(
            "xiaohongshu", {}
        ).get("write_or_private_scope_authorization_required")
        is True,
        "douyin_dangerous_scope_still_requires_authorization": payload.get(
            "douyin", {}
        ).get("write_or_private_scope_authorization_required")
        is True,
        "toutiao_anonymous": payload.get("toutiao", {}).get(
            "login_required_for_search"
        )
        is False,
        "toutiao_no_user_chrome": payload.get("toutiao", {}).get(
            "user_chrome_state_used"
        )
        is False,
        "toutiao_no_video": payload.get("toutiao", {}).get(
            "video_results_included"
        )
        is False,
        "toutiao_no_batch": payload.get("toutiao", {}).get(
            "batch_search_allowed"
        )
        is False,
        "x_bookmarks_backend_identified": payload.get("x_bookmarks", {}).get(
            "status"
        )
        in {"ok", "warn"},
        "x_search_contract_is_grok_first": (
            payload.get("twitter", {}).get("active_backend")
            in {None, "official_cli_account_quota"}
            and payload.get("twitter", {}).get("primary_login_required") is True
            and payload.get("twitter", {}).get("search_route", [None])[0]
            == "official_cli_account_quota"
            and payload.get("twitter", {}).get("search_route", [None, None])[1]
            == "fxtwitter-public"
            and payload.get("twitter", {}).get("fxtwitter_fallback_condition")
            == "explicit_account_quota_exhausted_only"
        ),
        "x_known_url_primary_is_anonymous": payload.get("twitter", {}).get(
            "known_url_adapter_ready"
        )
        is True,
        "asr_route_identified": payload.get("asr", {}).get("status")
        in {"ok", "warn"},
        "asr_billing_not_assumed": payload.get("asr", {}).get(
            "billing_status"
        )
        in {"unknown", "unknown_requires_console_login"},
        "firecrawl_adapter_present": firecrawl.get("adapter_ready") is True,
        "firecrawl_is_explicit_and_offline": (
            firecrawl.get("default_backend") is False
            and firecrawl.get("network_probe_performed") is False
            and firecrawl.get("credential_source")
            in {None, "environment", "private_file"}
        ),
        "zhihu_adapter_present": zhihu.get("adapter_ready") is True,
        "zhihu_cli_or_auth_missing_is_nonfatal": (
            zhihu.get("status") in {"ok", "warn"}
            and isinstance(zhihu.get("cli_ready"), bool)
            and isinstance(zhihu.get("auth_configured"), bool)
        ),
        "zhihu_keychain_source_only": zhihu.get("credential_source")
        in {None, "keychain"},
        "zhihu_offline_explicit_public_only": (
            zhihu.get("network_probe_performed") is False
            and zhihu.get("default_backend") is False
            and zhihu.get("public_commands_only") is True
            and zhihu.get("personal_commands_exposed") is False
        ),
    }
    return {
        "ok": all(invariants.values()),
        "invariants": invariants,
        "statuses": {
            key: value.get("status")
            for key, value in payload.items()
            if isinstance(value, dict)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="also run the read-only multi-backend doctor and assert safety invariants",
    )
    args = parser.parse_args()

    checks: dict[str, object] = {}
    failures: list[str] = []

    for name in FAMILY:
        root = SKILLS_ROOT / name
        skill_file = root / "SKILL.md"
        exists = root.is_dir() and skill_file.is_file()
        checks[f"{name}.exists"] = exists
        if not exists:
            failures.append(f"missing skill: {name}")
            continue

        actual_name = frontmatter_name(skill_file)
        checks[f"{name}.frontmatter"] = actual_name
        if actual_name != name:
            failures.append(f"{name}: frontmatter name is {actual_name!r}")

        source = skill_file.read_text(encoding="utf-8")
        no_template = "[TODO" not in source and "TODO:" not in source
        checks[f"{name}.no_template"] = no_template
        if not no_template:
            failures.append(f"{name}: template marker remains")

        if VALIDATOR.is_file():
            validation = run([sys.executable, str(VALIDATOR), str(root)])
            valid = validation.returncode == 0
            checks[f"{name}.quick_validate"] = {
                "status": "passed" if valid else "failed",
                "returncode": validation.returncode,
            }
            if not valid:
                failures.append(
                    f"{name}: quick_validate failed: "
                    f"{validation.stdout.strip()} {validation.stderr.strip()}"
                )
        else:
            checks[f"{name}.quick_validate"] = {
                "status": "skipped",
                "reason": "external quick_validate.py is not installed",
            }

    test_commands = {
        "yichen-web-research": [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(SKILLS_ROOT / "yichen-web-research/tests"),
            "-p",
            "test_*.py",
        ],
        "yichen-unified-search": [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(SKILLS_ROOT / "yichen-unified-search/tests"),
            "-p",
            "test_*.py",
        ],
        "yichen-content-archive": [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(SKILLS_ROOT / "yichen-content-archive/tests"),
            "-p",
            "test_*.py",
        ],
        "yichen-bookmarks-export": [
            sys.executable,
            str(
                SKILLS_ROOT
                / "yichen-bookmarks-export/tests/test_skill_contract.py"
            ),
        ],
        "yichen-asr": [
            sys.executable,
            str(SKILLS_ROOT / "yichen-asr/tests/test_contract.py"),
        ],
    }
    for name, command in test_commands.items():
        result = run(command)
        ok = result.returncode == 0
        checks[f"{name}.tests"] = {
            "ok": ok,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
        if not ok:
            failures.append(f"{name}: offline tests failed")

    syntax_failures: list[str] = []
    for name in FAMILY:
        for script in (SKILLS_ROOT / name).rglob("*.py"):
            try:
                ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
            except (OSError, SyntaxError) as exc:
                syntax_failures.append(f"{script}: {exc}")
    checks["python_ast"] = {
        "ok": not syntax_failures,
        "failures": syntax_failures,
    }
    failures.extend(syntax_failures)

    link_failures: list[str] = []
    for client_root in CLIENT_ROOTS:
        for name in FAMILY:
            link = client_root / name
            target = SKILLS_ROOT / name
            if not link.is_symlink():
                link_failures.append(f"{link}: not a symlink")
                continue
            if link.resolve() != target.resolve():
                link_failures.append(f"{link}: target mismatch")
    checks["client_links"] = {
        "ok": not link_failures,
        "failures": link_failures,
    }
    failures.extend(link_failures)

    retired_name = "agent" + "-reach"
    retired_paths = [
        SKILLS_ROOT / retired_name,
        *(root / retired_name for root in CLIENT_ROOTS),
        Path.home() / ".local/bin" / retired_name,
    ]
    retired_failures = [
        str(path)
        for path in retired_paths
        if path.exists() or path.is_symlink()
    ]
    if shutil.which(retired_name):
        retired_failures.append(f"command still resolves: {retired_name}")

    source_failures: list[str] = []
    for name in FAMILY:
        for path in (SKILLS_ROOT / name).rglob("*"):
            if path.suffix not in {".md", ".py", ".yaml", ".yml", ".json"}:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if retired_name in source.lower():
                source_failures.append(str(path))
    checks["retired_entry_absent"] = {
        "ok": not retired_failures and not source_failures,
        "paths": retired_failures,
        "source_files": source_failures,
    }
    if retired_failures or source_failures:
        failures.append("retired research entry remains")

    markdown_link_failures: list[str] = []
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for name in FAMILY:
        for path in (SKILLS_ROOT / name).rglob("*.md"):
            source = path.read_text(encoding="utf-8")
            for target in link_pattern.findall(source):
                target = target.strip().strip("<>")
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target_path = target.split("#", 1)[0]
                if not target_path:
                    continue
                resolved = (
                    Path(target_path)
                    if target_path.startswith("/")
                    else path.parent / target_path
                )
                if not resolved.exists():
                    markdown_link_failures.append(
                        f"{path}: missing link target {target}"
                    )
    checks["markdown_links"] = {
        "ok": not markdown_link_failures,
        "failures": markdown_link_failures,
    }
    failures.extend(markdown_link_failures)

    router_source = (
        SKILLS_ROOT / "yichen-web-research/SKILL.md"
    ).read_text(encoding="utf-8")
    hengzong_scripts = {
        name: SKILLS_ROOT / "yichen-web-research/scripts" / name
        for name in (
            "plan_hengzong_research.py",
            "assemble_hengzong_evidence.py",
        )
    }
    hengzong_forbidden_markers = (
        "import requests",
        "from requests",
        "urllib.request",
        "import httpx",
        "opencli ",
    )
    router_metadata_checks = {
        "english_trigger_present": "Use when an internet-research request"
        in router_source,
        "all_child_names_present": all(
            name in router_source
            for name in (
                "yichen-unified-search",
                "yichen-content-archive",
                "yichen-bookmarks-export",
                "yichen-asr",
            )
        ),
        "hengzong_reference_is_single_bounded_protocol": {
            path.name
            for path in (
                SKILLS_ROOT / "yichen-web-research/references"
            ).glob("*")
            if path.is_file()
        }
        == {"hengzong-research.md"},
        "router_scripts_are_bounded": {
            path.name
            for path in (
                SKILLS_ROOT / "yichen-web-research/scripts"
            ).glob("*.py")
        }
        == {
            "assemble_hengzong_evidence.py",
            "doctor_yichen.py",
            "plan_hengzong_research.py",
            "validate_family.py",
        },
        "hengzong_scripts_are_offline": all(
            path.is_file()
            and all(
                marker not in path.read_text(encoding="utf-8")
                for marker in hengzong_forbidden_markers
            )
            for path in hengzong_scripts.values()
        ),
        "zhihu_adapter_present": (
            SKILLS_ROOT
            / "yichen-unified-search/scripts/zhihu_adapter.py"
        ).is_file(),
    }
    checks["router_metadata"] = router_metadata_checks
    if not all(router_metadata_checks.values()):
        failures.append("router metadata or bounded research structure is incomplete")

    hengzong_reference = (
        SKILLS_ROOT
        / "yichen-web-research/references/hengzong-research.md"
    ).read_text(encoding="utf-8")
    planner_source = hengzong_scripts[
        "plan_hengzong_research.py"
    ].read_text(encoding="utf-8")
    assembler_source = hengzong_scripts[
        "assemble_hengzong_evidence.py"
    ].read_text(encoding="utf-8")
    hengzong_contract_checks = {
        "archive_is_explicit_conditional_branch": (
            "仅在用户明确要求归档且范围已限定时" in router_source
            and "搜索结束后不得自动归档或下载" in router_source
            and "只有用户明确要求持久化原文或下载媒体" in router_source
        ),
        "workstreams_have_bounded_scope_query_groups": all(
            marker in planner_source
            for marker in (
                '"query_groups"',
                '"coverage_dimensions"',
                '"geography_requirements"',
                '"language_requirements"',
                "MAX_QUERY_GROUPS_PER_WORKSTREAM",
                '"subject_localization_status"',
                '"geography_localization_status"',
                '"geography_localization_gap"',
            )
        ) and all(
            marker in hengzong_reference
            for marker in (
                "每个 workstream 都必须有自己的 `query_groups`",
                "blocking gap",
                "`retained_gaps`",
                "temporal-eligible verified source",
                "`query_text` 必须是",
                "`localization_status=native`",
            )
        ) and all(
            marker in assembler_source
            for marker in (
                '"geographies": geographies',
                '"languages": languages',
                "dimension_counts",
                "missing_dimensions",
            )
        ),
        "plan_and_evidence_are_fail_closed": all(
            marker in assembler_source
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
                "independence_group",
                "retrospective",
                "base_claims_complete",
                "timeline_ready",
                "cross_sectional_ready",
                'status = "contested"',
            )
        ) and all(
            marker in planner_source
            for marker in (
                '"source_annotation_fields"',
                '"geographies"',
                '"languages"',
                '"retrospective"',
                '"evidence_link_requirements"',
                '"supports_or_contradicts"',
                '"event_date"',
                '"scope"',
                '"notes"',
            )
        ),
        "retained_disclosure_is_bounded": all(
            marker in assembler_source
            for marker in (
                "retained_gaps",
                "query_or_path",
                "distinct query_or_path and route values",
                "bounded_conclusion",
                'status = "blocking"',
                '"ready_with_disclosure"',
            )
        ) and all(
            marker in planner_source
            for marker in (
                '"retained_gap_contract"',
                '"query_or_path"',
                '"route"',
                '"minimum_items"',
            )
        ) and all(
            marker in hengzong_reference
            for marker in (
                "至少 2 条结构化 `search_attempts`",
                "各条 query/path 彼此不同、route 也彼此不同",
                "Retained disclosure 只改变",
                "任一结构门失败仍为 `blocking`",
            )
        ),
        "opportunity_and_language_are_report_contracts": all(
            marker in planner_source
            for marker in (
                '"opportunity_map"',
                '"opportunity_id"',
                '"delivery_languages"',
                '"required_sections"',
            )
        ) and all(
            marker in assembler_source
            for marker in (
                "opportunity_map_ready",
                "nonempty_opportunity_map_required_by_plan",
                "opportunity_evidence_basis_requires_ready_claim_ids",
                "opportunity_requires_longitudinal_and_cross_sectional_ready_base_claims",
            )
        ) and all(
            marker in hengzong_reference
            for marker in (
                "`report_contract` 必须显式要求非空 `opportunity_map`",
                "`report_contract.language_requirements.delivery_languages` 必须同时列出两种语言",
            )
        ),
    }
    checks["hengzong_contract"] = hengzong_contract_checks
    if not all(hengzong_contract_checks.values()):
        failures.append("horizontal/longitudinal research contract markers are incomplete")

    boundary_sources = {
        "search": (
            SKILLS_ROOT / "yichen-unified-search/SKILL.md"
        ).read_text(encoding="utf-8"),
        "archive": (
            SKILLS_ROOT / "yichen-content-archive/SKILL.md"
        ).read_text(encoding="utf-8"),
        "bookmarks": (
            SKILLS_ROOT / "yichen-bookmarks-export/SKILL.md"
        ).read_text(encoding="utf-8"),
        "asr": (
            SKILLS_ROOT / "yichen-asr/SKILL.md"
        ).read_text(encoding="utf-8"),
    }
    boundary_checks = {
        "known_url_handoff": "handoff_required"
        in (
            SKILLS_ROOT
            / "yichen-unified-search/scripts/route_search.py"
        ).read_text(encoding="utf-8"),
        "search_does_not_archive": "不下载媒体、不归档"
        in boundary_sources["search"],
        "archive_accepts_known_collection": "known_collection"
        in boundary_sources["archive"],
        "archive_accepts_known_x_urls": (
            "x_known_url.py" in boundary_sources["archive"]
            and "FxTwitter → Jina" in boundary_sources["archive"]
        ),
        "x_search_is_grok_first": (
            "官方 Grok CLI" in boundary_sources["search"]
            and "明确额度耗尽" in boundary_sources["search"]
            and "FxTwitter" in boundary_sources["search"]
        ),
        "firecrawl_is_explicit_and_bounded": (
            "不进入默认搜索链" in router_source
            and "同源" in router_source
            and "最多 100 条" in router_source
            and "Firecrawl" in boundary_sources["search"]
        ),
        "zhihu_is_explicit_public_only": (
            "显式 `zhihu` 平台后端" in router_source
            and "global_search" in router_source
            and "zhihu_adapter.py" in boundary_sources["search"]
        ),
        "bookmarks_requires_current_turn_authorization": "当轮授权"
        in boundary_sources["bookmarks"],
        "bookmarks_does_not_download": "不得下载媒体"
        in boundary_sources["bookmarks"],
        "asr_does_not_search_or_download": "不负责搜索、下载或归档"
        in boundary_sources["asr"],
        "asr_no_cross_provider_resubmit": "不得跨服务商重提"
        in boundary_sources["asr"],
        "single_stage_multiplatform_search_goes_direct": (
            "单阶段搜索无论涉及一个还是多个平台"
            in router_source
        ),
        "search_completion_does_not_authorize_archive": (
            "搜索完成本身绝不转移归档授权" in router_source
            and "仅在用户明确要求归档且范围已限定时" in router_source
        ),
        "public_opinion_excludes_generic_search": (
            not (SKILLS_ROOT / "public-opinion-monitor/SKILL.md").is_file()
            or "普通跨平台关键词搜索"
            in (
                SKILLS_ROOT / "public-opinion-monitor/SKILL.md"
            ).read_text(encoding="utf-8")
        ),
        "bookmark_wrapper_forbids_media": (
            "不得下载媒体、正文、字幕或附件"
            in boundary_sources["bookmarks"]
            and "导出授权不等于下载授权"
            in boundary_sources["bookmarks"]
        ),
    }
    checks["boundaries"] = boundary_checks
    if not all(boundary_checks.values()):
        failures.append("one or more routing boundaries are missing")

    if args.doctor:
        doctor_result = check_doctor()
        checks["doctor"] = doctor_result
        if not doctor_result.get("ok"):
            failures.append("doctor safety invariants failed")

    report = {
        "ok": not failures,
        "family": list(FAMILY),
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
