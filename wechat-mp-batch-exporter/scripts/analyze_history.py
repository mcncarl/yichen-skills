#!/usr/bin/env python3
"""Analyze and normalize WeChat public-account history exports."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any


CSV_FIELDS = [
    "row",
    "account_name",
    "account_alias",
    "fakeid",
    "aid",
    "title",
    "url",
    "digest",
    "author",
    "publish_time_iso",
    "update_time_iso",
    "create_time",
    "update_time",
    "msgid",
    "appmsgid",
    "itemidx",
    "comment_id",
    "is_deleted",
    "is_original",
    "copyright_type",
    "copyright_stat",
    "cover_url",
    "_chunk_file",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def raw_value(item: dict[str, Any], key: str) -> Any:
    raw = item.get("raw")
    if isinstance(raw, dict):
        return raw.get(key)
    return None


def is_original(item: dict[str, Any]) -> bool:
    return (
        raw_value(item, "copyright_type") == 1
        and raw_value(item, "copyright_stat") == 1
        and not bool(item.get("is_deleted"))
    )


def iso_time(value: Any) -> str:
    if not value:
        return ""
    try:
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp = stamp / 1000
        return dt.datetime.fromtimestamp(stamp, tz=dt.timezone.utc).astimezone().isoformat()
    except Exception:
        return ""


def load_records(history_json: Path | None, chunk_dir: Path | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if history_json:
        data = read_json(history_json)
        if not isinstance(data, list):
            raise ValueError(f"{history_json} must contain a JSON array")
        records.extend(dict(item) for item in data)

    if chunk_dir:
        chunk_paths = sorted(
            {
                *chunk_dir.glob("history-chunk-*.json"),
                *chunk_dir.glob("*-history-chunk-*.json"),
            }
        )
        for path in chunk_paths:
            data = read_json(path)
            if not isinstance(data, list):
                continue
            for item in data:
                row = dict(item)
                row.setdefault("_chunk_file", path.name)
                records.append(row)

    if not records:
        raise ValueError("no history records found")
    return records


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in records:
        key = item.get("url") or item.get("aid")
        if not key:
            key = f"{item.get('appmsgid')}:{item.get('itemidx')}:{item.get('title')}"
        if key in seen:
            continue
        seen.add(str(key))
        deduped.append(item)

    deduped.sort(key=lambda x: (int(x.get("create_time") or 0), int(x.get("itemidx") or 0)), reverse=True)
    for index, item in enumerate(deduped, 1):
        item["row"] = index
        item["publish_time_iso"] = item.get("publish_time_iso") or iso_time(item.get("create_time"))
        item["update_time_iso"] = item.get("update_time_iso") or iso_time(item.get("update_time"))
        item["is_original"] = is_original(item)
        item["copyright_type"] = raw_value(item, "copyright_type")
        item["copyright_stat"] = raw_value(item, "copyright_stat")
    return deduped


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def counter_to_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): value for key, value in counter.most_common()}


def build_summary(records: list[dict[str, Any]], deduped: list[dict[str, Any]]) -> dict[str, Any]:
    original = [item for item in deduped if item.get("is_original")]
    publish_group_ids = {item.get("msgid") for item in deduped if item.get("msgid") is not None}
    headline_count = sum(1 for item in deduped if item.get("itemidx") == 1)
    publish_groups = len(publish_group_ids) or headline_count

    return {
        "raw_records": len(records),
        "expanded_url_items": len(deduped),
        "unique_urls": len({item.get("url") for item in deduped if item.get("url")}),
        "publish_groups": publish_groups,
        "headline_items": headline_count,
        "original_articles": len(original),
        "not_deleted_items": sum(1 for item in deduped if not item.get("is_deleted")),
        "deleted_items": sum(1 for item in deduped if item.get("is_deleted")),
        "duplicate_records_removed": len(records) - len(deduped),
        "first_publish_time": deduped[0].get("publish_time_iso") if deduped else "",
        "last_publish_time": deduped[-1].get("publish_time_iso") if deduped else "",
        "itemidx_counts": counter_to_dict(Counter(item.get("itemidx") for item in deduped)),
        "copyright_type_counts": counter_to_dict(Counter(raw_value(item, "copyright_type") for item in deduped)),
        "copyright_stat_counts": counter_to_dict(Counter(raw_value(item, "copyright_stat") for item in deduped)),
        "counting_notes": [
            "expanded_url_items counts every unique mp.weixin.qq.com article URL after expanding multi-article messages.",
            "publish_groups counts unique msgid values, roughly one WeChat publish/message group.",
            "original_articles uses copyright_type=1, copyright_stat=1, and is_deleted=false.",
            "Do not call expanded_url_items 'original articles' or 'pushes'.",
        ],
    }


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    text = "\n".join(
        [
            "# WeChat History Count Summary",
            "",
            f"- Raw records: {summary['raw_records']}",
            f"- Expanded URL items: {summary['expanded_url_items']}",
            f"- Unique URLs: {summary['unique_urls']}",
            f"- Publish groups: {summary['publish_groups']}",
            f"- Headline items: {summary['headline_items']}",
            f"- Original articles: {summary['original_articles']}",
            f"- Deleted items: {summary['deleted_items']}",
            f"- First publish time: {summary['first_publish_time']}",
            f"- Last publish time: {summary['last_publish_time']}",
            "",
            "## Counting Notes",
            "",
            "- `expanded_url_items`: every unique article URL after expanding multi-article messages.",
            "- `publish_groups`: unique `msgid` values, roughly one WeChat publish/message group.",
            "- `original_articles`: `copyright_type=1`, `copyright_stat=1`, and `is_deleted=false`.",
            "- Never compare `expanded_url_items` directly with a front-end original-article count.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze WeChat account history count scopes")
    parser.add_argument("--history-json", help="Merged/deduped history JSON array")
    parser.add_argument("--chunk-dir", help="Directory containing xzy-history-chunk-*.json files")
    parser.add_argument("--output-dir", help="Directory for normalized outputs; defaults next to input")
    parser.add_argument("--prefix", default="history", help="Output file prefix")
    args = parser.parse_args()

    history_json = Path(args.history_json).expanduser() if args.history_json else None
    chunk_dir = Path(args.chunk_dir).expanduser() if args.chunk_dir else None
    if not history_json and not chunk_dir:
        parser.error("provide --history-json or --chunk-dir")

    records = load_records(history_json, chunk_dir)
    deduped = dedupe_records(records)
    original = [item for item in deduped if item.get("is_original")]

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
    elif history_json:
        output_dir = history_json.parent
    else:
        output_dir = chunk_dir or Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = args.prefix
    all_json = output_dir / f"{prefix}.dedup.json"
    all_csv = output_dir / f"{prefix}.dedup.csv"
    all_urls = output_dir / "urls.all.txt"
    original_json = output_dir / f"{prefix}.original.json"
    original_csv = output_dir / f"{prefix}.original.csv"
    original_urls = output_dir / "urls.original.txt"
    summary_json = output_dir / f"{prefix}.summary.json"
    summary_md = output_dir / f"{prefix}.summary.md"

    all_json.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    original_json.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(all_csv, deduped)
    write_csv(original_csv, original)
    all_urls.write_text("\n".join(item.get("url", "") for item in deduped if item.get("url")) + "\n", encoding="utf-8")
    original_urls.write_text("\n".join(item.get("url", "") for item in original if item.get("url")) + "\n", encoding="utf-8")

    summary = build_summary(records, deduped)
    summary["files"] = {
        "dedup_json": str(all_json),
        "dedup_csv": str(all_csv),
        "all_urls": str(all_urls),
        "original_json": str(original_json),
        "original_csv": str(original_csv),
        "original_urls": str(original_urls),
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_summary(summary_md, summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
