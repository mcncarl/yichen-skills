#!/usr/bin/env python3
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
ROUTE_REFERENCE = (ROOT / "references" / "platform-routes.md").read_text(
    encoding="utf-8"
)
ROUTES = json.loads((ROOT / "tests" / "routes.json").read_text(encoding="utf-8"))


class ContentArchiveContractTest(unittest.TestCase):
    def test_frontmatter_and_references(self):
        match = re.match(r"^---\n(.*?)\n---\n", SKILL, re.S)
        self.assertIsNotNone(match)
        keys = {
            line.split(":", 1)[0]
            for line in match.group(1).splitlines()
            if line and not line.startswith(" ")
        }
        self.assertEqual(keys, {"name", "description"})
        self.assertIn("name: yichen-content-archive", match.group(1))
        self.assertTrue((ROOT / "references" / "platform-routes.md").is_file())
        self.assertTrue((ROOT / "references" / "handoff-contract.md").is_file())
        self.assertTrue((ROOT / "references" / "xiaohongshu-bitable.md").is_file())

    def test_static_safety_gates(self):
        required = [
            "不得执行关键词搜索或开放式发现",
            "不得调用任何总路由",
            "不得再次调用 `$yichen-content-archive`",
            "不得自动读取私人收藏",
            "不得删除任何文件",
            "绝对不得操控微信客户端",
            "`known_collection`",
            "普通网页",
            "Twitter/X",
            "B站",
            "小宇宙",
            "Agent 禁止自动使用兼容 `--overwrite`",
            "`--resume-existing --output-dir",
            "同级新的 `<name>-resume-<run_id>`",
            "discovery_performed: false",
            "`xiaohongshu_fetch.py`",
            "`douyin_download.py`",
            "写入飞书多维表格",
        ]
        for marker in required:
            self.assertIn(marker, SKILL)
        scripts = {path.name for path in (ROOT / "scripts").glob("*.py")}
        self.assertEqual(
            scripts,
            {
                "wechat_mp_local.py",
                "xiaoyuzhou_stepfun.py",
                "xiaoyuzhou_opencli.py",
                "x_known_url.py",
                "xiaohongshu_fetch.py",
                "douyin_download.py",
            },
        )

    def test_legacy_social_fetcher_skills_are_retired(self):
        for name in (
            "douyin-fetcher",
            "xiaohongshu-fetch",
            "yichen-douyin-fetcher",
            "yichen-xiaohongshu-fetch",
        ):
            legacy = ROOT.parent / name
            self.assertFalse(legacy.exists() or legacy.is_symlink(), str(legacy))

    def test_route_fixtures_are_closed(self):
        allowed_skills = {
            "yichen-wechat-mp-batch-exporter",
        }
        allowed_backends = {
            "jina-reader",
            "web-reader",
            "exact-url-file",
            "yt-dlp",
            "bili-cli",
            "xiaoyuzhou-stepfun",
            "xiaoyuzhou-opencli+xiaoyuzhou-stepfun",
            "wechat-mp-local",
            "x-public-known-url",
            "xiaohongshu-known-url",
            "douyin-known-url",
        }
        backend_markers = {
            "jina-reader": ("Jina Reader",),
            "web-reader": ("Web Reader",),
            "exact-url-file": ("URL 文件",),
            "yt-dlp": ("yt-dlp",),
            "bili-cli": ("bili-cli",),
            "xiaoyuzhou-stepfun": ("xiaoyuzhou_stepfun.py",),
            "xiaoyuzhou-opencli+xiaoyuzhou-stepfun": (
                "xiaoyuzhou_opencli.py",
                "xiaoyuzhou_stepfun.py",
            ),
            "wechat-mp-local": ("wechat_mp_local.py",),
            "x-public-known-url": ("x_known_url.py",),
            "xiaohongshu-known-url": ("xiaohongshu_fetch.py",),
            "douyin-known-url": ("douyin_download.py",),
        }
        routable_decisions = {"route", "enumerate_then_route"}
        forbidden_branches = {
            "keyword-search",
            "channel",
            "recommend",
            "site-crawl",
            "cross-source-expand",
        }
        self.assertTrue(any(row["decision"] == "reject" for row in ROUTES))
        self.assertTrue(any(row["decision"] == "unsupported" for row in ROUTES))
        for row in ROUTES:
            if row["decision"] in routable_decisions:
                self.assertTrue(
                    ("route_skill" in row) ^ ("route_backend" in row),
                    row["case"],
                )
                if "route_skill" in row:
                    self.assertIn(row["route_skill"], allowed_skills)
                    self.assertIn(row["route_skill"], ROUTE_REFERENCE)
                else:
                    self.assertIn(row["route_backend"], allowed_backends)
                    for marker in backend_markers[row["route_backend"]]:
                        self.assertIn(marker, ROUTE_REFERENCE)
                self.assertNotIn(row["allowed_branch"], forbidden_branches)
            else:
                self.assertNotIn("route_skill", row)
                self.assertNotIn("route_backend", row)

    def test_known_collection_is_exact_and_bounded(self):
        collection_rows = [
            row for row in ROUTES if row["input_kind"] == "known_collection"
        ]
        self.assertGreaterEqual(len(collection_rows), 6)
        for row in collection_rows:
            if row["decision"] == "enumerate_then_route":
                self.assertEqual(row["container_scope"], "exact", row["case"])
        container_kinds = {
            row["container_kind"]
            for row in collection_rows
            if "container_kind" in row
        }
        self.assertTrue(
            {
                "url_file",
                "youtube_playlist_url",
                "bilibili_playlist_url",
                "episode_url_file",
                "xiaoyuzhou_podcast",
                "wechat_account_history",
            }.issubset(container_kinds)
        )

    def test_required_known_url_platforms_are_covered(self):
        routed_platforms = {
            row["platform"]
            for row in ROUTES
            if row["decision"] in {"route", "enumerate_then_route"}
        }
        self.assertTrue(
            {
                "web",
                "x",
                "xiaohongshu",
                "douyin",
                "wechat",
                "youtube",
                "bilibili",
                "xiaoyuzhou",
            }.issubset(routed_platforms)
        )
        rejected_actions = {
            row["action"] for row in ROUTES if row["decision"] == "reject"
        }
        self.assertTrue({"search", "crawl", "expand_similar"}.issubset(rejected_actions))


if __name__ == "__main__":
    unittest.main()
