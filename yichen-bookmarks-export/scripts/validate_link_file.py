#!/usr/bin/env python3
"""Validate exported bookmark URL files without echoing private URLs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


XHS_PATTERNS = (
    re.compile(r"^/user/profile/[0-9a-f]{24}/[0-9a-f]{24}$", re.I),
    re.compile(r"^/explore/[0-9a-f]{24}$", re.I),
    re.compile(r"^/discovery/item/[0-9a-f]{24}$", re.I),
)
DOUYIN_PATTERN = re.compile(r"^/(video|note)/\d+$", re.I)
X_PATTERN = re.compile(r"^/[^/]+/status/\d+$", re.I)


def valid_url(platform: str, raw: str) -> bool:
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.rstrip("/")
    if platform == "xiaohongshu":
        return host in {"xiaohongshu.com", "www.xiaohongshu.com"} and any(pattern.match(path) for pattern in XHS_PATTERNS)
    if platform == "douyin":
        return host in {"douyin.com", "www.douyin.com"} and bool(DOUYIN_PATTERN.match(path))
    return host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and bool(X_PATTERN.match(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a bookmark link export")
    parser.add_argument("--platform", required=True, choices=("xiaohongshu", "douyin", "x"))
    parser.add_argument("file", type=Path)
    args = parser.parse_args()

    if not args.file.is_file():
        parser.error(f"file not found: {args.file}")
    lines = args.file.read_text(encoding="utf-8").splitlines()
    nonblank = [(number, line.strip()) for number, line in enumerate(lines, 1) if line.strip()]
    urls = [line for _, line in nonblank]
    duplicates = len(urls) - len(set(urls))
    invalid_lines = [number for number, url in nonblank if not valid_url(args.platform, url)]
    summary = {
        "platform": args.platform,
        "file": str(args.file),
        "valid": len(urls) - len(invalid_lines),
        "total_nonblank": len(urls),
        "blank_lines": len(lines) - len(nonblank),
        "duplicates": duplicates,
        "invalid_line_numbers": invalid_lines,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not invalid_lines and duplicates == 0 and urls else 1


if __name__ == "__main__":
    raise SystemExit(main())
