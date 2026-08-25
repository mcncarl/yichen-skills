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

## Research modes

Single-stage search still routes directly to `yichen-unified-search`. Known-link
reading or archiving, private bookmark export, and existing-media transcription
continue to use their dedicated child Skills.

For requests that require both historical development and a current
cross-sectional comparison, `yichen-web-research` adds a bounded
horizontal-and-vertical research protocol:

1. Normalize a dated research brief and build a canonical plan before browsing.
2. Search by bounded longitudinal and cross-sectional workstreams, with explicit
   geography and language coverage.
3. Verify claims against opened original sources and record a claim-source
   ledger; search snippets and AI summaries remain discovery aids only.
4. Assemble the evidence offline, reject structurally invalid bundles, and stop
   valid but incomplete bundles with `blocking` when scope, coverage,
   contradictions, cross-axis synthesis, or scenario gates fail.

From the repository root, the deterministic helpers are:

```bash
python3 yichen-web-research/scripts/plan_hengzong_research.py --brief brief.json
python3 yichen-web-research/scripts/assemble_hengzong_evidence.py --bundle bundle.json
```

The complete contract is in
[`references/hengzong-research.md`](references/hengzong-research.md). Search does
not authorize persistence: the archive route is used only when the user
explicitly requests it and supplies a bounded scope.

### Provenance

This mode is based on, inspired by, and extends the `hv-analysis` Skill from
[KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills/tree/7a5c4934be4106ac740ffdb95280bb81b3f4b83c/hv-analysis),
authored by 数字生命卡兹克 and pinned at upstream commit
`7a5c4934be4106ac740ffdb95280bb81b3f4b83c`. The upstream MIT license is
preserved in
[`licenses/KKKKhazix-khazix-skills-LICENSE.txt`](../licenses/KKKKhazix-khazix-skills-LICENSE.txt),
with the adaptation record in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## Optional backends

The family can use capabilities that are not bundled here:

- AnySearch for general, batch, and vertical public search
- Firecrawl for explicit bounded site Map or current-candidate Scrape only; it is
  never an implicit search fallback and this release does not claim Crawl support
- a separately installed Zhihu Open Platform CLI-compatible runtime for public
  `search` and explicit `hot` discovery through the bundled allowlisted adapter;
  this repository does not independently verify that runtime's vendor provenance,
  and account and answer commands are excluded
- `gh`, `yt-dlp`, `bili`, OpenCLI, Grok CLI, and `xreach`
- the `yichen-grok-consult` plugin for Grok-first native X search, with anonymous
  FxTwitter fallback only after explicit Grok account-quota exhaustion
- `yichen-wechat-mp-batch-exporter`; private bookmark collectors are bundled in
  `yichen-bookmarks-export`, while Xiaohongshu and Douyin known-link fetchers are bundled in `yichen-content-archive`
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
| `YICHEN_ANYSEARCH_RUNTIME_CONF` | Override the AnySearch `runtime.conf` path |
| `OPENCLI_HOME` | Override the OpenCLI state directory |
| `YICHEN_XIAOYUZHOU_CREDENTIAL_FILE` | Override the Xiaoyuzhou OpenCLI credential-file location |
| `YICHEN_STEP_ASR_SCRIPT` | Path to an independently installed Step ASR executor |
| `FIRECRAWL_API_KEY` | Optional Firecrawl API key; the doctor checks only whether it is non-empty |
| `FIRECRAWL_KEY_FILE` | Optional private Firecrawl key file; the doctor checks metadata only and never reads it |
| `ZHIHU_CLI` | Override the separately installed Zhihu CLI-compatible executable path |
| `YICHEN_DOUBAO_ASR_SCRIPT` | Override the bundled `yichen-volc-asr` executor path |
| `VOLC_ASR_TRIAL_APP_ID` / `VOLC_ASR_PAID_APP_ID` | User-owned Volcengine application IDs |
| `VOLC_ASR_TRIAL_TOKEN` / `VOLC_ASR_PAID_TOKEN` | User-owned Volcengine tokens |
| `WECHAT_ARTICLE_EXPORTER_KV` | Local exporter state directory |
| `GROK_CLI` | Override the Grok executable path |
| `GROK_AUTH_FILE` | Override the Grok local authentication-status file path |
| `YICHEN_GROK_CONSULT_ROOT` | Optional local source path used only by the doctor |
| `YICHEN_GROK_CONSULT_ENABLED=1` | Optional doctor hint that the plugin is enabled |
| `CODEX_CONFIG` | Optional Codex config path used to detect an enabled Grok plugin when no explicit hint is set |

Never commit the values of credential variables or local state files.

## Safety model

- Search never automatically turns into download or archive.
- Social-platform actions are read-only.
- Bounded public read-only Xiaohongshu and Douyin search may reuse an existing
  Chrome session without per-run authorization: one keyword, serial execution,
  at least five seconds between requests, and at most 20/30 results respectively.
- Writes, private-scope reads, account changes, and verification-code handling
  still require explicit current-turn authorization.
- Firecrawl Map is limited to an explicit public origin and input path, with at
  most 100 same-origin in-path URLs; Map results remain unverified candidates.
- Firecrawl Scrape accepts only a current AnySearch candidate with a valid
  short-lived receipt; it is not a Crawl or archive route.
- The Zhihu doctor runs only offline metadata commands, removes environment
  credentials from the child process, and accepts Keychain-only authentication.
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
python3 -m unittest discover -s yichen-web-research/tests -p 'test_*.py'
python3 yichen-web-research/scripts/validate_family.py
python3 yichen-web-research/scripts/validate_family.py --doctor
```

The first command is fully offline. `--doctor` performs read-only local
availability checks and may invoke installed CLI help/auth-status commands; it
does not authorize a private read, read a Firecrawl key, issue a Zhihu search,
or call an ASR billing endpoint.
