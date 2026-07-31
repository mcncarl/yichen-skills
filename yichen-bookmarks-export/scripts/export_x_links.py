#!/usr/bin/env python3
"""Export all locally indexed Field Theory bookmark URLs without printing private content."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def run_ft(*args: str) -> str:
    completed = subprocess.run(
        ["ft", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def bookmark_url(item: dict) -> str | None:
    url = item.get("url")
    if isinstance(url, str) and url.startswith("https://x.com/") and "/status/" in url:
        return url.split("?", 1)[0]
    tweet_id = str(item.get("tweetId") or item.get("id") or "").strip()
    author = str(item.get("authorHandle") or "_").strip().lstrip("@") or "_"
    if tweet_id.isdigit():
        return f"https://x.com/{author}/status/{tweet_id}"
    return None


def collect_urls(page_size: int, max_items: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    offset = 0
    while offset < max_items:
        limit = min(page_size, max_items - offset)
        payload = json.loads(run_ft("list", "--limit", str(limit), "--offset", str(offset), "--json"))
        if not isinstance(payload, list):
            raise RuntimeError("ft list --json did not return a JSON array")
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = bookmark_url(item)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        if len(payload) < limit:
            break
        offset += limit
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Field Theory X bookmark URLs")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--max-items", type=int, default=100000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if shutil.which("ft") is None:
        parser.error("ft is not installed or not on PATH")
    version = run_ft("--version").strip()
    if "graphql-only" not in version:
        parser.error(f"refusing non-GraphQL-only Field Theory version: {version}")
    if args.page_size < 1 or args.page_size > 1000:
        parser.error("--page-size must be between 1 and 1000")
    if args.max_items < 1:
        parser.error("--max-items must be positive")
    if args.output.exists() and not args.overwrite:
        parser.error(f"output already exists: {args.output}")

    urls = collect_urls(args.page_size, args.max_items)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if args.overwrite else "x"
    with args.output.open(mode, encoding="utf-8") as handle:
        handle.write("\n".join(urls))
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "count": len(urls), "fieldtheory": version}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(json.dumps({"error": "ft command failed", "returncode": error.returncode}), file=sys.stderr)
        raise SystemExit(1)
