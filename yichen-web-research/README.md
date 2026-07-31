# Yichen Web Research

`yichen-web-research` is the top-level router for a five-Skill research family:

1. `yichen-unified-search` — public web and platform discovery
2. `yichen-content-archive` — known-link reading, download, and archiving
3. `yichen-bookmarks-export` — explicitly authorized private bookmark export
4. `yichen-asr` — Step/Doubao ASR routing for existing local media
5. `yichen-web-research` — multi-stage orchestration across the four children

Install all five directories together. The router does not duplicate the child
implementations and is intentionally unable to complete their work when a child
Skill is missing.

## Optional backends

The family can use capabilities that are not bundled here:

- AnySearch for general, batch, and vertical public search
- `gh`, `yt-dlp`, `bili`, OpenCLI, Grok CLI, and `xreach`
- the `yichen-grok-consult` plugin for Grok-first native X search, with anonymous
  FxTwitter fallback only after explicit Grok account-quota exhaustion
- `yichen-social-bookmarks-exporter` and `yichen-wechat-mp-batch-exporter`;
  Xiaohongshu and Douyin known-link fetchers are bundled in `yichen-content-archive`
- `yichen-volc-asr`, `ffmpeg`, and an optional compatible Step ASR executor
- a loopback-only `wechat-article-exporter` for exact public-account containers

Missing optional backends reduce coverage; they do not relax authorization
rules or trigger automatic installation.

Known public X status and Article URLs are handled by the bundled
`yichen-content-archive/scripts/x_known_url.py` adapter. It uses anonymous
FxTwitter first, adds Jina only when needed, and returns OpenCLI/xreach merely
as authorization-gated fallback plans.

## Portable configuration

The public version contains no personal absolute paths, App IDs, tokens,
cookies, proxy credentials, or fixed Keychain items. Configure only the
backends you use:

| Variable | Purpose |
|---|---|
| `YICHEN_SKILLS_ROOT` | Override the directory containing the sibling Skills |
| `ANYSEARCH_RUNTIME_CONFIG` | Override the AnySearch `runtime.conf` path |
| `OPENCLI_HOME` | Override the OpenCLI state directory |
| `YICHEN_XIAOYUZHOU_CREDENTIAL_FILE` | Override the Xiaoyuzhou OpenCLI credential-file location |
| `YICHEN_STEP_ASR_SCRIPT` | Path to an independently installed Step ASR executor |
| `YICHEN_DOUBAO_ASR_SCRIPT` | Override the bundled `yichen-volc-asr` executor path |
| `VOLC_ASR_TRIAL_APP_ID` / `VOLC_ASR_PAID_APP_ID` | User-owned Volcengine application IDs |
| `VOLC_ASR_TRIAL_TOKEN` / `VOLC_ASR_PAID_TOKEN` | User-owned Volcengine tokens |
| `WECHAT_ARTICLE_EXPORTER_KV` | Local exporter state directory |
| `GROK_CLI` | Override the Grok executable path |
| `YICHEN_GROK_CONSULT_ROOT` | Optional local source path used only by the doctor |
| `YICHEN_GROK_CONSULT_ENABLED=1` | Optional doctor hint that the plugin is enabled |

Never commit the values of credential variables or local state files.

## Safety model

- Search never automatically turns into download or archive.
- Social-platform actions are read-only.
- Chrome/account-session reads require authorization for the exact current task.
- WeChat desktop or mobile UI is never controlled.
- Private bookmark authorization does not transfer to media download.
- An ASR job already submitted to one provider is never silently resubmitted to
  another provider.
- Existing artifacts are not overwritten or deleted by default.

The Xiaoyuzhou helper accepts only HTTPS episode pages on
`xiaoyuzhoufm.com` and audio on `xyzcdn.net`. The WeChat helper is fixed to the
loopback exporter at `127.0.0.1`.

## Validation

From the repository root:

```bash
python3 yichen-web-research/scripts/validate_family.py
python3 yichen-web-research/scripts/validate_family.py --doctor
```

The first command is fully offline. `--doctor` performs read-only local
availability checks and may invoke installed CLI help/auth-status commands; it
does not authorize a private read or call an ASR billing endpoint.
