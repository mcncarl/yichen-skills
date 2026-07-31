# Grok Consult for Codex

English | [简体中文](./README.zh.md)

`yichen-grok-consult` keeps GPT as the controlling Codex model while using Grok as a read-only second opinion or as a native X search backend.

This is an unofficial community plugin. It is not affiliated with, endorsed by, or sponsored by xAI, X, or OpenAI.

## What it provides

- `search_x_with_grok`: launches the official Grok Build CLI with native `x_search`. Only explicit account-quota exhaustion can activate anonymous FxTwitter; an empty or failed FxTwitter result can then continue to read-only OpenCLI and xreach. The tool extracts public X status URLs, decodes Snowflake timestamps, converts time zones, and filters a rolling window or fixed date.
- `ask_grok`: asks Grok for an independent answer.
- `review_with_grok`: asks Grok to review a draft or analysis.
- `challenge_with_grok`: asks Grok to stress-test a claim.

All four tools use the official Grok Build CLI and account OAuth. OpenCLI and xreach are X-only read-only fallbacks; they never replace Grok for ordinary consultation.

## Requirements

- Codex with plugin marketplace support.
- Node.js 18 or newer.
- Official [Grok Build CLI](https://docs.x.ai/build/overview), installed at `~/.grok/bin/grok` or configured through `GROK_CONSULT_CLI`.
- A valid Grok Build login created with `grok login`.
- Optional for X fallback only: the sibling `yichen-unified-search` Skill with `fxtwitter_search.py`, plus OpenCLI and xreach. These routes are used only under the documented fallback rules.

Official Grok Build installation at the time of publication:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
grok login
```

Always verify current installation instructions against xAI's official documentation before running a remote installer.

## Install from this repository

```bash
codex plugin marketplace add mcncarl/yichen-skills --ref main
codex plugin add yichen-grok-consult@yichen-skills
```

Start a new Codex task after installation so the plugin and MCP tools are loaded.

## Optional configuration

The public plugin does not include a fixed proxy, credential, API key, username, or absolute local path.

Supported environment variables:

| Variable | Purpose |
|---|---|
| `GROK_CONSULT_CLI` | Absolute path to the official Grok CLI when it is not at `~/.grok/bin/grok` |
| `GROK_CONSULT_SEARCH_TIMEOUT_MS` | Native-search timeout, bounded to 10–630 seconds |
| `GROK_CONSULT_SEARCH_MAX_TURNS` | Native-search turn limit, bounded to 1–60 |
| `GROK_CONSULT_PYTHON` | Absolute Python executable used by the FxTwitter adapter |
| `GROK_CONSULT_FXTWITTER_ADAPTER` | Absolute path to `fxtwitter_search.py` if the sibling Skill is installed elsewhere |
| `GROK_CONSULT_OPENCLI` | Absolute path to OpenCLI |
| `GROK_CONSULT_XREACH` | Absolute path to xreach |
| `GROK_CONSULT_LOCAL_READER_TIMEOUT_MS` | Local-reader timeout, bounded to 10–180 seconds |

If your network requires a proxy, add `HTTP_PROXY`, `HTTPS_PROXY`, and related variables only to your private local MCP environment. Do not commit proxy credentials.

## Security and privacy model

- Grok runs in an isolated, non-Git workspace under `~/.grok/grok-consult/`, not in the current project.
- The native-search child process receives an allowlisted environment rather than the full parent environment. `XAI_API_KEY` is not forwarded.
- Only `x_search`, `web_search`, and `web_fetch` are enabled for search. MCP access, local file tools, shell access, memory, subagents, and plan mode are disabled.
- The real Grok authentication file is referenced through `GROK_AUTH_PATH`; it is not copied into this repository or returned in tool output.
- The tool verifies at least one completed `XSearch` by reading the isolated session transcript. It does not trust a prose claim that a search occurred.
- Authentication, 401/403, permission, invalid-request, timeout, network, service, zero-result, or unverified-search errors do not qualify for FxTwitter fallback. Only explicit Grok account-quota or usage-limit exhaustion does.
- FxTwitter receives only the public query and no X cookies. OpenCLI and xreach may use local X session state, so keep them read-only and obtain any authorization required by the calling workflow.
- Queries, results, and session transcripts remain under the isolated Grok home and may also be processed by xAI. The plugin performs no automatic cleanup.
- The public result omits the user's absolute transcript path.

## Verification limits

- Transcript verification proves that the Grok session completed native `XSearch` at least once. It does not independently prove that every URL in Grok's final answer appeared in raw search output.
- Snowflake decoding reveals the timestamp encoded in a numeric X status ID. It does not independently prove that X issued the ID, that the post is still available, or that its text, author, and engagement metrics are correct.
- Engagement metrics are search-time observations and may be unavailable or change later.
- Native X search covers public content; it is not a stable replacement for the official X API when comprehensive structured data or an SLA is required.

## Architecture

```text
GPT-led Codex task
  -> local MCP server
  -> isolated official Grok Build CLI session (always first)
  -> native XSearch / supporting web tools
  -> on explicit account-quota exhaustion only:
       anonymous FxTwitter -> OpenCLI -> xreach
  -> native transcript proof or local read-only route proof
  -> URL extraction + Snowflake time decoding
  -> structured result returned to GPT
```

## Attribution

The design was informed by the public workflow in [`sudoHG/codex-grok-search`](https://github.com/sudoHG/codex-grok-search). No source code from that project is vendored here. See the repository-level `THIRD_PARTY_NOTICES.md`.

## License

This plugin follows the repository's [Apache License 2.0](../../LICENSE).
