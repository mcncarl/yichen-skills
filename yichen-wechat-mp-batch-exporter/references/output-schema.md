# Output Schema

## Lightweight URL Download

`scripts/download_urls.py` writes:

```text
<output-dir>/
|-- index.csv
|-- errors.json
`-- articles/
    |-- 001-title.md
    `-- 002-title.md
```

`index.csv` fields:

```text
seq,title,source_url,format,path,status,error,downloaded_at
```

`errors.json` contains an array of failed items:

```json
[
  {
    "seq": "002",
    "source_url": "https://mp.weixin.qq.com/s/...",
    "error": "..."
  }
]
```

## Enhanced Archive

When merging body, metrics, and comments from exporter, use one row per article:

```text
account_name
fakeid
title
url
publish_time
author
digest
cover_url
body_markdown_path
html_path
image_dir
read_count
like_count
share_count
favorite_count
comment_count
comments_path
comment_replies_path
fetch_mode
credential_status
exported_at
error
```

Recommended sidecars:

```text
comments/<article-id>.json
comment-replies/<article-id>.json
raw-exporter/
logs/
```

Do not store raw cookies, auth-key, pass_ticket, key, token, uin, or credentials JSON inside the output archive unless the user explicitly asks for a private debugging bundle and confirms the risk.

## History Count Analysis

Run `scripts/analyze_history.py` after syncing or importing a public-account history. It writes:

```text
history.summary.json
history.summary.md
history.dedup.json
history.dedup.csv
urls.all.txt
history.original.json
history.original.csv
urls.original.txt
```

Use these count fields:

```text
raw_records
expanded_url_items
unique_urls
publish_groups
headline_items
original_articles
not_deleted_items
deleted_items
duplicate_records_removed
first_publish_time
last_publish_time
itemidx_counts
copyright_type_counts
copyright_stat_counts
```

Definitions:

- `expanded_url_items`: unique article URLs after expanding multi-article messages.
- `publish_groups`: unique `msgid` values; roughly one WeChat publish/message group.
- `headline_items`: rows where `itemidx=1`.
- `original_articles`: rows with `copyright_type=1`, `copyright_stat=1`, and `is_deleted=false`.

When the user compares with WeChat frontend counts such as “原创文章”, compare against `original_articles`, not `expanded_url_items`.
