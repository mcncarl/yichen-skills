# Exporter Workflow

## 1. Known URL Body Download

Use `scripts/download_urls.py` for article URLs already provided by the user. This path calls the public exporter download API and writes Markdown or JSON outputs locally. It does not fetch read counts or comments.

```bash
python3 {baseDir}/scripts/download_urls.py --file urls.txt --format markdown
```

If the user needs images, exact HTML preservation, DOCX, Excel, or PDF, use `wechat-article-exporter` instead of the lightweight URL script.

## 2. Exporter Mode For History Lists

Use this mode when the user gives a public-account name, wants latest N articles, or wants to manage many accounts.

Preferred source:

```text
https://down.mptext.top
```

Local source path, if self-hosting or using a local checkout:

```text
$WECHAT_ARTICLE_EXPORTER_DIR or /path/to/wechat-article-exporter
```

Current upstream project:

```text
https://github.com/wechat-article/wechat-article-exporter
```

The exporter uses the WeChat Official Account backend search/list APIs through its own proxy endpoints. A valid user-owned auth-key is needed for account search and article list sync.

Typical flow:

1. Confirm the user has a WeChat Official Account or service account available for login.
2. Open the exporter site or local exporter.
3. Ask the user to scan the QR code and choose the correct public account/service account.
4. Search the target public account.
5. Sync article list.
6. Run `scripts/analyze_history.py` on the synced/exported history before reporting totals.
7. Show scoped counts, article titles, and publish dates in chat before downloading.
8. Let the user choose by latest count, date range, title keyword, original-only, or explicit rows.
9. Export body data.

Do not print auth-key. If the user manually provides one, store it only in a local private runtime file or macOS Keychain when a script supports it.

### Count Scopes

Use explicit count scopes for every account-history answer:

- `publish_groups`: unique `msgid` values, roughly one WeChat publish/message group.
- `expanded_url_items`: unique article URLs after expanding multi-article messages. This can be much larger than the WeChat frontend count.
- `original_articles`: original-article count, defined as `copyright_type=1`, `copyright_stat=1`, and `is_deleted=false`.

Example count shape: many `publish_groups` can expand into a larger number of unique article URLs, and only a subset may match the original-article filter. Treat concrete counts as run-specific evidence, never as a permanent account fact.

## 3. Enhanced Metrics And Comments

Use this mode when the user explicitly asks for阅读量、点赞、转发、收藏、评论、评论回复.

Required helper:

```text
$WXDOWN_SERVICE_DIR or /path/to/wxdown-service
```

Current upstream project:

```text
https://github.com/wechat-article/wxdown-service
```

`wxdown-service` starts a local mitmproxy service and exposes a WSS endpoint, commonly shaped like:

```text
wss://127.0.0.1:65001
```

The user must trust the mitmproxy CA certificate and open relevant articles in the proper WeChat browsing context so the helper can capture user-owned article credentials. The service stores credentials locally and pushes fresh credentials to the exporter.

After credentials are available:

1. Configure the WSS endpoint in exporter, or use the exporter's credential detection workflow.
2. Load/sync the target account and target article URLs.
3. Run metadata/comment download inside exporter.
4. Export the enhanced dataset.
5. Save comments and replies as JSON/CSV sidecars; do not paste raw comment bodies into chat unless the user explicitly asks for a short excerpt or analysis.

## 4. Local Exporter Development

Only start local exporter if the public site is insufficient or the user requests local/private deployment.

Known requirements from upstream:

```bash
corepack enable
corepack prepare yarn@1.22.22 --activate
yarn
yarn dev
```

Node >= 22 is required by the current upstream. The local snapshot may be older; check `package.json` before installing.

## 5. Validation

Validate every run with:

- output directory exists
- `history.summary.json` exists and reports `publish_groups`, `expanded_url_items`, and `original_articles`
- `index.csv` or exporter table exists
- selected URL count matches downloaded body count
- enhanced run states whether credentials were fresh, missing, or expired
- failed URLs are listed separately
- system proxy was restored if proxy mode was used
