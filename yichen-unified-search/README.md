# Yichen Unified Search

`yichen-unified-search` is a read-only discovery router for public web and
platform search. It creates an offline execution plan, delegates only to the
selected backend, and provides code-owned candidate normalization for the
adapters that emit envelopes. Direct native-CLI plan steps remain raw until a
documented downstream normalizer handles them.

It does not download media, archive pages, read private collections, operate
WeChat, or perform social write actions. Known-URL reading and archiving belong
to `yichen-content-archive`.

## Capabilities

| Intent | Backend | Main behavior |
|---|---|---|
| Time-sensitive AI news and releases | AI HOT | Selected/all/daily discovery, category and keyword filters, at most seven days |
| General, batch, and vertical web search | AnySearch | Normalized Markdown parsing, batches of at most five, optional general + vertical hybrid routing |
| Explicit site link enumeration | Firecrawl Map | Public HTTP(S), same origin, bounded seed path, at most 100 links |
| Explicit current-candidate page opening | AnySearch Extract or Firecrawl Scrape | Requires a complete, signed candidate from the current search |
| Zhihu public search and hot list | Separately installed Zhihu Open Platform CLI-compatible runtime | Allowlisted `search zhihu` and `hot` commands only; runtime provenance is not independently verified here |
| Weibo public keyword search | Anonymous mobile endpoint, then one bounded OpenCLI fallback | At most three pages and 20 candidates; browser fallback only after an access-gate failure |
| YouTube public videos and channels | YouTube Data API v3 or anonymous `yt-dlp` | Search/channel modes, local filters and sorting, no media download |
| X Quick | Grok native `x_search` | One bounded call per supplied query, at most 20 candidates and a seven-day window |
| X Research | Grok + offline normalizer and merger | Gated waves, deterministic deduplication, at most 40 searches and one gap-fill round |
| Other supported public platforms | Native CLI or OpenCLI route selected by the planner | Candidate discovery only, with platform-specific authorization and limits |

AI HOT summaries and all search snippets are discovery text, not verified
facts. Firecrawl is never an implicit fallback for ordinary keyword search.

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
  --platform x --depth research --days 7 --target-results 100 --max-searches 8 \
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
