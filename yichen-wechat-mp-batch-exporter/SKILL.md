---
name: wechat-mp-batch-exporter
description: 批量下载微信公众号文章正文、历史文章列表、原创文章筛选、历史计数口径、阅读量、点赞/转发等指标、评论和评论回复。Use when the user asks to batch fetch mp.weixin.qq.com articles, export WeChat public-account history, distinguish publish groups vs expanded article URLs vs original articles, use wechat-article-exporter, use wxdown-service credentials, collect read/comment metrics, or create an archive for Obsidian/Feishu/local analysis. Do not use for ordinary one-off article summarization unless batch/enhanced data is requested.
---

# WeChat MP Batch Exporter

## Core Rule

Never operate the user's WeChat UI. Do not publish, delete, mass-send, follow, unfollow, send messages, or click inside WeChat. For any workflow requiring WeChat desktop, tell the user exactly what to do and wait for confirmation.

Never print raw cookies, auth-key, token, pass_ticket, key, uin, credentials JSON, or QR login secrets in chat or saved reports.

Downloaded article content belongs to the original authors or rights holders. Use exports only within the user's lawful/private-use scope unless the user confirms they have permission to republish or redistribute.

## First Step

Run the local doctor before choosing a workflow:

```bash
python3 {baseDir}/scripts/doctor.py
```

Use `--check-network` only when the task needs the public exporter API or online download endpoint.

## Decision Tree

- User provides known article URLs and only needs正文/Markdown: use `scripts/download_urls.py`; no login or WeChat action is required.
- User wants a public account's历史文章列表 or latest N articles: use exporter mode from `wechat-article-exporter`; this requires a user-owned WeChat Official Account backend login/auth-key.
- User needs阅读量、点赞、转发、评论、评论回复: use `wxdown-service` credentials flow first, then export enhanced fields from `wechat-article-exporter`.
- User says“不登录”“代理模式” or exporter mode fails: use the proxy/history fallback only after explicit confirmation; read `references/manual-gates.md` first.

For simple single-URL extraction without batch/enhanced needs, prefer the existing `$wechat-article` skill.

## Count Discipline

Never report a public account total as just “N 篇文章” until the count scope is clear.

After any history sync or imported history JSON, run:

```bash
python3 {baseDir}/scripts/analyze_history.py --history-json /path/to/history.dedup.json
python3 {baseDir}/scripts/analyze_history.py --chunk-dir /path/to/chunks --output-dir /path/to/output
```

Use these labels in user-facing answers:

- `publish_groups`: unique `msgid` values; roughly one WeChat publish/message group.
- `expanded_url_items`: every unique article URL after expanding multi-article messages.
- `original_articles`: frontend-style original article count, using `copyright_type=1`, `copyright_stat=1`, and `is_deleted=false`.

If counts disagree with what the user sees in WeChat, explain the scope difference first and point to the generated `history.summary.json` / `history.summary.md`.

## Known-URL Body Download

Use this path for pasted URLs, `.txt`, `.csv`, or `.json` URL lists:

```bash
python3 {baseDir}/scripts/download_urls.py --file /path/to/urls.txt --format markdown
python3 {baseDir}/scripts/download_urls.py "https://mp.weixin.qq.com/s/..."
```

Report only: success count, failure count, failed URLs, output directory, and `index.csv`.

Default output:

```text
~/Downloads/wechat-mp-batch/<run-id>/
|-- index.csv
|-- errors.json
`-- articles/
    `-- 001-<safe-title>.md
```

## History And Enhanced Export

Read `references/exporter-workflow.md` before running exporter/history/enhanced-data tasks.

Start the local credential helper with:

```bash
python3 {baseDir}/scripts/start_wxdown_service.py
```

Use the mature upstream stack:

- `wechat-article/wechat-article-exporter` for account search, article history, body download, and multi-format export.
- `wechat-article/wxdown-service` for user-owned credential capture needed by read/comment metrics.

Local source paths are environment-specific. Prefer environment variables or explicit script flags:

```bash
export WECHAT_ARTICLE_EXPORTER_DIR=/path/to/wechat-article-exporter
export WXDOWN_SERVICE_DIR=/path/to/wxdown-service
python3 {baseDir}/scripts/doctor.py --exporter-path "$WECHAT_ARTICLE_EXPORTER_DIR" --wxdown-path "$WXDOWN_SERVICE_DIR"
python3 {baseDir}/scripts/start_wxdown_service.py --wxdown-dir "$WXDOWN_SERVICE_DIR"
```

If using the public exporter, default base URL is:

```text
https://down.mptext.top
```

## Manual Gates

Read `references/manual-gates.md` whenever the task involves login, credentials, comments, read counts, proxy, certificate trust, or WeChat desktop.

These actions always require explicit user confirmation:

- Scanning a QR code and selecting the user's Official Account or service account.
- Installing or trusting a mitmproxy certificate.
- Enabling or changing macOS system proxy settings.
- Asking the user to open an article/history page inside WeChat desktop and scroll.
- Using a pasted auth-key or credentials file.

## Outputs

Read `references/output-schema.md` when building an archive or merging exporter results into another system.

Preferred enhanced archive fields:

```text
account_name, fakeid, title, url, publish_time, author, digest, cover_url,
body_markdown_path, html_path, image_dir,
read_count, like_count, share_count, favorite_count, comment_count,
comments_path, comment_replies_path, fetch_mode, credential_status, exported_at
```

History analysis outputs should include:

```text
history.summary.json, history.summary.md,
history.dedup.json, history.dedup.csv, urls.all.txt,
history.original.json, history.original.csv, urls.original.txt
```

## What Cannot Be Done Automatically

- Do not bypass login, deleted content, paywalls, private articles, or platform permission checks.
- Do not guarantee read/comment metrics without fresh user-owned credentials.
- Do not operate WeChat UI or replace the user's required WeChat desktop actions.
- Do not promise comments when the article has comments disabled or hidden.
- Do not silently install system certificates, change proxies, or leave proxy settings enabled.
