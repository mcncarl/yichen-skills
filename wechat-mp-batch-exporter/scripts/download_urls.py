#!/usr/bin/env python3
"""Batch-download known WeChat article URLs through the public exporter API."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable


URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s\"'<>]+", re.I)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def make_run_id() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha256(f"{stamp}-{time.time()}".encode()).hexdigest()[:8]
    return f"{stamp}-{suffix}"


def safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:100] or fallback


def extract_urls_from_text(text: str) -> list[str]:
    return [m.group(0).rstrip(")，。；,;") for m in URL_RE.finditer(text)]


def read_urls(files: Iterable[str], inline: Iterable[str]) -> list[str]:
    urls: list[str] = []
    for item in inline:
        urls.extend(extract_urls_from_text(item))
    for file_value in files:
        path = Path(file_value).expanduser()
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    text = "\n".join(str(x) for x in data)
                elif isinstance(data, dict):
                    text = json.dumps(data, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        urls.extend(extract_urls_from_text(text))
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def title_from_body(body: str, seq: int) -> str:
    for line in body.splitlines()[:30]:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    match = re.search(r'"title"\s*:\s*"([^"]+)"', body)
    if match:
        return match.group(1)
    return f"article-{seq:03d}"


def fetch_article(api_base: str, url: str, fmt: str, timeout: int) -> str:
    query = urllib.parse.urlencode({"url": url, "format": fmt})
    endpoint = api_base.rstrip("/") + "/api/public/v1/download?" + query
    req = urllib.request.Request(endpoint, headers={"User-Agent": "wechat-mp-batch-exporter/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download known mp.weixin.qq.com article URLs")
    parser.add_argument("urls", nargs="*", help="Article URLs or text containing URLs")
    parser.add_argument("--file", action="append", default=[], help="File containing URLs; may be repeated")
    parser.add_argument("--output-dir", default="", help="Output directory; defaults to ~/Downloads/wechat-mp-batch/<run-id>")
    parser.add_argument("--format", choices=["markdown", "json", "text", "html"], default="markdown")
    parser.add_argument("--api-base", default="https://down.mptext.top")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--sleep", type=float, default=0.8, help="Delay between requests")
    args = parser.parse_args()

    urls = read_urls(args.file, args.urls)
    if not urls:
        print(json.dumps({"ok": False, "error": "no mp.weixin.qq.com URLs found"}, ensure_ascii=False, indent=2))
        return 2

    run_id = make_run_id()
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else Path.home() / "Downloads" / "wechat-mp-batch" / run_id
    article_dir = out_dir / "articles"
    article_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    suffix = {"markdown": ".md", "json": ".json", "text": ".txt", "html": ".html"}[args.format]

    for index, url in enumerate(urls, 1):
        seq = f"{index:03d}"
        try:
            body = fetch_article(args.api_base, url, args.format, args.timeout)
            title = title_from_body(body, index)
            rel_path = Path("articles") / f"{seq}-{safe_name(title, f'article-{seq}')}{suffix}"
            target = out_dir / rel_path
            target.write_text(body, encoding="utf-8")
            rows.append(
                {
                    "seq": seq,
                    "title": title,
                    "source_url": url,
                    "format": args.format,
                    "path": str(rel_path),
                    "status": "success",
                    "error": "",
                    "downloaded_at": now_iso(),
                }
            )
        except Exception as exc:
            error = str(exc)
            rows.append(
                {
                    "seq": seq,
                    "title": "",
                    "source_url": url,
                    "format": args.format,
                    "path": "",
                    "status": "failed",
                    "error": error,
                    "downloaded_at": now_iso(),
                }
            )
            errors.append({"seq": seq, "source_url": url, "error": error})
        if args.sleep > 0 and index < len(urls):
            time.sleep(args.sleep)

    index_path = out_dir / "index.csv"
    with index_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["seq", "title", "source_url", "format", "path", "status", "error", "downloaded_at"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    errors_path = out_dir / "errors.json"
    errors_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "ok": not errors,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "index_csv": str(index_path),
        "errors_json": str(errors_path),
        "success_count": sum(1 for row in rows if row["status"] == "success"),
        "failure_count": len(errors),
        "failed_urls": [item["source_url"] for item in errors],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
