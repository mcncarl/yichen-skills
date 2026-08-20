#!/usr/bin/env python3
"""Build a deterministic, offline horizontal/vertical research plan.

The planner only reads one JSON brief and writes one JSON result to stdout. It
does not search the web, archive content, inspect credentials, or mutate account
state. A plan ID is the first 16 hexadecimal characters of the SHA-256 digest
of the canonical JSON plan body before the ``plan_id`` field is inserted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, NoReturn


SCHEMA_VERSION = "1.0"
PLAN_ID_LENGTH = 16
MAX_BRIEF_BYTES = 1_048_576
MAX_QUERY_GROUPS_PER_WORKSTREAM = 64
MAX_QUERY_WAVES = 2
QUERIES_PER_GROUP = 2
MAX_RESULTS_PER_QUERY = 10

REQUIRED_FIELDS = (
    "subject",
    "object_type",
    "subtype",
    "goal",
    "as_of",
    "geography",
    "languages",
    "audience",
    "start_date",
)
OPTIONAL_FIELDS = (
    "horizontal_facets",
)

ENTITY_VERTICAL_FACETS = (
    "origin",
    "launch",
    "evolution",
    "decision_logic",
)
ENTITY_HORIZONTAL_FACETS = (
    "competition",
    "differentiation",
    "users",
    "ecosystem",
    "trajectory",
)
INDUSTRY_VERTICAL_FACETS = (
    "origin",
    "stages",
    "turning_points",
    "drivers",
)
INDUSTRY_HORIZONTAL_FACETS = (
    "value_chain",
    "segments",
    "business_models",
    "players",
    "regions",
    "users",
    "regulation",
    "capital",
)
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

FACET_QUERY_VOCABULARY: dict[str, dict[str, tuple[str, str, str]]] = {
    "origin": {
        "zh": ("起源 前史", "官方档案 创始记录 最早资料", "独立报道 历史研究 起源争议 反证"),
        "en": (
            "origin and antecedents",
            "official archives founding records earliest documents",
            "independent reporting historical research disputed origins counterevidence",
        ),
    },
    "launch": {
        "zh": ("首次发布 上线", "产品公告 新闻稿 版本记录", "同期报道 首发评测 承诺兑现 失败"),
        "en": (
            "initial launch and release",
            "product announcement press release version records",
            "contemporaneous reporting launch reviews unmet promises failures",
        ),
    },
    "evolution": {
        "zh": ("发展历程 版本演进", "版本记录 公司披露 里程碑", "独立报道 变更对比 战略转向 失败"),
        "en": (
            "evolution and milestones",
            "version history company disclosures milestone records",
            "independent reporting change comparison strategic reversals failures",
        ),
    },
    "decision_logic": {
        "zh": ("关键决策 原因", "负责人访谈 官方文件 明确说明", "独立证据 替代解释 决策反证 未知"),
        "en": (
            "key decisions and rationale",
            "executive interviews official documents explicit rationale",
            "independent evidence alternative explanations counterevidence unknown motives",
        ),
    },
    "competition": {
        "zh": ("竞争格局 替代方案", "公司披露 产品定价 市场申报", "竞品对比 行业报告 用户迁移 失败案例"),
        "en": (
            "competitive landscape and substitutes",
            "company disclosures product pricing market filings",
            "independent competitor comparison industry reports switching and failure cases",
        ),
    },
    "differentiation": {
        "zh": ("差异化 核心能力", "产品文档 技术论文 官方演示", "独立评测 可复制性 用户验证 反例"),
        "en": (
            "differentiation and core capabilities",
            "product documentation technical papers official demonstrations",
            "independent evaluations replicability user validation counterexamples",
        ),
    },
    "users": {
        "zh": ("用户群体 使用场景", "采用数据 客户案例 官方统计", "用户反馈 独立调研 弃用原因 失败案例"),
        "en": (
            "users adoption and use cases",
            "usage data customer cases official adoption statistics",
            "user feedback independent surveys abandonment reasons failure cases",
        ),
    },
    "ecosystem": {
        "zh": ("生态伙伴 关键依赖", "合作公告 标准 合同 供应链披露", "依赖风险 行业报道 合作失效 反证"),
        "en": (
            "ecosystem partners and dependencies",
            "partnership announcements standards contracts supply chain disclosures",
            "dependency risks independent reporting failed partnerships counterevidence",
        ),
    },
    "trajectory": {
        "zh": ("发展趋势 未来走向", "最新指标 官方规划 监管记录", "独立预测 风险信号 停滞 反转证据"),
        "en": (
            "trajectory and future direction",
            "latest metrics official plans regulatory records",
            "independent outlook risk signals stagnation reversal evidence",
        ),
    },
    "stages": {
        "zh": ("行业阶段 发展周期", "官方统计 政策文件 历史数据", "行业研究 阶段争议 转折反证"),
        "en": (
            "industry stages and development cycle",
            "official statistics policy documents historical data",
            "industry research disputed stages turning point counterevidence",
        ),
    },
    "turning_points": {
        "zh": ("关键转折点", "事件原始记录 前后统计 政策文件", "同期报道 影响评估 短期反弹 反证"),
        "en": (
            "major turning points",
            "original event records before and after statistics policy documents",
            "contemporaneous reporting impact assessment temporary reversal counterevidence",
        ),
    },
    "drivers": {
        "zh": ("行业驱动力", "供需数据 技术成本 政策记录", "实证研究 混杂因素 驱动力衰减 反证"),
        "en": (
            "industry drivers",
            "supply demand data technology costs policy records",
            "empirical research confounders weakening drivers counterevidence",
        ),
    },
    "value_chain": {
        "zh": ("产业链 价值分配", "监管数据 公司披露 成本结构", "行业报告 瓶颈 议价权 风险"),
        "en": (
            "value chain and value capture",
            "regulatory data company disclosures cost structure",
            "industry reports bottlenecks bargaining power risks",
        ),
    },
    "segments": {
        "zh": ("市场细分 赛道边界", "官方分类 统计数据 公司披露", "市场报告 口径差异 重复计算 反证"),
        "en": (
            "market segments and category boundaries",
            "official classifications statistics company disclosures",
            "market reports definition differences double counting counterevidence",
        ),
    },
    "business_models": {
        "zh": ("商业模式 盈利逻辑", "审计披露 定价 收入 成本", "单位经济分析 补贴依赖 失败模式"),
        "en": (
            "business models and profit logic",
            "audited disclosures pricing revenue costs",
            "unit economics analysis subsidy dependence failure modes",
        ),
    },
    "players": {
        "zh": ("主要玩家 竞争格局", "企业登记 公司披露 市场份额", "行业报告 挑战者 替代者 排名口径"),
        "en": (
            "major players and market structure",
            "company registries disclosures market share records",
            "industry reports challengers substitutes ranking methodology",
        ),
    },
    "regions": {
        "zh": ("区域差异", "地区统计 当地监管 基础设施数据", "区域研究 本地化约束 不可泛化证据"),
        "en": (
            "regional differences",
            "regional statistics local regulation infrastructure data",
            "regional research localization constraints limits to generalization",
        ),
    },
    "regulation": {
        "zh": ("监管政策 合规", "法律法规 监管文件 执法记录", "法律分析 行业回应 政策冲突 执行差异"),
        "en": (
            "regulation policy and compliance",
            "laws regulations official guidance enforcement records",
            "independent legal analysis industry response policy conflicts enforcement differences",
        ),
    },
    "capital": {
        "zh": ("融资 资本周期", "交易公告 证券申报 审计披露", "财务报道 估值口径 融资失败 退出案例"),
        "en": (
            "funding and capital cycle",
            "transaction announcements securities filings audited disclosures",
            "independent financial reporting valuation methods failed funding exit cases",
        ),
    },
}


class PlannerError(Exception):
    """A user-correctable, JSON-safe planner failure."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def as_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.field is not None:
            payload["field"] = self.field
        return payload


class JsonArgumentParser(argparse.ArgumentParser):
    """Convert CLI usage errors into the planner's JSON error contract."""

    def error(self, message: str) -> NoReturn:
        raise PlannerError("invalid_arguments", message, "arguments")


def canonical_json(value: object) -> str:
    """Return canonical JSON used by the stable plan identifier."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlannerError(
                "duplicate_json_key",
                f"duplicate JSON key: {key}",
                key,
            )
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> NoReturn:
    raise PlannerError(
        "invalid_json_number",
        f"non-finite JSON number is not allowed: {value}",
    )


def parse_brief_json(source: str) -> dict[str, Any]:
    """Parse a brief while rejecting ambiguous duplicate keys and NaN values."""
    if not source.strip():
        raise PlannerError("empty_brief", "brief input is empty", "brief")
    try:
        payload = json.loads(
            source,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
    except PlannerError:
        raise
    except json.JSONDecodeError as exc:
        raise PlannerError(
            "invalid_json",
            f"brief is not valid JSON at line {exc.lineno}, column {exc.colno}",
            "brief",
        ) from exc
    if not isinstance(payload, dict):
        raise PlannerError(
            "invalid_brief_type",
            "brief must be a JSON object",
            "brief",
        )
    return payload


def _clean_required_string(brief: dict[str, Any], field: str) -> str:
    value = brief.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PlannerError(
            "invalid_field",
            f"{field} must be a non-empty string",
            field,
        )
    return value.strip()


def _clean_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlannerError(
            "invalid_date",
            f"{field} must use YYYY-MM-DD",
            field,
        )
    cleaned = value.strip()
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise PlannerError(
            "invalid_date",
            f"{field} must be a valid calendar date in YYYY-MM-DD format",
            field,
        ) from exc
    if parsed.isoformat() != cleaned:
        raise PlannerError(
            "invalid_date",
            f"{field} must use canonical YYYY-MM-DD format",
            field,
        )
    return cleaned


def _clean_scope(value: Any, field: str) -> str | list[str]:
    """Normalize an explicitly supplied scope, including a known-unknown."""
    if value is None:
        return "unknown"
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.casefold() == "unknown":
            return "unknown"
        if cleaned:
            return cleaned
    elif isinstance(value, list):
        if not value:
            return "unknown"
        cleaned_items: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise PlannerError(
                    "invalid_field",
                    f"{field}[{index}] must be a non-empty string",
                    field,
                )
            cleaned = item.strip()
            if cleaned in seen:
                raise PlannerError(
                    "duplicate_value",
                    f"{field} contains duplicate value: {cleaned}",
                    field,
                )
            seen.add(cleaned)
            cleaned_items.append(cleaned)
        unknown_items = [
            item for item in cleaned_items if item.casefold() == "unknown"
        ]
        if unknown_items:
            if len(cleaned_items) == 1:
                return "unknown"
            raise PlannerError(
                "ambiguous_scope",
                f"{field} cannot mix unknown with concrete values",
                field,
            )
        return cleaned_items
    raise PlannerError(
        "invalid_field",
        f"{field} must be a string, string array, null, or explicit unknown",
        field,
    )


def _clean_start_date(value: Any) -> str:
    """Normalize a known start date or an explicitly unknown lower bound."""
    if value is None:
        return "unknown"
    if isinstance(value, str) and (
        not value.strip() or value.strip().casefold() == "unknown"
    ):
        return "unknown"
    return _clean_date(value, "start_date")


def known_scope_values(value: str | list[str]) -> list[str]:
    """Return concrete scope values without inventing a value for unknown."""
    if value == "unknown":
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _clean_facets(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise PlannerError(
            "invalid_horizontal_facets",
            "horizontal_facets must be a JSON array",
            "horizontal_facets",
        )
    facets: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise PlannerError(
                "invalid_horizontal_facets",
                f"horizontal_facets[{index}] must be a non-empty string",
                "horizontal_facets",
            )
        facet = item.strip().lower()
        if facet in seen:
            raise PlannerError(
                "duplicate_horizontal_facet",
                f"horizontal_facets contains duplicate value: {facet}",
                "horizontal_facets",
            )
        seen.add(facet)
        facets.append(facet)
    return facets


def normalize_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize all planner inputs without external lookups."""
    missing = [field for field in REQUIRED_FIELDS if field not in brief]
    if missing:
        raise PlannerError(
            "missing_required_fields",
            "missing required field(s): " + ", ".join(missing),
            missing[0],
        )

    normalized: dict[str, Any] = {
        "subject": _clean_required_string(brief, "subject"),
        "object_type": _clean_required_string(brief, "object_type").lower(),
        "subtype": _clean_required_string(brief, "subtype"),
        "goal": _clean_required_string(brief, "goal"),
        "as_of": _clean_date(brief["as_of"], "as_of"),
    }
    if normalized["object_type"] not in {"entity", "industry"}:
        raise PlannerError(
            "invalid_object_type",
            "object_type must be entity or industry",
            "object_type",
        )

    for field in ("geography", "languages", "audience"):
        normalized[field] = _clean_scope(brief[field], field)

    geography_count = len(known_scope_values(normalized["geography"]))
    language_count = len(known_scope_values(normalized["languages"]))
    if geography_count * language_count > MAX_QUERY_GROUPS_PER_WORKSTREAM:
        raise PlannerError(
            "scope_too_broad",
            "geography x languages exceeds the bounded limit of "
            f"{MAX_QUERY_GROUPS_PER_WORKSTREAM} query groups per workstream",
            "geography",
        )

    normalized["start_date"] = _clean_start_date(brief["start_date"])
    if (
        normalized["start_date"] != "unknown"
        and normalized["start_date"] > normalized["as_of"]
    ):
        raise PlannerError(
            "invalid_date_range",
            "start_date must not be later than as_of",
            "start_date",
        )

    if "horizontal_facets" in brief:
        facets = _clean_facets(brief["horizontal_facets"])
        if normalized["object_type"] == "entity":
            if set(facets) != set(ENTITY_HORIZONTAL_FACETS) or len(facets) != len(
                ENTITY_HORIZONTAL_FACETS
            ):
                raise PlannerError(
                    "entity_facets_are_fixed",
                    "entity horizontal_facets must contain the complete fixed set: "
                    + ", ".join(ENTITY_HORIZONTAL_FACETS),
                    "horizontal_facets",
                )
            normalized["horizontal_facets"] = list(ENTITY_HORIZONTAL_FACETS)
        else:
            if not 3 <= len(facets) <= 5:
                raise PlannerError(
                    "invalid_facet_count",
                    "industry horizontal_facets must contain 3 to 5 unique facets",
                    "horizontal_facets",
                )
            invalid = [
                facet for facet in facets if facet not in INDUSTRY_HORIZONTAL_FACETS
            ]
            if invalid:
                raise PlannerError(
                    "unsupported_horizontal_facet",
                    "unsupported industry horizontal facet(s): "
                    + ", ".join(invalid),
                    "horizontal_facets",
                )
            normalized["horizontal_facets"] = facets

    return normalized


GOAL_DEFAULT_RULES: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...], str], ...
] = (
    (
        "regulation_policy",
        (
            "监管",
            "政策",
            "合规",
            "法律",
            "regulat",
            "policy",
            "compliance",
            "legal",
        ),
        ("regulation", "players", "value_chain", "regions", "users"),
        "The goal emphasizes regulation, policy, compliance, or legal exposure.",
    ),
    (
        "capital_investment",
        (
            "投资",
            "融资",
            "资本",
            "估值",
            "并购",
            "investment",
            "funding",
            "capital",
            "valuation",
            "m&a",
        ),
        ("capital", "players", "business_models", "segments", "regions"),
        "The goal emphasizes investment, financing, valuation, or transactions.",
    ),
    (
        "regional_expansion",
        (
            "区域",
            "地域",
            "出海",
            "全球",
            "国际",
            "国家",
            "region",
            "geograph",
            "global",
            "international",
            "country",
        ),
        ("regions", "regulation", "players", "segments", "users"),
        "The goal emphasizes geographic comparison or cross-border expansion.",
    ),
    (
        "user_demand",
        (
            "用户",
            "客户",
            "需求",
            "产品",
            "采用",
            "user",
            "customer",
            "demand",
            "product",
            "adoption",
        ),
        ("users", "segments", "business_models", "players", "regions"),
        "The goal emphasizes users, demand, products, or adoption.",
    ),
    (
        "technology_innovation",
        (
            "技术",
            "创新",
            "研发",
            "technology",
            "technical",
            "innovation",
            "research and development",
        ),
        ("value_chain", "players", "business_models", "regulation", "capital"),
        "The goal emphasizes technology, innovation, or research and development.",
    ),
    (
        "competition_strategy",
        (
            "竞争",
            "战略",
            "商业",
            "市场",
            "格局",
            "competition",
            "competitive",
            "strategy",
            "business",
            "market",
        ),
        ("players", "business_models", "segments", "value_chain", "users"),
        "The goal emphasizes competitive structure, strategy, or market position.",
    ),
)

GENERAL_INDUSTRY_FACETS = (
    "value_chain",
    "segments",
    "business_models",
    "players",
    "users",
)


def select_industry_facets(goal: str) -> tuple[list[str], dict[str, Any]]:
    """Choose a deterministic goal-sensitive default for industry research."""
    normalized_goal = goal.casefold()
    for rule_id, keywords, facets, explanation in GOAL_DEFAULT_RULES:
        matched = [keyword for keyword in keywords if keyword in normalized_goal]
        if matched:
            return list(facets), {
                "mode": "goal_default",
                "selection_rule": rule_id,
                "matched_goal_terms": matched,
                "selection_reason": explanation,
            }
    return list(GENERAL_INDUSTRY_FACETS), {
        "mode": "goal_default",
        "selection_rule": "general_industry",
        "matched_goal_terms": [],
        "selection_reason": (
            "No specialized goal rule matched; use the fixed general-industry "
            "set covering structure, segmentation, monetization, actors, and demand."
        ),
    }


ENTITY_QUESTIONS: dict[str, tuple[str, ...]] = {
    "origin": (
        "What verifiable need, context, or predecessor led to the subject?",
        "Who initiated it, when, and under what organizational or market conditions?",
        "Which origin claims are primary evidence, later recollection, or still unknown?",
    ),
    "launch": (
        "What event counts as the formal launch, and what contemporaneous evidence dates it?",
        "What initial audience, promise, scope, pricing, or distribution was announced?",
        "How did independent contemporary observers describe the launch?",
    ),
    "evolution": (
        "Which dated milestones materially changed the product, organization, strategy, or reach?",
        "Which metrics and claims are comparable across time, and which changed definition?",
        "What remained continuous and what was discontinued, reversed, or reframed?",
    ),
    "decision_logic": (
        "Which decisions have an explicit, attributable rationale from a primary source?",
        "Which rationales are supported_inference from at least two independent evidence lines?",
        "Which motives remain unknown and must not be narrated as fact?",
    ),
    "competition": (
        "What direct, indirect, and substitute alternatives existed at the as-of date?",
        "On which comparable dimensions do competitors differ in evidence-backed ways?",
        "Which competitor claims rely on mismatched periods, geographies, or definitions?",
    ),
    "differentiation": (
        "What differentiation is claimed, and which parts are independently demonstrated?",
        "Which capabilities, assets, distribution advantages, or constraints are difficult to copy?",
        "Where is the claimed differentiation weak, temporary, or unverified?",
    ),
    "users": (
        "Who actually uses the subject, for which jobs, and in which contexts?",
        "What evidence distinguishes stated target users from observed adoption?",
        "What recurring outcomes, objections, failures, and switching reasons appear?",
    ),
    "ecosystem": (
        "Which suppliers, partners, platforms, channels, standards, and regulators shape outcomes?",
        "Where are the critical dependencies, bargaining asymmetries, or single points of failure?",
        "Which ecosystem relationships are formal, inferred, inactive, or unknown?",
    ),
    "trajectory": (
        "What current signals indicate momentum, stagnation, reversal, or strategic transition?",
        "Which leading indicators would distinguish plausible next scenarios?",
        "What could falsify each trajectory inference after the as-of date?",
    ),
}

INDUSTRY_QUESTIONS: dict[str, tuple[str, ...]] = {
    "origin": (
        "Which needs, technologies, institutions, or policies created the industry?",
        "What is the earliest defensible boundary for the industry and its terminology?",
        "Which origin narratives conflict or impose present-day categories on the past?",
    ),
    "stages": (
        "Which evidence-backed stages describe the industry's development over time?",
        "What entry, adoption, supply, or standardization signals separate one stage from another?",
        "How do stage boundaries vary by region or segment?",
    ),
    "turning_points": (
        "Which dated events changed industry structure, economics, adoption, or regulation?",
        "What before-and-after evidence supports each claimed turning point?",
        "Which apparent turning points were temporary or later reversed?",
    ),
    "drivers": (
        "Which demand, supply, technology, policy, and capital forces drove each period?",
        "Which drivers are directly documented and which are supported inference?",
        "What counterevidence or confounders weaken the causal account?",
    ),
    "value_chain": (
        "What are the value-chain stages, inputs, outputs, margins, and bottlenecks?",
        "Where is value captured, and how has bargaining power shifted?",
        "Which dependencies or missing data prevent a complete chain view?",
    ),
    "segments": (
        "Which segmentation scheme best serves the stated goal without double counting?",
        "How large, mature, and fast-changing is each segment under comparable definitions?",
        "Which segment boundaries or labels remain contested?",
    ),
    "business_models": (
        "Which revenue, pricing, cost, distribution, and retention models are in use?",
        "What evidence distinguishes a durable model from a subsidized or experimental one?",
        "Which economics cannot be compared because definitions or disclosures differ?",
    ),
    "players": (
        "Who are the major incumbents, challengers, enablers, and substitutes?",
        "How do their roles, scale, positioning, and strategic constraints compare?",
        "Which market-share or ranking claims use incompatible scopes?",
    ),
    "regions": (
        "How do demand, supply, maturity, infrastructure, and policy differ by region?",
        "Which regional comparisons use equivalent periods and definitions?",
        "Where would geographic evidence be unsafe to generalize?",
    ),
    "users": (
        "Which user groups, buyers, and beneficiaries participate in the industry?",
        "What jobs, adoption barriers, switching costs, and unmet needs recur?",
        "How do stated demand and observed behavior differ?",
    ),
    "regulation": (
        "Which laws, regulations, standards, and enforcement practices shape the industry?",
        "What is currently effective, proposed, jurisdiction-specific, or historically superseded?",
        "Which regulatory changes create material opportunities, costs, or uncertainty?",
    ),
    "capital": (
        "How have funding, investment, valuation, credit, and exit conditions changed?",
        "Which capital claims are based on disclosed transactions rather than estimates?",
        "How does capital availability affect entry, consolidation, and business-model durability?",
    ),
}


L1_FIRST_FACETS = {
    "origin",
    "launch",
    "evolution",
    "decision_logic",
    "differentiation",
    "ecosystem",
}
L0_FIRST_FACETS = {
    "competition",
    "trajectory",
    "stages",
    "turning_points",
    "drivers",
    "value_chain",
    "segments",
    "business_models",
    "players",
    "regions",
    "regulation",
    "capital",
}


def minimum_evidence_for(facet: str) -> dict[str, Any]:
    """Return an auditable minimum evidence threshold for one workstream."""
    minimum = {
        "verified_sources": 2,
        "primary_sources": 1,
        "independent_sources": 1,
    }
    if facet in {"trajectory", "drivers", "capital", "users"}:
        minimum["verified_sources"] = 3
    return minimum


def source_priorities_for(facet: str) -> list[str]:
    """Order the evidence tiers without implying that a lower tier proves facts."""
    if facet == "users":
        return ["L1", "L2", "L3", "L0"]
    if facet in L1_FIRST_FACETS:
        return ["L1", "L0", "L2", "L3"]
    if facet in L0_FIRST_FACETS:
        return ["L0", "L1", "L2", "L3"]
    return ["L0", "L1", "L2", "L3"]


def stop_conditions_for(facet: str) -> list[str]:
    conditions = [
        "The workstream's minimum evidence threshold is met or every deficit is logged as a gap.",
        "Every material contradiction is resolved with stronger evidence or disclosed without forced reconciliation.",
        "Two consecutive bounded query waves add no new high-quality evidence relevant to this facet.",
    ]
    if facet in {"decision_logic", "drivers", "trajectory"}:
        conditions.append(
            "All interpretive claims are labeled explicit, supported_inference, or unknown as applicable."
        )
    return conditions


def language_family(language: str) -> str:
    """Map declared language labels to the query vocabularies we actually own."""
    normalized = language.strip().casefold().replace("_", "-")
    if normalized.startswith(("zh", "chinese", "中文", "汉语")):
        return "zh"
    if normalized.startswith(("en", "english", "英文", "英语")):
        return "en"
    return "neutral"


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _has_latin(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value))


def bilingual_subject_segments(subject: str) -> dict[str, str] | None:
    """Split only explicit Chinese/English subject forms, never infer a translation."""
    candidates: list[tuple[str, str]] = []
    slash = re.fullmatch(r"\s*(.+?)\s*[/／]\s*(.+?)\s*", subject)
    if slash:
        candidates.append((slash.group(1).strip(), slash.group(2).strip()))
    parenthetical = re.fullmatch(
        r"\s*(.+?)\s*[（(]\s*([^（）()]+?)\s*[）)]\s*",
        subject,
    )
    if parenthetical:
        candidates.append(
            (parenthetical.group(1).strip(), parenthetical.group(2).strip())
        )

    for first, second in candidates:
        if _has_cjk(first) and _has_latin(second) and not _has_cjk(second):
            return {"zh": first, "en": second}
        if _has_cjk(second) and _has_latin(first) and not _has_cjk(first):
            return {"zh": second, "en": first}
    return None


def localized_subject(subject: str, family: str, language: str) -> dict[str, str]:
    """Select a proven subject segment or disclose that the source was preserved."""
    segments = bilingual_subject_segments(subject)
    if family in {"zh", "en"} and segments is not None:
        return {
            "subject": segments[family],
            "localization_status": "native_bilingual_subject_segment",
        }

    has_cjk = _has_cjk(subject)
    has_latin = _has_latin(subject)
    if family == "zh" and has_cjk and not has_latin:
        return {
            "subject": subject,
            "localization_status": "native_source_subject",
        }
    if family == "en" and has_latin and not has_cjk:
        return {
            "subject": subject,
            "localization_status": "native_source_subject",
        }

    if family == "neutral":
        reason = (
            f"No native query vocabulary is defined for {language}; a neutral "
            "fallback preserves the source subject without claiming translation."
        )
    else:
        reason = (
            f"Could not reliably isolate a {family} subject segment; the original "
            "subject is preserved without claiming translation."
        )
    return {
        "subject": subject,
        "localization_status": "source_subject_untranslated",
        "localization_gap": reason,
    }


def localized_geography(
    geography: str,
    family: str,
    language: str,
) -> dict[str, str]:
    """Localize only known geography names and disclose every uncertain case."""
    key = geography.strip().casefold()
    zh_known = {
        "global": "全球",
        "全球": "全球",
        "china": "中国",
        "mainland china": "中国大陆",
        "people's republic of china": "中国",
        "prc": "中国",
        "中国": "中国",
        "中國": "中国",
        "中国大陆": "中国大陆",
        "中國大陸": "中国大陆",
        "中华人民共和国": "中国",
        "中華人民共和國": "中国",
        "united states": "美国",
        "united states of america": "美国",
        "us": "美国",
        "u.s.": "美国",
        "usa": "美国",
        "u.s.a.": "美国",
        "america": "美国",
        "美国": "美国",
        "美國": "美国",
        "美利坚合众国": "美国",
        "美利堅合眾國": "美国",
        "hong kong": "香港",
        "香港": "香港",
        "europe": "欧洲",
        "欧洲": "欧洲",
        "歐洲": "欧洲",
    }
    en_known = {
        "global": "globally",
        "全球": "globally",
        "china": "in China",
        "mainland china": "in Mainland China",
        "people's republic of china": "in China",
        "prc": "in China",
        "中国": "in China",
        "中國": "in China",
        "中国大陆": "in Mainland China",
        "中國大陸": "in Mainland China",
        "中华人民共和国": "in China",
        "中華人民共和國": "in China",
        "united states": "in United States",
        "united states of america": "in United States",
        "us": "in United States",
        "u.s.": "in United States",
        "usa": "in United States",
        "u.s.a.": "in United States",
        "america": "in United States",
        "美国": "in United States",
        "美國": "in United States",
        "美利坚合众国": "in United States",
        "美利堅合眾國": "in United States",
        "hong kong": "in Hong Kong",
        "香港": "in Hong Kong",
        "europe": "in Europe",
        "欧洲": "in Europe",
        "歐洲": "in Europe",
    }
    known = zh_known if family == "zh" else en_known if family == "en" else {}
    if key in known:
        return {
            "geography": known[key],
            "localization_status": "native_mapped_geography",
        }
    if family == "zh" and _has_cjk(geography) and not _has_latin(geography):
        return {
            "geography": geography,
            "localization_status": "native_source_geography",
        }
    if family == "en" and _has_latin(geography) and not _has_cjk(geography):
        return {
            "geography": f"in {geography}",
            "localization_status": "native_source_geography",
        }

    return {
        "geography": geography,
        "localization_status": "source_geography_untranslated",
        "geography_localization_gap": (
            f"Could not reliably localize geography {geography!r} for {language}; "
            "the original geography is preserved without claiming translation."
        ),
    }


def query_year_hints(brief: dict[str, Any], axis: str, family: str) -> tuple[str, str]:
    as_of_year = brief["as_of"][:4]
    start_year = (
        brief["start_date"][:4]
        if brief["start_date"] != "unknown"
        else None
    )
    if family == "zh":
        if axis == "longitudinal":
            early = (
                f"{start_year}年起的早期记录"
                if start_year
                else f"{as_of_year}年以前的早期记录"
            )
            return early, f"截至{as_of_year}年的变化"
        return f"{as_of_year}年官方现状", f"{as_of_year}年独立观察"
    if axis == "longitudinal":
        early = f"early records from {start_year}" if start_year else f"early records before {as_of_year}"
        return early, f"changes through {as_of_year}"
    return f"official status in {as_of_year}", f"independent evidence in {as_of_year}"


def facet_query_vocabulary(facet: str, family: str) -> tuple[str, str, str]:
    if family in {"zh", "en"}:
        return FACET_QUERY_VOCABULARY[facet][family]
    readable_facet = facet.replace("_", " ")
    return (
        readable_facet,
        "official records original documents statistics disclosures",
        "independent reporting industry research counterevidence adoption failures",
    )


def make_query_groups(
    workstream_id: str,
    axis: str,
    facet: str,
    brief: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build bounded geography-by-language query groups without executing them."""
    geographies = known_scope_values(brief["geography"])
    languages = known_scope_values(brief["languages"])
    if not geographies or not languages:
        return []

    groups: list[dict[str, Any]] = []
    for geography_index, geography in enumerate(geographies, start=1):
        for language_index, language in enumerate(languages, start=1):
            group_id = (
                f"{workstream_id}_g{geography_index:02d}_l{language_index:02d}"
            )
            family = language_family(language)
            subject = localized_subject(brief["subject"], family, language)
            facet_terms, primary_terms, independent_terms = facet_query_vocabulary(
                facet, family
            )
            early_years, current_years = query_year_hints(brief, axis, family)
            localized_geo = localized_geography(geography, family, language)
            subject_is_native = subject["localization_status"].startswith("native_")
            geography_is_native = localized_geo["localization_status"].startswith(
                "native_"
            )
            if subject_is_native and geography_is_native:
                group_localization_status = "native"
            elif not subject_is_native:
                group_localization_status = "source_subject_untranslated"
            else:
                group_localization_status = "source_geography_untranslated"
            queries = [
                {
                    "id": f"{group_id}_q01",
                    "intent": "primary_official_evidence",
                    "wave_hint": "wave_1_primary_source_path",
                    "query_text": " ".join(
                        (
                            subject["subject"],
                            localized_geo["geography"],
                            facet_terms,
                            primary_terms,
                            early_years,
                        )
                    ),
                },
                {
                    "id": f"{group_id}_q02",
                    "intent": "independent_contradiction_gap_check",
                    "wave_hint": "wave_2_independent_challenge_path",
                    "query_text": " ".join(
                        (
                            subject["subject"],
                            localized_geo["geography"],
                            facet_terms,
                            independent_terms,
                            current_years,
                        )
                    ),
                },
            ]
            group = {
                "id": group_id,
                "geography": geography,
                "language": language,
                "language_family": family,
                "subject_for_query": subject["subject"],
                "geography_for_query": localized_geo["geography"],
                "subject_localization_status": subject["localization_status"],
                "geography_localization_status": localized_geo[
                    "localization_status"
                ],
                "localization_status": group_localization_status,
                "queries": queries,
                "bounds": {
                    "max_query_waves": MAX_QUERY_WAVES,
                    "max_queries_per_group": QUERIES_PER_GROUP,
                    "max_results_per_query": MAX_RESULTS_PER_QUERY,
                    "max_total_candidates": (
                        MAX_QUERY_WAVES
                        * QUERIES_PER_GROUP
                        * MAX_RESULTS_PER_QUERY
                    ),
                    "allow_unbounded_pagination": False,
                    "start_date": brief["start_date"],
                    "as_of": brief["as_of"],
                },
            }
            if "localization_gap" in subject:
                group["localization_gap"] = subject["localization_gap"]
            if "geography_localization_gap" in localized_geo:
                group["geography_localization_gap"] = localized_geo[
                    "geography_localization_gap"
                ]
            groups.append(group)
    return groups


def make_workstream(
    object_type: str,
    axis: str,
    index: int,
    facet: str,
    brief: dict[str, Any],
) -> dict[str, Any]:
    questions_by_type = (
        ENTITY_QUESTIONS if object_type == "entity" else INDUSTRY_QUESTIONS
    )
    prefix = "v" if axis == "longitudinal" else "h"
    workstream_id = f"{prefix}{index:02d}_{facet}"
    return {
        "id": workstream_id,
        "axis": axis,
        "facet": facet,
        "questions": list(questions_by_type[facet]),
        "query_groups": make_query_groups(
            workstream_id,
            axis,
            facet,
            brief,
        ),
        "source_priorities": source_priorities_for(facet),
        "minimum_evidence": minimum_evidence_for(facet),
        "stop_conditions": stop_conditions_for(facet),
    }


def make_evidence_policy() -> dict[str, Any]:
    return {
        "source_tiers": [
            {
                "tier": "L0",
                "use": "Anchor legal status, audited facts, official statistics, and original records.",
                "examples": [
                    "official_records",
                    "laws_and_regulations",
                    "audited_disclosures",
                    "original_datasets",
                ],
            },
            {
                "tier": "L1",
                "use": "Establish what the subject did or explicitly said in dated first-party material.",
                "examples": [
                    "first_party_dated_materials",
                    "product_documentation",
                    "technical_papers",
                    "direct_interviews_or_statements",
                ],
            },
            {
                "tier": "L2",
                "use": "Corroborate, compare, contextualize, and challenge primary claims.",
                "examples": [
                    "reputable_reporting",
                    "peer_reviewed_or_method_disclosed_research",
                    "qualified_industry_analysis",
                ],
            },
            {
                "tier": "L3",
                "use": "Discover leads and experience themes without treating anecdotes or snippets as prevalence or proven fact.",
                "examples": [
                    "user_reports",
                    "practitioner_observations",
                    "community_discussion",
                    "search_snippets",
                    "unsourced_aggregators",
                    "reposts",
                ],
            },
        ],
        "claim_requirements": {
            "material_fact": (
                "Cite a scope-matched source; prefer primary evidence and add independent "
                "corroboration when the claim is contested or consequential."
            ),
            "material_number": (
                "Record value, unit, period, geography, definition, source date, and any "
                "methodology caveat."
            ),
            "causal_claim": (
                "State the mechanism, counterevidence, and plausible confounders; otherwise "
                "downgrade to association."
            ),
            "decision_logic": {
                "allowed_labels": [
                    "explicit",
                    "supported_inference",
                    "unknown",
                ],
                "explicit": (
                    "Use only for an attributable rationale stated in a primary source."
                ),
                "supported_inference": (
                    "Use only when at least two independent evidence lines support a stated "
                    "reasoning chain; never present it as the actor's own words."
                ),
                "unknown": (
                    "Use when evidence is missing, single-source, contradictory, or cannot "
                    "distinguish plausible motives."
                ),
            },
        },
        "independence_rule": (
            "Syndicated copies, shared press releases, and sources repeating one underlying "
            "dataset count as one evidence line."
        ),
        "time_rule": (
            "Separate event date, publication date, and access date; do not use evidence "
            "after as_of to describe knowledge available at as_of unless labeled retrospective."
        ),
        "conflict_rule": (
            "Preserve material conflicts in the ledger and prefer scope-matched primary or "
            "methodologically stronger evidence; never average incompatible claims."
        ),
    }


def make_coverage_dimensions(brief: dict[str, Any]) -> dict[str, Any]:
    """Turn known scope values into explicit execution and delivery obligations."""
    geographies = known_scope_values(brief["geography"])
    languages = known_scope_values(brief["languages"])
    gaps: list[dict[str, str]] = []
    if brief["start_date"] == "unknown":
        gaps.append(
            {
                "dimension": "start_date",
                "status": "gap",
                "reason": (
                    "brief.start_date is unknown; no historical lower bound was "
                    "invented"
                ),
            }
        )
    if not geographies:
        gaps.append(
            {
                "dimension": "geography",
                "status": "gap",
                "reason": "brief.geography is unknown; no geography was invented",
            }
        )
    if not languages:
        gaps.append(
            {
                "dimension": "languages",
                "status": "gap",
                "reason": "brief.languages is unknown; no search or delivery language was invented",
            }
        )
    if brief["audience"] == "unknown":
        gaps.append(
            {
                "dimension": "audience",
                "status": "gap",
                "reason": (
                    "brief.audience is unknown; no delivery audience or decision "
                    "context was invented"
                ),
            }
        )

    groups_per_workstream = len(geographies) * len(languages)
    blocking_dimensions = [gap["dimension"] for gap in gaps]
    return {
        "geographies": geographies,
        "languages": languages,
        "geography_requirements": [
            {
                "geography": geography,
                "coverage_required": True,
                "cross_geography_comparison_required": len(geographies) > 1,
            }
            for geography in geographies
        ],
        "language_requirements": [
            {
                "language": language,
                "search_required": True,
                "delivery_required": True,
                "scope_matched_citations_required": True,
            }
            for language in languages
        ],
        "query_group_matrix": {
            "status": (
                "ready"
                if groups_per_workstream and not blocking_dimensions
                else "blocked_by_scope_gap"
            ),
            "blocking_dimensions": blocking_dimensions,
            "groups_per_workstream": groups_per_workstream,
            "maximum_groups_per_workstream": MAX_QUERY_GROUPS_PER_WORKSTREAM,
            "queries_per_group": QUERIES_PER_GROUP,
            "max_query_waves": MAX_QUERY_WAVES,
            "max_results_per_query": MAX_RESULTS_PER_QUERY,
        },
        "gaps": gaps,
    }


def future_opportunity_contract(
    object_type: str,
    goal: str,
) -> dict[str, Any]:
    """Detect explicit future/opportunity intent without adding a facet."""
    normalized_goal = goal.casefold()
    matched_terms = [
        term for term in FUTURE_OPPORTUNITY_TERMS if term in normalized_goal
    ]
    required = object_type == "industry" and bool(matched_terms)
    return {
        "required": required,
        "section": "opportunity_map" if required else None,
        "trigger_terms": matched_terms if object_type == "industry" else [],
        "not_a_horizontal_facet": True,
        "required_fields": [
            "opportunity_id",
            "opportunity",
            "historical_driver",
            "current_condition",
            "evidence_basis",
            "beneficiaries",
            "constraints",
            "leading_indicators",
            "invalidators",
        ],
        "evidence_rule": (
            "Every opportunity must connect verified longitudinal evidence to a "
            "current cross-sectional condition and state constraints and invalidators."
        ),
    }


def make_gates(
    workstream_ids: list[str],
    coverage_dimensions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "completion_basis": [
            "coverage",
            "contradiction",
            "gap",
        ],
        "word_count_is_completion_gate": False,
        "coverage": {
            "metric": "workstreams_with_threshold_or_disclosed_gap / total_workstreams",
            "required_ratio": 1.0,
            "required_workstreams": workstream_ids,
            "required_geographies": coverage_dimensions["geographies"],
            "required_languages": coverage_dimensions["languages"],
            "scope_gaps": [
                gap["dimension"] for gap in coverage_dimensions["gaps"]
            ],
            "pass_condition": (
                "Every planned workstream either meets its minimum evidence threshold or "
                "has a precise, report-visible coverage gap."
            ),
        },
        "contradiction": {
            "metric": "material_contradictions_resolved_or_disclosed / material_contradictions",
            "required_ratio": 1.0,
            "pass_condition": (
                "Every material contradiction is resolved by stronger scope-matched evidence "
                "or shown in the report with the competing claims and consequences."
            ),
        },
        "gap": {
            "metric": "material_gaps_disclosed_and_claims_constrained / material_gaps",
            "required_ratio": 1.0,
            "pass_condition": (
                "Every material evidence gap is named, its impact is stated, and unsupported "
                "claims are removed or labeled unknown."
            ),
        },
    }


def make_report_contract(
    brief: dict[str, Any],
    coverage_dimensions: dict[str, Any],
    opportunity_map: dict[str, Any],
) -> dict[str, Any]:
    delivery_languages = known_scope_values(brief["languages"])
    required_sections = [
            "scope_and_classification",
            "executive_findings",
            "vertical_timeline",
            "horizontal_comparison_matrix",
            "cross_axis_synthesis",
    ]
    if opportunity_map["required"]:
        required_sections.append("opportunity_map")
    required_sections.extend(
        [
            "scenarios_and_falsifiers",
            "contradictions_and_gaps",
            "evidence_ledger",
            "limitations",
        ]
    )
    return {
        "required_sections": required_sections,
        "geography_requirements": {
            "status": (
                "required"
                if coverage_dimensions["geographies"]
                else "gap_unknown"
            ),
            "required_geographies": coverage_dimensions["geographies"],
            "cross_geography_comparison_required": (
                len(coverage_dimensions["geographies"]) > 1
            ),
            "rule": (
                "Report coverage and limitations separately for every known geography; "
                "do not generalize an uncovered geography."
            ),
        },
        "language_requirements": {
            "status": "required" if delivery_languages else "gap_unknown",
            "derived_from": "brief.languages",
            "search_languages": delivery_languages,
            "delivery_languages": delivery_languages,
            "all_delivery_languages_required": bool(delivery_languages),
            "per_language_requirements": coverage_dimensions[
                "language_requirements"
            ],
            "rule": (
                "Use each known brief language for scoped retrieval and delivery, "
                "and disclose evidence unavailable in any required language."
            ),
        },
        "opportunity_map": opportunity_map,
        "claim_record_fields": [
            "claim_id",
            "statement",
            "claim_type",
            "basis",
            "workstream_ids",
            "event_date",
            "as_of",
            "evidence",
            "cross_link",
            "scenario",
            "contradiction_resolution",
        ],
        "source_annotation_fields": [
            "source_id",
            "source_tier",
            "source_role",
            "publisher_kind",
            "published_at",
            "event_dates",
            "geographies",
            "languages",
            "retrospective",
            "pre_scope_context",
            "independence_group",
            "selection_reason",
        ],
        "evidence_link_fields": [
            "source_id",
            "relation",
            "locator",
            "event_date",
            "scope",
            "notes",
        ],
        "evidence_link_requirements": {
            "allowed_relations": [
                "supports",
                "contradicts",
                "context_only",
            ],
            "supports_or_contradicts": {
                "required_fields": [
                    "source_id",
                    "relation",
                    "locator",
                    "event_date",
                    "scope",
                ],
                "optional_fields": ["notes"],
                "rule": (
                    "Material supports and contradicts links require non-empty locator, "
                    "event_date, and scope; notes are optional."
                ),
            },
            "context_only": {
                "required_fields": ["source_id", "relation"],
                "optional_fields": [
                    "locator",
                    "event_date",
                    "scope",
                    "notes",
                ],
            },
        },
        "retained_gap_contract": {
            "bundle_field": "retained_gaps",
            "required_fields": [
                "gap_key",
                "search_attempts",
                "impact",
                "disclosure",
                "bounded_conclusion",
            ],
            "search_attempts": {
                "type": "array_of_objects",
                "item_required_fields": ["query_or_path", "route"],
                "minimum_items": 2,
                "minimum_distinct_query_or_path_values": 2,
                "minimum_distinct_route_values": 2,
                "all_query_or_path_values_must_be_distinct": True,
                "all_route_values_must_be_distinct": True,
            },
            "rule": (
                "A retained gap must match an actual coverage or claim gap. Each "
                "search_attempt must be an object with non-empty query_or_path and route; "
                "at least two attempts are required and both fields must remain distinct "
                "across attempts."
            ),
        },
        "decision_logic_labels": [
            "explicit",
            "supported_inference",
            "unknown",
        ],
        "cross_axis_requirement": (
            "Connect dated vertical changes to the current horizontal structure, and state "
            "where the relationship is causal, correlational, inferred, or unknown."
        ),
        "scenario_requirement": {
            "rule": (
                "Scenarios are conditional analyses, not predictions, and must be "
                "supported by verified evidence from both research axes."
            ),
            "required_fields": [
                "label",
                "horizon",
                "starting_conditions",
                "causal_path",
                "triggers",
                "invalidators",
                "implications",
            ],
        },
        "scenario_labels": ["most_likely", "optimistic", "danger"],
        "citation_requirement": (
            "Every material factual, numerical, legal, and decision-logic claim must link to "
            "one or more evidence-ledger source IDs."
        ),
        "completion_rule": (
            "Completion is determined by the coverage, contradiction, and gap gates, not by "
            "a target word count."
        ),
    }


def make_limitations(brief: dict[str, Any]) -> list[str]:
    limitations = [
        "This offline plan contains no search results and does not establish that any planned source is available.",
        "Source availability, language coverage, and archive access must be verified during execution.",
        "Scenario sections are conditional analyses and must not be represented as forecasts.",
    ]
    if brief["start_date"] == "unknown":
        limitations.append(
            "start_date is explicitly unknown; the executor must identify the earliest defensible origin and disclose historical coverage limits."
        )
    if brief["geography"] == "unknown":
        limitations.append(
            "geography is explicitly unknown; the executor must disclose observed geographic coverage and avoid global generalization."
        )
    if brief["languages"] == "unknown":
        limitations.append(
            "languages are explicitly unknown; the executor must disclose language coverage and likely language bias."
        )
    if brief["audience"] == "unknown":
        limitations.append(
            "audience is explicitly unknown; the report should use evidence-first neutral language rather than assume a decision context."
        )
    return limitations


def build_plan(raw_brief: dict[str, Any]) -> dict[str, Any]:
    """Validate a brief and return a complete deterministic plan."""
    brief = normalize_brief(raw_brief)
    object_type = brief["object_type"]

    if object_type == "entity":
        vertical_facets = list(ENTITY_VERTICAL_FACETS)
        horizontal_facets = list(ENTITY_HORIZONTAL_FACETS)
        selection = {
            "mode": "fixed_entity_protocol",
            "selection_rule": "all_entity_facets",
            "matched_goal_terms": [],
            "selection_reason": (
                "Entity research always covers competition, differentiation, users, "
                "ecosystem, and trajectory."
            ),
        }
    else:
        vertical_facets = list(INDUSTRY_VERTICAL_FACETS)
        if "horizontal_facets" in brief:
            horizontal_facets = list(brief["horizontal_facets"])
            selection = {
                "mode": "explicit",
                "selection_rule": "user_supplied",
                "matched_goal_terms": [],
                "selection_reason": (
                    "Use the 3-5 valid industry facets explicitly supplied in the brief, "
                    "preserving their order."
                ),
            }
        else:
            horizontal_facets, selection = select_industry_facets(brief["goal"])

    classification = {
        "object_type": object_type,
        "subtype": brief["subtype"],
        "protocol": f"{object_type}_hengzong_v1",
        "scope_status": {
            "unknown_fields": [
                field
                for field in ("start_date", "geography", "languages", "audience")
                if brief[field] == "unknown"
            ],
            "scope_gap_required": any(
                brief[field] == "unknown"
                for field in ("start_date", "geography", "languages", "audience")
            ),
        },
        "vertical_facets": vertical_facets,
        "horizontal_facets": horizontal_facets,
        "horizontal_selection": selection,
    }

    coverage_dimensions = make_coverage_dimensions(brief)
    opportunity_map = future_opportunity_contract(object_type, brief["goal"])

    workstreams = [
        make_workstream(object_type, "longitudinal", index, facet, brief)
        for index, facet in enumerate(vertical_facets, start=1)
    ]
    workstreams.extend(
        make_workstream(object_type, "cross_sectional", index, facet, brief)
        for index, facet in enumerate(horizontal_facets, start=1)
    )

    plan_body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "brief": brief,
        "classification": classification,
        "workstreams": workstreams,
        "coverage_dimensions": coverage_dimensions,
        "evidence_policy": make_evidence_policy(),
        "gates": make_gates(
            [item["id"] for item in workstreams],
            coverage_dimensions,
        ),
        "report_contract": make_report_contract(
            brief,
            coverage_dimensions,
            opportunity_map,
        ),
        "limitations": make_limitations(brief),
        "errors": [],
    }
    plan_id = hashlib.sha256(canonical_json(plan_body).encode("utf-8")).hexdigest()[
        :PLAN_ID_LENGTH
    ]
    return {
        "schema_version": plan_body["schema_version"],
        "plan_id": plan_id,
        **{key: value for key, value in plan_body.items() if key != "schema_version"},
    }


def error_result(error: PlannerError) -> dict[str, Any]:
    """Return the same top-level shape as a successful plan."""
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": None,
        "brief": None,
        "classification": None,
        "workstreams": [],
        "coverage_dimensions": {
            "geographies": [],
            "languages": [],
            "geography_requirements": [],
            "language_requirements": [],
            "query_group_matrix": {
                "status": "invalid_brief",
                "blocking_dimensions": [],
                "groups_per_workstream": 0,
                "maximum_groups_per_workstream": MAX_QUERY_GROUPS_PER_WORKSTREAM,
                "queries_per_group": QUERIES_PER_GROUP,
                "max_query_waves": MAX_QUERY_WAVES,
                "max_results_per_query": MAX_RESULTS_PER_QUERY,
            },
            "gaps": [],
        },
        "evidence_policy": {},
        "gates": {},
        "report_contract": {},
        "limitations": [
            "No research plan was generated because the brief failed closed."
        ],
        "errors": [error.as_dict()],
    }


def read_brief_source(location: str) -> str:
    """Read a bounded UTF-8 brief from a path or stdin."""
    if location == "-":
        source = sys.stdin.read(MAX_BRIEF_BYTES + 1)
    else:
        path = Path(location).expanduser()
        try:
            with path.open("r", encoding="utf-8") as handle:
                source = handle.read(MAX_BRIEF_BYTES + 1)
        except (OSError, UnicodeError) as exc:
            raise PlannerError(
                "brief_read_failed",
                f"unable to read brief as UTF-8: {exc}",
                "brief",
            ) from exc
    if len(source.encode("utf-8")) > MAX_BRIEF_BYTES:
        raise PlannerError(
            "brief_too_large",
            f"brief exceeds {MAX_BRIEF_BYTES} UTF-8 bytes",
            "brief",
        )
    return source


def write_json(payload: dict[str, Any]) -> None:
    json.dump(
        payload,
        sys.stdout,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    sys.stdout.write("\n")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = JsonArgumentParser(
        description="Build an offline deterministic horizontal/vertical research plan."
    )
    parser.add_argument(
        "--brief",
        required=True,
        metavar="PATH|-",
        help="UTF-8 JSON brief path, or - to read stdin",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_arguments(argv)
        raw_brief = parse_brief_json(read_brief_source(args.brief))
        payload = build_plan(raw_brief)
    except PlannerError as exc:
        write_json(error_result(exc))
        return 2
    except Exception as exc:
        error = PlannerError(
            "planner_internal_error",
            f"planner could not produce canonical JSON: {type(exc).__name__}",
        )
        write_json(error_result(error))
        return 3

    write_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
