"""Planner capabilities that prevent silent query loss.

Native multi-query search is currently implemented only by X, AI HOT and web.
Other native backends either require one query or expose explicit batch semantics.
"""
SINGLE_QUERY_PLATFORMS = frozenset({
    "github", "wechat", "xiaohongshu", "douyin", "toutiao", "bilibili",
    "youtube", "xiaoyuzhou",
})
