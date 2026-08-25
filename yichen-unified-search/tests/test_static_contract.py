import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"


class StaticContractTests(unittest.TestCase):
    def test_frontmatter_has_only_name_and_description(self):
        text = SKILL.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
        self.assertIsNotNone(match)
        keys = []
        for line in match.group(1).splitlines():
            if line and not line.startswith((" ", "\t")) and ":" in line:
                keys.append(line.split(":", 1)[0])
        self.assertEqual(keys, ["name", "description"])

    def test_required_contract_language_is_present(self):
        text = SKILL.read_text(encoding="utf-8")
        required = (
            "AnySearch",
            "AI HOT",
            "绝对不得操控微信",
            "不下载媒体",
            "不读取、同步或搜索私人收藏",
            "candidate-schema.md",
            "routes.md",
            "doctor_yichen.py",
            "$yichen-content-archive",
            "本次搜索所得候选",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_linked_files_exist(self):
        for relative in (
            "README.md",
            "references/routes.md",
            "references/candidate-schema.md",
            "scripts/route_search.py",
            "scripts/anysearch_adapter.py",
            "scripts/zhihu_adapter.py",
            "scripts/firecrawl_adapter.py",
            "scripts/aihot_search.py",
            "scripts/fxtwitter_search.py",
            "scripts/grok_x_result_adapter.py",
            "scripts/x_research_merge.py",
            "scripts/youtube_search.py",
            "scripts/weibo_adapter.py",
            "references/THIRD_PARTY_NOTICES.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_public_tree_uses_portable_paths(self):
        private_home_pattern = re.compile("/" + r"Users/[^/\s]+")
        text_files = [
            *ROOT.rglob("*.py"),
            *ROOT.rglob("*.md"),
            *ROOT.rglob("*.yaml"),
        ]
        for path in text_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(private_home_pattern.search(text))

        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        anysearch = (ROOT / "scripts" / "anysearch_adapter.py").read_text(
            encoding="utf-8"
        )
        firecrawl = (ROOT / "scripts" / "firecrawl_adapter.py").read_text(
            encoding="utf-8"
        )
        zhihu = (ROOT / "scripts" / "zhihu_adapter.py").read_text(encoding="utf-8")
        self.assertIn("Path(__file__).resolve()", router)
        self.assertIn("YICHEN_SKILLS_ROOT", router)
        self.assertIn("YICHEN_ANYSEARCH_RUNTIME_CONF", anysearch)
        self.assertIn("YICHEN_UNIFIED_SEARCH_RECEIPT_KEY_FILE", anysearch)
        self.assertIn("FIRECRAWL_KEY_FILE", firecrawl)
        self.assertIn("Path.home()", firecrawl)
        self.assertIn('ZHIHU_CLI_ENV = "ZHIHU_CLI"', zhihu)
        self.assertIn("Path.home()", zhihu)

    def test_router_does_not_import_network_clients(self):
        text = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "http.client", "subprocess"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_x_research_contract_is_bounded_and_time_matched_only(self):
        skill = SKILL.read_text(encoding="utf-8")
        required = (
            "--depth research",
            "<x_post_time_verification>.matched",
            "excluded_outside_window",
            "tweet_id",
            "最多 40",
            "最多补搜一轮",
            "Grok `criteria` 只是检索约束",
            "grok_x_result_adapter.py",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_x_research_helpers_are_offline_and_non_persistent(self):
        forbidden_patterns = (
            r"(?:from|import)\s+urllib\.request",
            r"(?:from|import)\s+requests\b",
            r"(?:from|import)\s+http\.client",
            r"(?:from|import)\s+subprocess\b",
            r"\.unlink\(",
            r"shutil\.rmtree",
        )
        for relative in (
            "scripts/grok_x_result_adapter.py",
            "scripts/x_research_merge.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                with self.subTest(relative=relative, pattern=pattern):
                    self.assertNotRegex(text, pattern)

    def test_anysearch_execution_is_normalized_by_adapter(self):
        skill = SKILL.read_text(encoding="utf-8")
        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        self.assertIn("anysearch_adapter.py", skill)
        self.assertIn("ANYSEARCH_ADAPTER", router)
        for subcommand in ("search", "batch", "verify"):
            with self.subTest(subcommand=subcommand):
                self.assertRegex(
                    router, rf'adapter_step\(\s*"{subcommand}"'
                )

    def test_zhihu_cli_route_is_native_bounded_and_candidate_only(self):
        skill = SKILL.read_text(encoding="utf-8")
        routes = (ROOT / "references" / "routes.md").read_text(encoding="utf-8")
        schema = (ROOT / "references" / "candidate-schema.md").read_text(
            encoding="utf-8"
        )
        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        notices = (ROOT / "references" / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((skill, routes, schema, notices))
        required = (
            "zhihu-open-platform-cli",
            "zhihu_adapter.py",
            "global_search",
            "zhida",
            "Keychain",
            "candidate",
            "no pagination",
            "time filter",
            "precompiled",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertIn("ZHIHU_ADAPTER", router)
        self.assertIn('"hot"', router)

    def test_frontmatter_does_not_trigger_on_known_url_reading(self):
        text = SKILL.read_text(encoding="utf-8")
        frontmatter = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL).group(1)
        self.assertNotIn("URL 正文提取", frontmatter)
        self.assertIn("不用于读取或下载用户直接给出的已知 URL", frontmatter)

    def test_generic_extract_mode_is_removed(self):
        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        self.assertNotIn('choices=("search", "batch", "extract")', router)
        self.assertIn("verify-candidate", router)

    def test_firecrawl_is_explicit_bounded_and_not_default_search(self):
        skill = SKILL.read_text(encoding="utf-8")
        routes = (ROOT / "references" / "routes.md").read_text(encoding="utf-8")
        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        required = (
            "--mode site-map",
            "--verify-backend firecrawl",
            "最多 100",
            "storeInCache=false",
            "skipTlsVerification=false",
            "不等于绝对零数据保留",
        )
        combined = f"{skill}\n{routes}"
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertIn("FIRECRAWL_ADAPTER", router)
        self.assertIn('"backend": "anysearch"', router)

    def test_weibo_route_is_readonly_auto_bounded_and_candidate_only(self):
        skill = SKILL.read_text(encoding="utf-8")
        routes = (ROOT / "references" / "routes.md").read_text(encoding="utf-8")
        schema = (ROOT / "references" / "candidate-schema.md").read_text(
            encoding="utf-8"
        )
        router = (ROOT / "scripts" / "route_search.py").read_text(encoding="utf-8")
        adapter = (ROOT / "scripts" / "weibo_adapter.py").read_text(encoding="utf-8")
        combined = "\n".join((skill, routes, schema))
        for phrase in (
            "weibo-readonly-auto",
            "weibo-public-anonymous",
            "weibo-opencli-readonly",
            "weibo_adapter.py",
            "临时匿名访客会话",
            "最多 3 页",
            "最多 20",
            "只读",
            "candidate",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertIn("WEIBO_ADAPTER", router)
        self.assertIn("RejectRedirects", adapter)
        self.assertNotIn("api/comments/show", adapter)
        self.assertNotIn("CookieJar", adapter)


if __name__ == "__main__":
    unittest.main()
