# Yichen Unified Search

English | [简体中文](./README.zh.md)

`yichen-unified-search` is a safety-first, read-only discovery router for the
public web and 11 named platform routes: GitHub, Zhihu, WeChat Official
Accounts, Weibo, Xiaohongshu, Douyin, Toutiao, X/Twitter, Bilibili, YouTube,
and Xiaoyuzhou.

Give it a topic, platform, time range, and result target. Its offline planner
selects one bounded route, makes the authorization state visible, and emits the
exact steps to run. Built-in adapters return reviewable candidate envelopes;
direct native-CLI steps remain raw unless an explicit downstream normalizer is
provided.

This Skill is for **finding candidates**, not for pretending search snippets
are facts. It does not download media, archive pages, read private collections,
operate WeChat, or perform social write actions. Known-URL reading, download,
and archiving belong to `yichen-content-archive`.

## Why use one router?

The same query should not be sent to every installed service. Unified Search
first decides what kind of discovery is actually needed, then discloses the
request only to the selected backend:

```text
topic + scope + platform + time window
  -> offline route_search.py plan
  -> one selected public or authenticated-public route
  -> bounded search
  -> candidate envelope or documented raw CLI output
  -> optional verification of a signed current-search candidate
```

The planner returns `status`, `authorization`, `route`, `steps`, and
`limitations`. It does not call a search service by itself.

## Support levels

The platform matrix uses three output labels:

- **Envelope** — a bundled adapter emits schema `1.0` with candidates, coverage,
  provenance, and sanitized errors.
- **Adapter required** — the planned backend output must pass through the named
  bundled adapter before it becomes an envelope. X/Grok uses this model.
- **Raw CLI step** — the planner safely selects and bounds an external CLI, but
  the direct result is not claimed to be normalized by this repository.

Missing optional CLIs reduce coverage. They never authorize installation,
private-data access, browser escalation, or a different fallback.

## Public web and AI discovery

| Intent | Selected route | Access | Output | Important boundary |
|---|---|---|---|---|
| Fresh AI news, releases, dynamics, or a daily digest | AI HOT via `aihot_search.py` | Anonymous public API | Envelope | Items cover at most seven days. Aggregated or AI-generated summaries are discovery text, not evidence. |
| General web, news, batches, `site:` queries, and vertical domains such as legal, academic, finance, or security | AnySearch via `anysearch_adapter.py` | Existing AnySearch runtime | Envelope | At most five expanded batch requests and ten candidates per query. A backend failure is reported, not silently rerouted. |
| Explicit public site or documentation link enumeration | Firecrawl Map via `firecrawl_adapter.py` | API key in a private environment/file | Envelope | At most 100 public, same-origin, in-path links. Map discovers links; it does not read page bodies or claim completeness. |
| Open one current AnySearch candidate | AnySearch Extract or explicit Firecrawl Scrape | Valid short-lived candidate receipt; Firecrawl also needs its key | Enriched envelope | Accepts the complete, unmodified candidate from the current search, never a bare URL. Opening a page still does not prove a claim. |

AI HOT is selected only for a query that combines an AI topic with clear
freshness intent, or when the user names AI HOT. Ordinary AI concepts,
tutorials, history, and longer research go to AnySearch. Firecrawl is never an
implicit fallback for keyword search.

## Platform coverage at a glance

| Platform | What this route discovers | Planned backend | Login state | Bound | Output |
|---|---|---|---|---|---|
| GitHub | Public repositories | `gh search repos --visibility public` | `gh` may use local credentials only to access the public API | 1–50 requested candidates | Raw CLI step |
| Zhihu | Public keyword results and an explicit hot list | Bundled `zhihu_adapter.py` → separately installed CLI-compatible runtime | Keychain-managed credential; public results are marked `authenticated_public` | Search: 10 per query; batch: 5 queries; hot: 30 | Envelope |
| WeChat Official Accounts | Cross-account public article candidates | `opencli weixin search` public route | Anonymous | Page 1; 1–50 requested candidates | Raw CLI step |
| Weibo | Public keyword post candidates | Bundled `weibo_adapter.py`; anonymous mobile route first, then one access-gate-only OpenCLI fallback | Anonymous first; existing Chrome session only after a qualifying access gate | 3 pages / 20 candidates; batch: 5 serial queries | Envelope |
| Xiaohongshu | Public note candidates by keyword | `opencli xiaohongshu search` | May reuse an existing Chrome session for this bounded public read-only route | One keyword at a time; 20 candidates; serial with a 5-second gap | Raw CLI step |
| Douyin | Public video/post candidates by keyword | `opencli douyin search` | May reuse an existing Chrome session for this bounded public read-only route | One keyword at a time; 30 candidates; serial with a 5-second gap | Raw CLI step |
| Toutiao | Current public, non-video search candidates | `opencli toutiao search` with a dedicated anonymous profile | Anonymous | One keyword; up to 50 candidates; 1–30 day control | Raw CLI step |
| X / Twitter | Public posts matched to one or many focused queries | Grok native `x_search`; narrowly gated fallbacks | Grok account OAuth first; later authenticated fallback is disabled by default | 20 per outer call; 1–7 days; Research: at most 40 calls and one gap-fill round | Adapter required |
| Bilibili | Public video candidates | `bili search` | Anonymous first | One result page; 1–50 requested candidates | Raw CLI step |
| YouTube | Public videos or one explicit public channel | Bundled `youtube_search.py` using Data API v3 or anonymous `yt-dlp` | Existing API key if present; otherwise no login Cookie | 1–50 candidates; search/channel modes | Envelope |
| Xiaoyuzhou | Public episode/page candidates matching a keyword | AnySearch `site:xiaoyuzhoufm.com` | Anonymous public web | 10 candidates per query | Envelope |

These are bounded discovery routes, not claims of complete native indexes.
Platform search results, counters, rankings, snippets, and publication times
remain candidate metadata until independently checked.

## Platform details

### GitHub

- The current native route searches **public repositories only**.
- The query is placed after `--`, so it cannot be interpreted as another `gh`
  option.
- The Skill does not claim native code, Issue, or Pull Request object search,
  and it does not clone or modify repositories.

### Zhihu

- Keyword search and the explicit hot list pass through the bundled allowlisted
  adapter and become normalized envelopes.
- Search returns at most 10 candidates per query, exposes no pagination or time
  filter, and batch mode produces at most five independent searches.
- Hot-list mode must be explicitly selected and returns at most 30 entries.
- The separately installed CLI-compatible runtime manages its Access Secret in
  macOS Keychain. This repository does not independently verify that runtime's
  vendor provenance. Personal commands, favorites, followees, and other private
  scope are excluded.

### WeChat Official Accounts

- This means public Official Account article discovery across accounts. It does
  **not** mean personal WeChat search, chat access, account administration, or
  Official Account backend access.
- The route uses an anonymous public search surface through OpenCLI.
- WeChat desktop and mobile UI are never controlled by this Skill.

### Weibo

- Each process starts with an ephemeral, in-memory anonymous visitor session
  against the public mobile search surface.
- Only an explicit access-gate failure—such as a login/verification redirect or
  access denial—may trigger one bounded read-only OpenCLI search using the
  existing Chrome session. Network errors, rate limits, ordinary parse errors,
  and zero results do not authorize that fallback.
- A query is capped at three pages and 20 candidates. Batch mode accepts at
  most five queries, runs serially, and waits at least five seconds between
  steps.
- `--days` is a client-side filter over the bounded returned pages, not a
  server-side or exhaustive date search. Comments, profiles, and media are not
  fetched, and Cookie values never enter adapter input, output, or logs.

### Xiaohongshu and Douyin

- Both routes are public, read-only keyword discovery. They may automatically
  reuse an existing Chrome session only within this narrow route.
- Searches use a background ephemeral site session, one keyword at a time,
  release the tab after use, and run serially with at least a five-second gap.
- Xiaohongshu returns at most 20 candidates; Douyin returns at most 30. Their
  platform time control accepts `0`, `1`, `7`, or `180` days and is not a strict
  coverage guarantee, so consumers should recheck returned timestamps.
- No post, comment, like, collect, follow, message, private feed, private
  collection, account change, CAPTCHA handling, download, or comment expansion
  is included.

### Toutiao

- The route uses a dedicated anonymous profile rather than the user's Chrome
  state.
- It performs a low-frequency, single-keyword search over current public
  non-video results, with no automatic retry.
- The planner accepts a 1–30 day control and caps a step at 50 candidates.

### X / Twitter: Quick versus Research

Both modes start with the official Grok CLI account OAuth and native
`x_search`. A Grok result must pass through `grok_x_result_adapter.py`, which
keeps only posts in the tool's structured `matched` time-verification bucket.

| Mode | Best for | Execution model | Stop rule |
|---|---|---|---|
| Quick | A small number of focused queries | One outer `search_x_with_grok` call for every supplied query; at most 20 candidates per call | Stop after the supplied queries or on any primary-route failure |
| Research | Broader, auditable X coverage | At least three distinct focused queries, gated waves of at most five, offline merge and `tweet_id` deduplication | Target reached, no material gap, no new unique result, one gap-fill round used, 40-call budget reached, or any non-quota primary failure |

The time window is limited to 1–7 days. Repost/reply, author, language,
engagement, and sort criteria guide retrieval, but the offline merger reapplies
only fields actually present in structured candidates. Missing metrics remain
unknown; they are never invented from prose.

Fallbacks are deliberately asymmetric:

1. Grok native `x_search` is always first.
2. Anonymous FxTwitter is eligible only when output explicitly proves Grok
   account quota or usage-limit exhaustion.
3. If FxTwitter also fails or returns no result, the route stops.
4. OpenCLI/xreach may use the local X session and remain disabled until the
   user explicitly authorizes that fallback for the current task and the plan
   is regenerated with `--login-approved`.

Authentication failures, 401/403, permission errors, timeouts, network or
service errors, unverifiable search evidence, and zero results are not quota
exhaustion and must not unlock the fallback chain.

### Bilibili

- The native route searches public videos through `bili` and returns candidate
  URLs and metadata from one bounded result page.
- It does not download video, audio, subtitles, comments, or account data.

### YouTube

- `search` discovers public videos. `channel` browses one explicit handle,
  channel ID, or channel URL as a public discovery container.
- If `YT_BROWSE_API_KEY` or `YOUTUBE_API_KEY` already exists, the adapter can use
  YouTube Data API v3 for channel resolution, time controls, and ordering.
- Otherwise it uses anonymous `yt-dlp`, ignores user configuration, plugins,
  cache, and login Cookies, passes only a minimal non-credential environment,
  and forces `--skip-download`.
- Both backends emit normalized candidates and return at most 50 results. The
  anonymous backend cannot guarantee every API-level ordering option.

### Xiaoyuzhou

- OpenCLI does not provide a native full-site keyword route here, so Unified
  Search uses a public AnySearch `site:xiaoyuzhoufm.com` query.
- The result is normalized, but it is a public web index view—not Xiaoyuzhou's
  complete native index.

### Platform batch behavior

Zhihu and Weibo support bounded batches of up to five independent native
adapter calls. For other named platforms, `--mode batch` is deliberately
rewritten into AnySearch `site:` queries. That public-web view is useful for
cross-keyword discovery, but it is not equivalent to complete native search.

## Installation

Copy this directory into the directory that contains your other Skills. The
default layout is:

```text
~/.agents/skills/
  anysearch/
    runtime.conf
  yichen-content-archive/
  yichen-unified-search/
  yichen-web-research/
```

Set `YICHEN_SKILLS_ROOT` when using a different parent directory. The Python
adapters use only the standard library except for the optional `idna` package,
which strengthens UTS #46 host validation. Missing `idna` fails closed for
non-ASCII hosts.

Install only the external runtimes needed by your chosen routes. Examples
include AnySearch, a Zhihu Open Platform CLI-compatible runtime, OpenCLI, Grok CLI, `yt-dlp`, `bili`,
`gh`, and `xreach`. No external executable or credential is bundled here.

## Quick start

Generate an offline plan without calling a search backend:

```bash
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "latest public AI model release" --platform auto --limit 10
```

Examples:

```bash
# General + vertical hybrid plan
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "cross-border data rule" --platform web --domain legal --hybrid

# Zhihu CLI search
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "Agent memory" --platform zhihu --limit 10

# Bounded X research plan; supply at least three distinct focused queries
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --platform x --depth research --days 7 --limit 20 \
  --target-results 100 --max-searches 8 \
  --query "topic official announcement" \
  --query "topic independent evaluation" \
  --query "topic developer feedback"

# Explicit same-origin site map
python3 "${YICHEN_SKILLS_ROOT:-$HOME/.agents/skills}/yichen-unified-search/scripts/route_search.py" \
  --query "https://example.com/docs/" --platform web --mode site-map --limit 100
```

The planner returns `status`, `authorization`, `steps`, and `limitations`.
Execute only the emitted steps. Full command contracts are documented in
[`references/routes.md`](references/routes.md).

X plans set `allow_authenticated_fallback=false` by default. If anonymous
FxTwitter is eligible but fails, stop. Only after the user explicitly authorizes
authenticated OpenCLI/xreach fallback for the current task may the planner be
rerun with `--login-approved`; the MCP server independently enforces the same
boolean gate.

## Portable configuration

| Variable | Purpose |
|---|---|
| `YICHEN_SKILLS_ROOT` | Directory containing this Skill and its sibling Skills |
| `YICHEN_ANYSEARCH_RUNTIME_CONF` | Override the AnySearch `runtime.conf` with an absolute path |
| `YICHEN_UNIFIED_SEARCH_RECEIPT_KEY` | Optional in-memory HMAC key; use only through a private environment |
| `YICHEN_UNIFIED_SEARCH_RECEIPT_KEY_FILE` | Override the private receipt-key file |
| `FIRECRAWL_API_KEY` | Firecrawl API key supplied through the process environment |
| `FIRECRAWL_KEY_FILE` | Override the private Firecrawl key file |
| `ZHIHU_CLI` | Override the separately installed Zhihu CLI-compatible runtime with an absolute executable path |
| `YT_BROWSE_API_KEY` / `YOUTUBE_API_KEY` | Optional YouTube Data API v3 key |

The default receipt-key and Firecrawl-key files are under the current user's
`~/.config/agent-secrets/` directory. Private key files must be owned by the
current user and have mode `0600` or stricter. Values, local credential files,
browser state, and generated candidate bundles must never be committed.

The default Zhihu CLI-compatible runtime location on macOS is resolved from
`Path.home()` under `~/Library/Application Support/zhihu-cli/`; an absolute
`ZHIHU_CLI` override supports other installation locations without editing the
Skill.

## Query and candidate data flow

```text
user scope
  -> offline route_search.py plan
  -> exactly the selected public backend
  -> backend-specific adapter
  -> candidate envelope + coverage + sanitized errors
  -> optional explicit current-candidate opening
```

The request is disclosed only to the selected backend:

- AI-freshness intent goes to AI HOT.
- General, batch, and vertical queries go to AnySearch.
- Zhihu and Weibo queries go only to their respective adapters.
- A Firecrawl URL is sent only for explicit Map or explicit candidate Scrape.
- X queries go to Grok native `x_search`; anonymous FxTwitter is permitted only
  after output explicitly proves account quota exhaustion. Authenticated
  OpenCLI/xreach fallback is disabled unless the current-task authorization
  flag is explicitly true.

Every normalized envelope uses schema version `1.0` and contains `request`,
`routes`, `candidates`, `coverage`, and `errors`. See
[`references/candidate-schema.md`](references/candidate-schema.md).

### Signed AnySearch receipts

AnySearch search and batch results carry a short-lived HMAC receipt bound to
the run ID, candidate ID, URL, query, retrieval time, and expiry. Verification
accepts the complete unmodified candidate JSON (or an `@file` containing it),
not a bare URL. The default lifetime is two hours.

The receipt proves only that the URL came from a recent adapter search. It does
not authenticate the remote page, prove a claim, or upgrade
`verification.status` beyond `candidate`. AnySearch Extract and Firecrawl
Scrape may attach page text while preserving that distinction.

## Read-only and login-state boundaries

- No posting, commenting, liking, collecting, following, messaging, deletion,
  account changes, CAPTCHA solving, or private-scope reads.
- WeChat desktop and mobile UI are never controlled. Public-account discovery
  uses only anonymous public search routes.
- Xiaohongshu and Douyin may reuse an existing Chrome session only for the
  bounded public read-only route described in `SKILL.md`; writes and private
  data remain outside this Skill.
- Weibo starts with an ephemeral in-memory anonymous visitor session. It may
  invoke one fixed read-only OpenCLI search only after an access-gate failure.
  Network failures do not authorize browser fallback, and Cookie values never
  enter adapter input, output, or logs.
- Zhihu authentication remains inside the configured CLI runtime's macOS Keychain flow.
  The adapter removes `ZHIHU_ACCESS_SECRET` from its child environment and does
  not expose account or private commands. Because the CLI uses that credential,
  Zhihu candidates are marked `authenticated_public` with
  `login_state_used=true` even though the returned content is public.
- YouTube anonymous fallback ignores user configuration, plugins and cache,
  receives only a small non-credential environment, and always uses
  `--skip-download`.

## Validation

From the repository root:

```bash
python3 -m unittest discover -s yichen-unified-search/tests -p 'test_*.py'
python3 -m compileall -q yichen-unified-search/scripts yichen-unified-search/tests
python3 yichen-web-research/scripts/validate_family.py
```

The unit tests are offline and cover routing, normalization, signed receipts,
URL validation, bounded fallback behavior, redaction, and static publication
contracts. `validate_family.py` checks the family-level integration.

Third-party attribution is in
[`references/THIRD_PARTY_NOTICES.md`](references/THIRD_PARTY_NOTICES.md).
