# WeChat MP Batch Exporter

Batch-oriented workflow for WeChat Official Account article archives.

It helps an agent:

- Download known `mp.weixin.qq.com` article URLs as Markdown, JSON, text, or HTML.
- Export a public account's history list through `wechat-article-exporter`.
- Distinguish `publish_groups`, `expanded_url_items`, and `original_articles`.
- Prepare enhanced archives that can include read counts, likes, shares, comments, and replies when fresh user-owned credentials are available.

## Privacy Boundary

This public skill does not include credentials, cookies, QR secrets, article archives, downloaded bodies, local account data, or private paths.

The scripts are intentionally conservative:

- `doctor.py` is read-only.
- `download_urls.py` only downloads known public article URLs through the configured exporter API.
- `start_wxdown_service.py` starts a local helper only when explicitly run and does not change system proxy settings.
- Any QR login, certificate trust, proxy change, or WeChat desktop action must be confirmed and performed by the user.

Never commit output archives, `credentials.json`, cookies, auth-key values, `pass_ticket`, `uin`, tokens, QR login secrets, or private account data.

## Local Setup

For known URL body downloads, no local upstream checkout is required:

```bash
python3 scripts/download_urls.py "https://mp.weixin.qq.com/s/..."
```

For account history, install or self-host `wechat-article/wechat-article-exporter`, then point the skill at it:

```bash
export WECHAT_ARTICLE_EXPORTER_DIR=/path/to/wechat-article-exporter
python3 scripts/doctor.py --exporter-path "$WECHAT_ARTICLE_EXPORTER_DIR" --check-network
```

For read counts and comments, install `wechat-article/wxdown-service` and start it only after the user confirms the credential-capture workflow:

```bash
export WXDOWN_SERVICE_DIR=/path/to/wxdown-service
python3 scripts/start_wxdown_service.py --wxdown-dir "$WXDOWN_SERVICE_DIR" --dry-run
```

## Output

History analysis writes:

- `history.summary.json`
- `history.summary.md`
- `history.dedup.json`
- `history.dedup.csv`
- `urls.all.txt`
- `history.original.json`
- `history.original.csv`
- `urls.original.txt`

Known URL downloads write:

- `index.csv`
- `errors.json`
- `articles/*`

## Safety Notes

- Do not operate WeChat UI from the agent.
- Do not bypass login, paywalls, deleted articles, private content, or platform permission checks.
- Downloaded article content belongs to the original authors or rights holders; do not republish or redistribute without permission.
- Do not guarantee read/comment metrics without fresh user-owned credentials.
- Do not leave system proxy settings changed after a credential-capture workflow.
