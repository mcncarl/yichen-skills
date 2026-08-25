import importlib.util
import json
import pathlib
import sys
import unittest
from datetime import date


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "route_search", ROOT / "scripts" / "route_search.py"
)
ROUTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ROUTER
SPEC.loader.exec_module(ROUTER)


def request(**overrides):
    values = {
        "queries": ("agent memory best practices",),
        "platform": "auto",
        "mode": "search",
        "depth": "quick",
        "input_kind": "auto",
        "limit": 10,
        "days": None,
        "domain": None,
        "hybrid": False,
        "login_approved": False,
        "private_data": False,
        "candidate_url": None,
        "candidate_from_search": False,
        "verify_backend": "anysearch",
        "x_include_replies": False,
        "x_include_reposts": False,
        "x_language": None,
        "x_authors": (),
        "x_min_likes": None,
        "x_min_reposts": None,
        "x_min_replies": None,
        "x_min_views": None,
        "x_sort": "relevance",
        "target_results": None,
        "max_searches": 8,
    }
    values.update(overrides)
    return ROUTER.Request(**values)


def option_value(step, option):
    argv = step["argv"]
    return argv[argv.index(option) + 1]


class RouteTests(unittest.TestCase):
    def test_general_web_defaults_to_anysearch(self):
        result = ROUTER.plan(request())
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertEqual(result["status"], "ready")

    def test_zhihu_is_auto_detected_in_chinese_and_english(self):
        for query in ("知乎上的 Agent 讨论", "latest Zhihu discussions about agents"):
            with self.subTest(query=query):
                result = ROUTER.plan(request(queries=(query,)))
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["route"]["platform"], "zhihu")
                self.assertEqual(result["route"]["backend"], "zhihu-open-platform-cli")

    def test_explicit_zhihu_search_uses_allowlisted_cli_adapter(self):
        result = ROUTER.plan(
            request(queries=("agent memory",), platform="zhihu", limit=10)
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "zhihu-open-platform-cli")
        self.assertTrue(result["route"]["login_state_used"])
        step = result["steps"][0]
        self.assertEqual(step["subcommand"], "search")
        self.assertTrue(step["argv"][1].endswith("/zhihu_adapter.py"))
        self.assertEqual(step["argv"][2:], [
            "search",
            "--query",
            "agent memory",
            "--limit",
            "10",
        ])
        self.assertNotIn("anysearch", " ".join(step["argv"]).lower())
        self.assertNotIn("site:", " ".join(step["argv"]).lower())

    def test_zhihu_search_clamps_each_query_to_ten(self):
        result = ROUTER.plan(
            request(queries=("agent memory",), platform="zhihu", limit=50)
        )
        self.assertEqual(option_value(result["steps"][0], "--limit"), "10")
        self.assertIn("at most 10", " ".join(result["limitations"]))

    def test_zhihu_batch_uses_at_most_five_independent_search_calls(self):
        queries = ("知乎 query 1", "query 2", "query 3", "query 4", "query 5")
        result = ROUTER.plan(request(queries=queries, mode="batch"))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "zhihu-open-platform-cli")
        self.assertEqual(len(result["steps"]), 5)
        self.assertEqual(
            [option_value(step, "--query") for step in result["steps"]],
            list(queries),
        )
        self.assertTrue(
            all(step["subcommand"] == "search" for step in result["steps"])
        )
        self.assertTrue(
            all("anysearch" not in " ".join(step["argv"]).lower() for step in result["steps"])
        )

    def test_zhihu_batch_rejects_more_than_five_queries(self):
        queries = tuple(f"知乎 query {index}" for index in range(1, 7))
        result = ROUTER.plan(request(queries=queries, mode="batch"))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_explicit_zhihu_batch_does_not_require_hint_in_each_query(self):
        result = ROUTER.plan(
            request(
                queries=("agent memory", "RAG workflow"),
                platform="zhihu",
                mode="batch",
            )
        )
        self.assertEqual(result["route"]["backend"], "zhihu-open-platform-cli")
        self.assertEqual(len(result["steps"]), 2)

    def test_zhihu_hot_requires_explicit_or_auto_detected_zhihu(self):
        explicit = ROUTER.plan(
            request(queries=("热榜",), platform="zhihu", mode="hot", limit=30)
        )
        automatic = ROUTER.plan(
            request(queries=("知乎热榜",), mode="hot", limit=30)
        )
        for result in (explicit, automatic):
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["route"]["backend"], "zhihu-open-platform-cli")
            self.assertEqual(result["route"]["mode"], "hot")
            self.assertTrue(result["route"]["login_state_used"])
            self.assertEqual(
                result["steps"][0]["argv"][2:], ["hot", "--limit", "30"]
            )
            self.assertTrue(
                any(
                    "without sending the routing query text" in item
                    for item in result["limitations"]
                )
            )
            self.assertFalse(
                any(
                    "query is sent to Zhihu" in item
                    for item in result["limitations"]
                )
            )

        unrelated = ROUTER.plan(request(queries=("technology hot list",), mode="hot"))
        self.assertEqual(unrelated["status"], "invalid_request")
        self.assertEqual(unrelated["steps"], [])

    def test_zhihu_hot_rejects_limit_over_thirty(self):
        result = ROUTER.plan(
            request(queries=("知乎热榜",), mode="hot", limit=31)
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_zhihu_cli_route_rejects_incompatible_options(self):
        scenarios = (
            request(platform="zhihu", domain="social_media"),
            request(platform="zhihu", domain="social_media", hybrid=True),
            request(platform="zhihu", days=7),
            request(platform="zhihu", x_include_replies=True),
            request(platform="zhihu", private_data=True),
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result = ROUTER.plan(scenario)
                self.assertIn(result["status"], {"invalid_request", "blocked"})
                self.assertEqual(result["steps"], [])

    def test_weibo_is_auto_detected_in_chinese_and_english(self):
        for query in ("微博上的 iPhone 18 讨论", "latest Weibo posts about iPhone 18"):
            with self.subTest(query=query):
                result = ROUTER.plan(request(queries=(query,)))
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["route"]["platform"], "weibo")
                self.assertEqual(result["route"]["backend"], "weibo-readonly-auto")
                self.assertFalse(result["route"]["login_state_used"])
                self.assertEqual(
                    result["route"]["login_state_use"],
                    "conditional_on_anonymous_access_gate_failure",
                )

    def test_explicit_weibo_search_uses_bounded_readonly_auto_adapter(self):
        result = ROUTER.plan(
            request(
                queries=("iPhone 18",),
                platform="weibo",
                limit=50,
                days=30,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["authorization"], "not_required")
        step = result["steps"][0]
        self.assertEqual(step["subcommand"], "search")
        self.assertTrue(step["argv"][1].endswith("/weibo_adapter.py"))
        self.assertEqual(option_value(step, "--query"), "iPhone 18")
        self.assertEqual(option_value(step, "--limit"), "20")
        self.assertEqual(option_value(step, "--max-pages"), "3")
        self.assertEqual(option_value(step, "--session-mode"), "auto")
        self.assertEqual(option_value(step, "--days"), "30")
        command = " ".join(step["argv"]).lower()
        self.assertNotIn("anysearch", command)
        self.assertNotIn("site:", command)
        self.assertIn("at most 20", " ".join(result["limitations"]))

    def test_weibo_batch_uses_at_most_five_independent_adapter_calls(self):
        queries = ("iPhone 18", "苹果折叠屏", "Apple A20")
        result = ROUTER.plan(
            request(queries=queries, platform="weibo", mode="batch")
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "weibo-readonly-auto")
        self.assertEqual(
            [option_value(step, "--query") for step in result["steps"]],
            list(queries),
        )
        self.assertTrue(
            all(step["subcommand"] == "search" for step in result["steps"])
        )
        self.assertTrue(
            all(step["execution"]["mode"] == "serial" for step in result["steps"])
        )
        self.assertTrue(
            all(
                step["execution"]["minimum_gap_seconds_after_step"] == 5
                for step in result["steps"]
            )
        )

        too_many = ROUTER.plan(
            request(
                queries=tuple(f"微博 query {index}" for index in range(6)),
                mode="batch",
            )
        )
        self.assertEqual(too_many["status"], "invalid_request")
        self.assertEqual(too_many["steps"], [])

    def test_weibo_rejects_incompatible_or_unbounded_options(self):
        scenarios = (
            request(platform="weibo", domain="social_media"),
            request(platform="weibo", hybrid=True, domain="social_media"),
            request(platform="weibo", days=0),
            request(platform="weibo", mode="batch", queries=()),
            request(platform="weibo", queries=("one", "two")),
            request(platform="weibo", private_data=True),
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result = ROUTER.plan(scenario)
                self.assertIn(result["status"], {"invalid_request", "blocked"})
                self.assertEqual(result["steps"], [])

    def test_ordinary_web_search_is_unchanged_by_zhihu_route(self):
        result = ROUTER.plan(request(queries=("agent memory best practices",)))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["platform"], "web")
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertTrue(result["steps"][0]["argv"][1].endswith("/anysearch_adapter.py"))

    def test_known_zhihu_url_still_handoffs_to_content_archive(self):
        result = ROUTER.plan(
            request(queries=("https://www.zhihu.com/question/123456",))
        )
        self.assertEqual(result["status"], "handoff_required")
        self.assertEqual(result["handoff_skill"], "yichen-content-archive")
        self.assertEqual(result["steps"], [])

    def test_current_ai_discovery_routes_to_aihot_selected(self):
        result = ROUTER.plan(request(queries=("今天 AI 圈有什么新动态",)))
        self.assertEqual(result["route"]["backend"], "aihot")
        argv = result["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--feed") + 1], "selected")
        self.assertEqual(argv[argv.index("--days") + 1], "1")
        self.assertEqual(result["steps"][0]["skill_contract"], "aihot")

    def test_static_ai_research_stays_on_anysearch(self):
        result = ROUTER.plan(request(queries=("RAG 是什么以及它的工作原理",)))
        self.assertEqual(result["route"]["backend"], "anysearch")

    def test_aihot_daily_is_only_selected_by_daily_wording(self):
        result = ROUTER.plan(request(queries=("给我今天的 AI 日报",)))
        argv = result["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--feed") + 1], "daily")
        self.assertNotIn("--days", argv)

    def test_aihot_dated_daily_forwards_explicit_date(self):
        result = ROUTER.plan(request(queries=("看 2026-07-30 的 AI 日报",)))
        argv = result["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--date") + 1], "2026-07-30")

    def test_aihot_relative_daily_date_is_resolved(self):
        self.assertEqual(
            ROUTER.infer_aihot_date("昨天的 AI 日报", today=date(2026, 7, 31)),
            "2026-07-30",
        )

    def test_aihot_all_papers_maps_feed_and_category(self):
        result = ROUTER.plan(request(queries=("最近全部 AI 论文动态",)))
        argv = result["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--feed") + 1], "all")
        self.assertEqual(argv[argv.index("--category") + 1], "paper")

    def test_aihot_named_entity_uses_server_side_keyword(self):
        result = ROUTER.plan(request(queries=("OpenAI 最近发布了什么",)))
        argv = result["steps"][0]["argv"]
        self.assertEqual(argv[argv.index("--keyword") + 1], "OpenAI")

    def test_explicit_platform_intent_wins_over_aihot(self):
        result = ROUTER.plan(request(queries=("X 上最近的 AI 动态",)))
        self.assertEqual(result["route"]["backend"], "grok-consult")

    def test_long_ai_window_auto_falls_back_to_anysearch(self):
        result = ROUTER.plan(
            request(queries=("最近一个月 AI 新闻",), days=30)
        )
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertIn("latest 7 days", " ".join(result["limitations"]))

    def test_long_ai_window_explicit_aihot_is_rejected(self):
        result = ROUTER.plan(
            request(queries=("最近一个月 AI 新闻",), platform="aihot", days=30)
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_vertical_search_discovers_subdomains_first(self):
        result = ROUTER.plan(request(domain="legal"))
        self.assertEqual(result["steps"][1]["subcommand"], "get_sub_domains")
        self.assertEqual(result["steps"][2]["subcommand"], "search")
        self.assertEqual(result["steps"][2]["action"], "invoke_existing_adapter")

    def test_vertical_batch_discovers_subdomains_and_preserves_scope(self):
        result = ROUTER.plan(
            request(
                queries=("contract damages", "arbitration award"),
                mode="batch",
                domain="legal",
            )
        )
        self.assertEqual(result["steps"][1]["subcommand"], "get_sub_domains")
        self.assertEqual(result["steps"][2]["subcommand"], "batch")
        payload = json.loads(option_value(result["steps"][2], "--queries"))
        self.assertEqual(
            [item["query"] for item in payload],
            ["contract damages", "arbitration award"],
        )
        for item in payload:
            self.assertEqual(item["domain"], "legal")
            self.assertEqual(item["sub_domain"], "<from-get_sub_domains>")
            self.assertEqual(
                item["sub_domain_params"], "<all-required-params>"
            )

    def test_vertical_multi_query_search_uses_scoped_batch(self):
        result = ROUTER.plan(
            request(queries=("query one", "query two"), domain="legal")
        )
        self.assertEqual(result["steps"][1]["subcommand"], "get_sub_domains")
        self.assertEqual(result["steps"][2]["subcommand"], "batch")
        payload = json.loads(option_value(result["steps"][2], "--queries"))
        self.assertTrue(all(item["domain"] == "legal" for item in payload))

    def test_hybrid_requires_vertical_domain(self):
        result = ROUTER.plan(request(hybrid=True))
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("requires", result["reason"])
        self.assertEqual(result["steps"], [])

    def test_hybrid_rejects_non_search_mode(self):
        result = ROUTER.plan(
            request(mode="channel", domain="legal", hybrid=True)
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("search and batch", result["reason"])
        self.assertEqual(result["steps"], [])

    def test_hybrid_single_query_emits_general_then_vertical(self):
        result = ROUTER.plan(request(domain="legal", hybrid=True))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["reason"], "public_web_general_plus_vertical")
        self.assertEqual(result["steps"][1]["subcommand"], "get_sub_domains")
        payload = json.loads(option_value(result["steps"][2], "--queries"))
        self.assertEqual(len(payload), 2)
        self.assertNotIn("domain", payload[0])
        self.assertEqual(payload[1]["domain"], "legal")
        self.assertEqual(payload[0]["query"], payload[1]["query"])

    def test_hybrid_chunks_expanded_payloads_at_five(self):
        result = ROUTER.plan(
            request(
                queries=("query one", "query two", "query three"),
                mode="batch",
                domain="legal",
                hybrid=True,
            )
        )
        batch_steps = [
            step for step in result["steps"] if step.get("subcommand") == "batch"
        ]
        payloads = [json.loads(option_value(step, "--queries")) for step in batch_steps]
        self.assertEqual([len(payload) for payload in payloads], [5, 1])
        self.assertTrue(all(len(payload) <= 5 for payload in payloads))

    def test_batch_platform_scope_uses_public_site_index(self):
        result = ROUTER.plan(
            request(
                queries=("topic one", "topic two"),
                platform="xiaohongshu",
                mode="batch",
            )
        )
        self.assertEqual(result["route"]["backend"], "anysearch")
        payload = option_value(result["steps"][0], "--queries")
        self.assertIn("site:xiaohongshu.com", payload)
        self.assertTrue(result["limitations"])

    def test_anysearch_clamps_per_query_limit_to_ten(self):
        result = ROUTER.plan(request(limit=50))
        self.assertEqual(option_value(result["steps"][0], "--max-results"), "10")
        self.assertTrue(result["limitations"])

    def test_anysearch_batch_is_split_into_groups_of_five(self):
        queries = tuple(f"query {index}" for index in range(11))
        result = ROUTER.plan(request(queries=queries, mode="batch"))
        batch_steps = [
            step for step in result["steps"] if step.get("subcommand") == "batch"
        ]
        self.assertEqual(len(batch_steps), 3)

    def test_auto_batch_does_not_send_mixed_queries_to_aihot(self):
        result = ROUTER.plan(
            request(
                queries=("今天 AI 圈有什么", "全球半导体供应链"),
                mode="batch",
            )
        )
        self.assertEqual(result["route"]["backend"], "anysearch")

    def test_auto_batch_keeps_public_web_semantics_even_with_x_wording(self):
        result = ROUTER.plan(
            request(
                queries=("X 上的 OpenAI", "Twitter 上的 Anthropic"),
                mode="batch",
                days=30,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "anysearch")

    def test_xiaohongshu_bounded_public_search_needs_no_per_run_authorization(self):
        result = ROUTER.plan(request(platform="xiaohongshu"))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["authorization"], "not_required")
        self.assertEqual(result["route"]["backend"], "opencli")
        self.assertTrue(result["route"]["login_state_used"])
        self.assertEqual(option_value(result["steps"][0], "--limit"), "10")
        self.assertEqual(option_value(result["steps"][0], "--window"), "background")
        self.assertEqual(option_value(result["steps"][0], "--site-session"), "ephemeral")
        self.assertEqual(option_value(result["steps"][0], "--keep-tab"), "false")
        self.assertEqual(result["steps"][0]["execution"]["mode"], "serial")
        self.assertEqual(
            result["steps"][0]["execution"]["minimum_gap_seconds_after_step"], 5
        )

    def test_legacy_login_approved_flag_does_not_change_readonly_route(self):
        without_flag = ROUTER.plan(request(platform="xiaohongshu"))
        result = ROUTER.plan(request(platform="xiaohongshu", login_approved=True))
        self.assertEqual(result, without_flag)

    def test_xiaohongshu_limit_is_clamped_to_twenty(self):
        result = ROUTER.plan(request(platform="xiaohongshu", limit=99))
        self.assertEqual(option_value(result["steps"][0], "--limit"), "20")

    def test_invalid_xiaohongshu_days_is_rejected_offline(self):
        result = ROUTER.plan(request(platform="xiaohongshu", days=30))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_invalid_toutiao_days_is_rejected_offline(self):
        result = ROUTER.plan(request(platform="toutiao", days=180))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_wechat_search_is_public_and_never_uses_wechat_ui(self):
        result = ROUTER.plan(request(platform="wechat"))
        self.assertEqual(result["route"]["backend"], "opencli-weixin-public")
        self.assertFalse(result["route"]["login_state_used"])

    def test_x_routes_to_grok_then_fxtwitter_only_on_quota(self):
        result = ROUTER.plan(request(platform="x"))
        self.assertEqual(
            result["authorization"],
            "fallback_requires_current_turn_authorization",
        )
        self.assertEqual(result["route"]["backend"], "grok-consult")
        self.assertTrue(result["route"]["login_state_used"])
        self.assertEqual(result["steps"][0]["backend"], "grok-consult")
        self.assertEqual(result["steps"][0]["tool"], "search_x_with_grok")
        self.assertFalse(
            result["steps"][0]["arguments"]["allow_authenticated_fallback"]
        )
        self.assertEqual(
            result["steps"][0]["authenticated_fallback_when"],
            "disabled",
        )
        self.assertFalse(result["route"]["authenticated_fallback_allowed"])
        self.assertEqual(
            result["steps"][0]["fxtwitter_when"],
            "explicit_account_quota_exhausted_only",
        )
        self.assertEqual(
            result["steps"][0]["contains_read_only_chain"],
            [
                "official_grok_cli_account_quota",
                "fxtwitter-public",
                "opencli",
                "xreach",
            ],
        )
        self.assertIn(
            "timeout",
            result["steps"][0]["must_stop_without_fallback_when"],
        )
        normalizer = result["steps"][0]["result_normalizer"]
        self.assertTrue(normalizer["script"].endswith("/grok_x_result_adapter.py"))
        self.assertEqual(
            normalizer["accepted_result_path"],
            "x_post_time_verification.matched",
        )

    def test_x_authenticated_fallback_requires_explicit_current_task_flag(self):
        result = ROUTER.plan(request(platform="x", login_approved=True))
        self.assertEqual(
            result["authorization"],
            "current_turn_authenticated_fallback_authorized",
        )
        self.assertTrue(
            result["steps"][0]["arguments"]["allow_authenticated_fallback"]
        )
        self.assertEqual(
            result["steps"][0]["authenticated_fallback_when"],
            "explicit_current_task_authorization",
        )
        self.assertTrue(result["route"]["authenticated_fallback_allowed"])

    def test_x_days_is_forwarded_to_grok_as_hours(self):
        result = ROUTER.plan(request(platform="x", days=1))
        self.assertEqual(result["steps"][0]["arguments"]["hours"], 24)

    def test_x_multi_query_quick_search_never_drops_queries(self):
        result = ROUTER.plan(
            request(
                platform="x",
                queries=("OpenAI model releases", "Anthropic model releases"),
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["depth"], "quick")
        self.assertEqual(
            [step["arguments"]["query"] for step in result["steps"]],
            ["OpenAI model releases", "Anthropic model releases"],
        )
        self.assertNotIn("research", result)

    def test_x_queries_are_trimmed_and_deduplicated(self):
        result = ROUTER.plan(
            request(
                platform="x",
                queries=(" OpenAI ", "openai", "Anthropic"),
            )
        )
        self.assertEqual(
            [step["arguments"]["query"] for step in result["steps"]],
            ["OpenAI", "Anthropic"],
        )

    def test_x_limit_is_clamped_to_grok_per_call_maximum(self):
        result = ROUTER.plan(request(platform="x", limit=50))
        self.assertEqual(result["steps"][0]["arguments"]["max_results"], 20)
        self.assertIn("at most 20", " ".join(result["limitations"]))

    def test_x_seven_days_maps_to_maximum_168_hours(self):
        result = ROUTER.plan(request(platform="x", days=7))
        self.assertEqual(result["steps"][0]["arguments"]["hours"], 168)

    def test_x_zero_or_more_than_seven_days_is_rejected(self):
        for days in (0, 8, 30):
            with self.subTest(days=days):
                result = ROUTER.plan(request(platform="x", days=days))
                self.assertEqual(result["status"], "invalid_request")
                self.assertEqual(result["steps"], [])

    def test_x_default_criteria_excludes_reposts_and_replies(self):
        result = ROUTER.plan(request(platform="x"))
        criteria = result["steps"][0]["arguments"]["criteria"]
        self.assertIn("Exclude reposts", criteria)
        self.assertIn("Exclude replies", criteria)

    def test_x_filters_are_forwarded_as_search_criteria(self):
        result = ROUTER.plan(
            request(
                platform="x",
                x_include_replies=True,
                x_authors=("OpenAI", "@AnthropicAI"),
                x_language="English",
                x_min_likes=100,
                x_sort="engagement",
            )
        )
        criteria = result["steps"][0]["arguments"]["criteria"]
        self.assertIn("Replies may be included", criteria)
        self.assertIn("@openai, @anthropicai", criteria)
        self.assertIn("language English", criteria)
        self.assertIn("likes greater than or equal to 100", criteria)
        self.assertIn("total engagement", criteria)

    def test_x_research_requires_at_least_three_queries(self):
        result = ROUTER.plan(
            request(platform="x", depth="research", queries=("AI agents",))
        )
        self.assertEqual(result["status"], "needs_query_expansion")
        self.assertEqual(result["steps"], [])
        self.assertEqual(result["query_expansion"]["minimum_queries"], 3)

    def test_x_research_emits_independent_calls_and_bounded_protocol(self):
        queries = ("AI agent launches", "AI agent benchmarks", "AI agent failures")
        result = ROUTER.plan(
            request(
                platform="x",
                depth="research",
                queries=queries,
                limit=50,
                target_results=100,
                max_searches=6,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["depth"], "research")
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(
            [step["arguments"]["query"] for step in result["steps"]],
            list(queries),
        )
        self.assertTrue(
            all(step["arguments"]["max_results"] == 20 for step in result["steps"])
        )
        protocol = result["research"]
        self.assertEqual(protocol["target_unique_results"], 100)
        self.assertEqual(protocol["minimum_calls_for_target_before_duplicates"], 5)
        self.assertEqual(protocol["additional_focused_queries_needed_for_capacity"], 2)
        self.assertEqual(protocol["max_searches"], 6)
        self.assertEqual(protocol["remaining_search_budget"], 3)
        self.assertEqual(protocol["max_supplementary_searches"], 3)
        self.assertEqual(protocol["max_gap_fill_rounds"], 1)
        self.assertEqual(protocol["dedupe_key"], "tweet_id_then_canonical_url")
        self.assertEqual(
            protocol["accepted_grok_result_path"],
            "x_post_time_verification.matched",
        )
        supplementary = protocol["supplementary_search_template"]
        self.assertEqual(supplementary["research_phase"], "supplementary")
        self.assertEqual(
            supplementary["result_normalizer"]["argv"][7],
            "<next-call-index>",
        )

    def test_x_research_rejects_impossible_target(self):
        result = ROUTER.plan(
            request(
                platform="x",
                depth="research",
                queries=("query one", "query two", "query three"),
                target_results=500,
                max_searches=8,
            )
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("search budget", result["reason"])

    def test_x_research_exposes_only_first_wave_until_merge_gate(self):
        queries = tuple(f"focused query {index}" for index in range(1, 13))
        result = ROUTER.plan(
            request(
                platform="x",
                depth="research",
                queries=queries,
                target_results=20,
                max_searches=12,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(
            [step["arguments"]["query"] for step in result["steps"]],
            list(queries[:2]),
        )
        waves = result["research"]["initial_waves"]
        self.assertEqual([wave["step_count"] for wave in waves], [2, 5, 5])
        self.assertEqual([len(wave["steps"]) for wave in waves], [0, 5, 5])
        self.assertEqual(waves[0]["execute_from"], "top_level_steps")
        self.assertEqual([wave["status"] for wave in waves], ["ready", "gated", "gated"])
        self.assertEqual(result["research"]["ready_initial_searches"], 2)
        self.assertEqual(result["research"]["gated_initial_searches"], 10)

    def test_x_specific_options_are_rejected_when_batch_would_ignore_them(self):
        result = ROUTER.plan(
            request(
                platform="x",
                mode="batch",
                queries=("query one", "query two"),
                x_min_likes=10,
            )
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_x_specific_options_are_rejected_when_domain_would_ignore_them(self):
        result = ROUTER.plan(
            request(platform="x", domain="social_media", x_sort="recent")
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_quick_rejects_custom_research_budget(self):
        result = ROUTER.plan(
            request(platform="x", depth="quick", max_searches=20)
        )
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("research depth", result["reason"])

    def test_research_depth_is_rejected_outside_native_x_search(self):
        result = ROUTER.plan(request(platform="web", depth="research"))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_x_batch_remains_public_site_index_for_compatibility(self):
        result = ROUTER.plan(
            request(
                platform="x",
                mode="batch",
                queries=("query one", "query two"),
            )
        )
        self.assertEqual(result["route"]["backend"], "anysearch")
        payload = option_value(result["steps"][0], "--queries")
        self.assertIn("site:x.com", payload)

    def test_xiaoyuzhou_keyword_search_uses_public_site_discovery(self):
        result = ROUTER.plan(request(platform="xiaoyuzhou"))
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertIn("site:xiaoyuzhoufm.com", result["steps"][0]["argv"][3])

    def test_youtube_search_uses_local_public_adapter(self):
        result = ROUTER.plan(request(platform="youtube"))
        self.assertEqual(result["route"]["backend"], "youtube-public-search")
        argv = result["steps"][0]["argv"]
        self.assertTrue(argv[1].endswith("/youtube_search.py"))
        self.assertEqual(argv[2], "search")
        self.assertNotIn("download", argv)

    def test_youtube_channel_mode_accepts_exact_channel_url(self):
        result = ROUTER.plan(
            request(
                queries=("https://www.youtube.com/@example",),
                platform="youtube",
                mode="channel",
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "youtube-public-search")
        self.assertEqual(result["steps"][0]["argv"][2], "channel")

    def test_channel_mode_is_rejected_for_non_youtube_platforms(self):
        result = ROUTER.plan(request(platform="github", mode="channel"))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_github_query_is_positional_and_cannot_inject_gh_options(self):
        result = ROUTER.plan(
            request(
                queries=("--visibility=private",),
                platform="github",
                limit=1,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            result["steps"][0]["argv"],
            [
                "gh",
                "search",
                "repos",
                "--visibility",
                "public",
                "--limit",
                "1",
                "--",
                "--visibility=private",
            ],
        )
        self.assertEqual(result["authorization"], "not_required")
        self.assertTrue(result["route"]["login_state_used"])
        self.assertIn("--visibility public", " ".join(result["limitations"]))

    def test_private_data_is_blocked(self):
        result = ROUTER.plan(request(private_data=True))
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["route"])

    def test_direct_known_url_handoffs_to_content_archive(self):
        result = ROUTER.plan(request(queries=("https://example.com/article",)))
        self.assertEqual(result["status"], "handoff_required")
        self.assertEqual(result["handoff_skill"], "yichen-content-archive")
        self.assertEqual(result["steps"], [])

    def test_known_url_embedded_in_instruction_also_handoffs(self):
        result = ROUTER.plan(
            request(queries=("请读一下 https://example.com/article",))
        )
        self.assertEqual(result["status"], "handoff_required")
        self.assertEqual(result["handoff_skill"], "yichen-content-archive")

    def test_url_can_be_an_explicit_discovery_seed(self):
        result = ROUTER.plan(
            request(
                queries=(
                    "搜索引用 https://example.com/research 的公开报道",
                ),
                platform="web",
                input_kind="url-seed",
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertIn("discovery seed", " ".join(result["limitations"]))

    def test_url_seed_without_url_is_rejected(self):
        result = ROUTER.plan(request(input_kind="url-seed"))
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(result["steps"], [])

    def test_explicit_known_url_always_handoffs(self):
        result = ROUTER.plan(
            request(
                queries=("请搜索这个网页",),
                input_kind="known-url",
            )
        )
        self.assertEqual(result["status"], "handoff_required")
        self.assertEqual(result["handoff_skill"], "yichen-content-archive")

    def test_unprovenanced_candidate_url_handoffs_to_content_archive(self):
        result = ROUTER.plan(
            request(
                mode="verify-candidate",
                candidate_url="https://example.com/article",
            )
        )
        self.assertEqual(result["status"], "handoff_required")
        self.assertEqual(result["handoff_skill"], "yichen-content-archive")

    def test_current_search_candidate_uses_normalizing_verify_adapter(self):
        result = ROUTER.plan(
            request(
                mode="verify-candidate",
                candidate_url="https://example.com/article",
                candidate_from_search=True,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["mode"], "verify-candidate")
        self.assertEqual(result["steps"][0]["subcommand"], "verify")
        self.assertEqual(
            result["steps"][0]["action"], "invoke_existing_adapter"
        )
        self.assertEqual(result["steps"][0]["backend"], "anysearch")
        self.assertEqual(
            result["steps"][0]["requested_candidate_url"],
            "https://example.com/article",
        )
        self.assertEqual(
            option_value(result["steps"][0], "--candidate-from-search"),
            "<full-current-anysearch-candidate-json-or-@file>",
        )
        self.assertNotIn("https://example.com/article", result["steps"][0]["argv"])

    def test_firecrawl_is_never_selected_by_ordinary_search(self):
        result = ROUTER.plan(request(verify_backend="firecrawl"))
        self.assertEqual(result["route"]["backend"], "anysearch")
        self.assertNotIn("firecrawl_adapter.py", " ".join(result["steps"][0]["argv"]))

    def test_explicit_site_map_uses_bounded_firecrawl_adapter(self):
        result = ROUTER.plan(
            request(
                queries=("https://example.com/docs/",),
                platform="web",
                mode="site-map",
                limit=100,
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "firecrawl")
        self.assertEqual(result["route"]["mode"], "site-map")
        self.assertEqual(result["steps"][0]["subcommand"], "map")
        self.assertEqual(option_value(result["steps"][0], "--limit"), "100")
        self.assertEqual(
            option_value(result["steps"][0], "--url"),
            "https://example.com/docs/",
        )

    def test_site_map_rejects_unbounded_or_non_url_requests(self):
        too_many = ROUTER.plan(
            request(queries=("https://example.com/",), mode="site-map", limit=101)
        )
        self.assertEqual(too_many["status"], "invalid_request")
        not_url = ROUTER.plan(request(mode="site-map"))
        self.assertEqual(not_url["status"], "invalid_request")
        multiple = ROUTER.plan(
            request(
                queries=("https://example.com/", "https://example.org/"),
                mode="site-map",
            )
        )
        self.assertEqual(multiple["status"], "invalid_request")

    def test_site_map_rejects_private_obfuscated_and_malformed_hosts_offline(self):
        unsafe_urls = (
            "http://127.0.0.1/",
            "https://%31%32%37.0.0.1/",
            "https://１２７。０。０。１/",
            "https://0x7f.1/",
            "https://0177.0.0.1/",
            "https://2130706433/",
            "https://127.1/",
            "https://intranet/",
            "https://example.com:invalid/",
            "https://example..com/",
        )
        for url in unsafe_urls:
            with self.subTest(url=url):
                result = ROUTER.plan(
                    request(queries=(url,), platform="web", mode="site-map")
                )
                self.assertEqual(result["status"], "invalid_request")
                self.assertEqual(result["steps"], [])

    def test_site_map_route_uses_modern_uts46_host_normalization(self):
        self.assertEqual(ROUTER._normalize_host_uts46("faß.de"), "xn--fa-hia.de")
        self.assertEqual(ROUTER._normalize_host_uts46("ς.gr"), "xn--3xa.gr")
        self.assertEqual(
            ROUTER._normalize_host_uts46("Bücher.de"), "xn--bcher-kva.de"
        )
        self.assertFalse(ROUTER.is_public_http_url("https://ab\u200ccd.com/docs"))
        self.assertFalse(ROUTER.is_public_http_url("https://１２７。０。０。１/docs"))

    def test_current_search_candidate_can_explicitly_use_firecrawl_scrape(self):
        result = ROUTER.plan(
            request(
                mode="verify-candidate",
                candidate_url="https://example.com/article",
                candidate_from_search=True,
                verify_backend="firecrawl",
            )
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"]["backend"], "firecrawl")
        self.assertEqual(result["steps"][0]["subcommand"], "scrape")
        self.assertEqual(
            option_value(result["steps"][0], "--candidate-from-search"),
            "<full-current-anysearch-candidate-json-or-@file>",
        )
        self.assertNotIn("https://example.com/article", result["steps"][0]["argv"])

    def test_candidate_verification_rejects_non_web_platform_for_both_backends(self):
        for backend in ("anysearch", "firecrawl"):
            with self.subTest(backend=backend):
                result = ROUTER.plan(
                    request(
                        platform="x",
                        mode="verify-candidate",
                        candidate_url="https://example.com/article",
                        candidate_from_search=True,
                        verify_backend=backend,
                    )
                )
                self.assertEqual(result["status"], "invalid_request")
                self.assertEqual(result["steps"], [])

    def test_search_batch_and_verify_never_use_raw_anysearch_execution(self):
        scenarios = (
            request(),
            request(queries=("one", "two"), mode="batch"),
            request(domain="legal"),
            request(
                mode="verify-candidate",
                candidate_url="https://example.com/article",
                candidate_from_search=True,
            ),
        )
        for scenario in scenarios:
            with self.subTest(mode=scenario.mode, domain=scenario.domain):
                result = ROUTER.plan(scenario)
                raw_subcommands = {
                    step.get("subcommand")
                    for step in result["steps"]
                    if step.get("action") == "invoke_anysearch"
                }
                self.assertTrue(
                    raw_subcommands.isdisjoint({"search", "batch_search", "extract"})
                )


if __name__ == "__main__":
    unittest.main()
