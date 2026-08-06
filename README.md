# yichen-skills

English | [中文](./README.zh.md)

A skill collection for creators who want to streamline writing, X content slicing, X Articles draft publishing, WeChat digital-asset capture, and local workflows with Claude Code and Codex.

## Maintainer

Created and maintained by **逸尘 (Yichen)**.

- WeChat: `yichen365ai`
- When adding me, please include `GitHub` in the verification message

## What This Repo Does

1. Turn Claude Code conversations into structured Obsidian notes (`yichen-summary`)
2. Upload Obsidian/Markdown articles to X Articles drafts (`yichen-x-article-draft-uploader`)
3. Run two WeChat accounts on one Mac with a distinct blue icon (`yichen-mac-wechat-dual-open`)
4. Turn WeChat chats, Moments, and Favorites into AI-powered digital assets (`yichen-wechat-local-vault`)
5. Fetch benchmark videos from known Douyin links (`yichen-content-archive`)
6. Fetch benchmark posts from known Xiaohongshu links (`yichen-content-archive`)
7. Transcribe, caption, and rough-cut talking-head videos with Volcengine ASR (`yichen-volc-asr`)
8. Diagnose benchmark video transcripts (`yichen-video-content`)
9. Run verified research through the official ChatGPT web page (`yichen-chatgpt-web-research`)
10. Hand off rough cuts to Jianying/CapCut for final editing (`yichen-jianying-editor`)
11. Install and maintain a Markdown/Obsidian-first Agent Memory Vault system (`yichen-agent-memory`)
12. Batch-export WeChat Official Account article history, original-article lists, bodies, and optional read/comment metrics (`yichen-wechat-mp-batch-exporter`)
13. Read and export local WeCom/企业微信 5.x database snapshots without controlling the app (`yichen-wecom-local-vault`)
14. Let GPT call Grok for native X search or an independent second opinion without switching the main model (`yichen-grok-consult`)
15. Export Xiaohongshu favorites, Douyin favorites, and X bookmarks as validated local URL files (`yichen-social-bookmarks-exporter`)
16. Route multi-stage internet research through one safety-first entry point (`yichen-web-research`)
17. Normalize public web and platform search into reviewable candidates (`yichen-unified-search`)
18. Read, download, and archive only known or explicitly confirmed links (`yichen-content-archive`)
19. Gate private bookmark export behind current-task authorization (`yichen-bookmarks-export`)
20. Choose between Step and Doubao/Volcengine ASR without duplicate submissions (`yichen-asr`)
21. Create authorized WeCom documents and manage todos, meetings, and schedules through the official CLI without controlling the desktop app (`yichen-wecom-operations`)
22. Turn one public X Post or Thread URL into verified 3:4 image slices and a finished video that embeds complete native video visuals and preserves their original audio when present (`yichen-x-slicer`)

## Included Skills

### 1) `yichen-summary`
- Purpose: extract key insights from the current conversation and save to Obsidian
- Typical triggers: `/yichen-summary`, "save conversation", "export highlights"
- Capabilities:
  - Filters out low-value chat transitions
  - Produces structured notes (Background, Core Content, Solution, Key Points, Related)
  - Useful for long-term knowledge accumulation

### 2) `yichen-x-article-draft-uploader`
Upload Obsidian/Markdown long-form articles to X Articles drafts:
- Uses the first image as the X Article cover
- Converts Markdown into rich text for the X editor
- Inserts body images at their original Markdown positions
- Runs in an independent Playwright browser so it does not take over the user's current Chrome window
- Reuses Chrome login state through temporary exported cookies
- Saves drafts only and does not click the final `发布` button

See [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md) for installation, privacy notes, and troubleshooting.

### 3) `yichen-mac-wechat-dual-open`
Run two WeChat accounts simultaneously on macOS — no third-party tools:
- Copies WeChat, changes the bundle identifier, and re-signs locally
- Recolors the second app's icon from green to blue for visual distinction
- Handles both outer and embedded icon files, Finder custom icon, and cache refresh
- One-command workflow: `create` → `recolor-icon` → `launch`
- Typical triggers: "微信双开", "WeChat dual open", "double WeChat"
- Requirements: macOS 12+, WeChat at `/Applications/WeChat.app`, Python 3.10+, Pillow
- Limitations: breaks after WeChat updates (re-run `repair`), push notifications may be unreliable
- Based on the well-known copy + bundle-id + ad-hoc signing method documented by [@koffuxu](https://x.com/koffuxu/status/2043110831584690427)

### 4) `yichen-wechat-local-vault`
WeChat digital-asset assistant for macOS:
- Decrypts WeChat Mac 4.x local SQLCipher databases (AES-256-CBC)
- Extracts chats, Moments (`sns.db`), and Favorites (`favorite.db`)
- Generates AI-powered chat digests, Moments reports, Favorites cleanup notes, customer follow-up drafts, and relationship review prompts
- First-time onboarding introduces 3 categories and 9 playbooks: chat records, Moments, and Favorites
- Configurable monitoring for groups, contacts, Moments targets, and Favorites cleanup preferences
- First-time setup guided via frida key extraction
- Typical triggers: "微信解析", "微信全量", "微信增量", "导出聊天", "朋友圈解析", "收藏夹整理", "客户跟进", "yichen-wechat-local-vault"
- Requirements: macOS, WeChat Mac 4.x, Python 3.9+, `pycryptodome`, `zstandard`
- See [yichen-wechat-local-vault/README.md](./yichen-wechat-local-vault/README.md) for full documentation

### 5–6) Social fetchers integrated into `yichen-content-archive`
The former standalone Douyin and Xiaohongshu fetchers now have one source of truth:
- `douyin_download.py` reads metadata or downloads a known Douyin video through Playwright interception
- `xiaohongshu_fetch.py` anonymously reads known posts first, then downloads requested video, subtitles, or images
- Existing outputs are never overwritten; a new `-run-N` path is selected instead
- Xiaohongshu cookies require explicit current-task authorization, and optional Feishu deposition remains opt-in

### 7) `yichen-volc-asr`
Transcribe local audio/video files and generate rough cuts:
- Uses environment variables for Volcengine ASR and TOS configuration
- Produces transcript text, SRT subtitles, ASR cache, and optional rough-cut MP4
- Requires explicit user approval before cleaning temporary files

### 8) `yichen-video-content`
Analyze benchmark video transcripts:
- Breaks a transcript down sentence by sentence
- Labels each sentence's role
- Produces a structured imitation and improvement report

### 9) `yichen-chatgpt-web-research`
Run research through the user's already signed-in official ChatGPT website account:
- Uses the real ChatGPT web page, not the OpenAI API or a separate account
- Prefers Chrome extension control and falls back to visible Computer Use only when necessary
- Waits for a full answer with a unique marker before extracting
- Saves raw and readable Markdown reports under the current workspace's `reports/` directory
- Keeps profile names, local paths, cookies, tokens, and browser storage out of the public skill

See [yichen-chatgpt-web-research/README.md](./yichen-chatgpt-web-research/README.md) for privacy notes and workflow details.

### 10) `yichen-jianying-editor`
Guide Jianying/CapCut desktop finishing:
- Confirms media files and imports rough cuts
- Handles timeline placement, subtitles, visual polishing, and export notes
- Leaves automatic rough-cut logic to `yichen-volc-asr`

### 11) `yichen-agent-memory`
Install and maintain the public Agent Memory Vault system:
- Creates a local Markdown/Obsidian-first memory vault from the public template
- Uses Markdown as the source of truth and SQLite/FTS as the fast index
- Supports optional Zvec semantic retrieval for fuzzy "meaning-based" recall
- Guides prewrite reconcile, closeout, audit, and privacy-safe template updates
- Typical triggers: "install Agent Memory Vault", "set up memory vault", "run memory closeout", "audit my Agent Memory Vault"
- Template repo: [mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault)

### 12) `yichen-wechat-mp-batch-exporter`
Batch-export WeChat Official Account articles:
- Downloads known `mp.weixin.qq.com` article URLs as Markdown/JSON/text/HTML
- Uses `wechat-article-exporter` for account search and history list sync
- Separates `publish_groups`, `expanded_url_items`, and `original_articles`
- Supports enhanced archive planning for read counts, likes, shares, comments, and replies through `wxdown-service` when fresh user-owned credentials are available
- Requires user confirmation for QR login, credential capture, certificate trust, proxy changes, and any WeChat desktop steps
- Never operates WeChat UI or stores real credentials in the repo

See [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md) for setup and privacy notes.

### 13) `yichen-wecom-local-vault`
Read, decrypt, query, and export local WeCom/企业微信 5.x desktop databases on macOS:
- Creates private, timestamped plaintext snapshots and never writes back to the WeCom container
- Supports contacts, sessions, message history, search, and Markdown/JSON export
- Keeps raw keys, snapshots, and chat exports out of Git
- Does not control the original WeCom app or send messages

### 14) `yichen-grok-consult`
Use Grok from a GPT-led Codex task without switching the main model:
- Runs native public X search through the official Grok Build CLI
- Verifies that the isolated Grok session completed `XSearch`
- Extracts status URLs and deterministically decodes Snowflake publication times
- Keeps Grok outside the current project and disables local file, shell, MCP, memory, and subagent access
- Provides optional independent-answer, review, and challenge tools through local OpenCodex

See [plugins/yichen-grok-consult/README.md](./plugins/yichen-grok-consult/README.md) for installation, privacy boundaries, and verification limits.

### 15) `yichen-social-bookmarks-exporter`
Read-only export for the currently accessible private collections on three platforms:
- Reuses the user's authenticated Chrome tab for Xiaohongshu and Douyin, scrolling to a stable bottom and deduplicating links
- Uses a separately installed Field Theory `ft` CLI build whose version contains `graphql-only` for the X route
- Writes one URL per line and validates counts, blanks, duplicates, and malformed rows
- Does not export cookies, browser storage, passwords, or token databases; Xiaohongshu `xsec_token` values stay only in the user-requested local link file

See [yichen-social-bookmarks-exporter/README.md](./yichen-social-bookmarks-exporter/README.md) for installation, dependencies, and privacy boundaries.

### 16) `yichen-web-research`

Top-level router for research tasks that span search, candidate review, archiving, and optional transcription:

- Sends single-stage work directly to the appropriate child Skill
- Never turns a search result into an automatic download
- Enforces read-only social-platform use, exact-scope authorization, and no WeChat UI control
- Ships with a portable read-only backend doctor

See [yichen-web-research/README.md](./yichen-web-research/README.md) for the full family, optional backends, and configuration.

### 17) `yichen-unified-search`

Search-only orchestration across public web and platform-specific adapters:

- Supports AnySearch, GitHub, WeChat public search, Xiaohongshu, Douyin, Toutiao, X, Bilibili, YouTube, and Xiaoyuzhou routes
- Produces normalized candidates with provenance, coverage, and limitations
- Requires current-task authorization before browser-session searches

### 18) `yichen-content-archive`

Known-link and exact-container processing:

- Reads and archives confirmed web, Xiaohongshu, Douyin, WeChat Official Account, YouTube, Bilibili, and Xiaoyuzhou targets
- Bundles the only maintained Douyin and Xiaohongshu known-link fetchers; optional Xiaohongshu-to-Feishu deposition remains explicit
- Keeps search/discovery outside the archive layer
- Uses collision-safe outputs, resumable checkpoints, and explicit overwrite guards

### 19) `yichen-bookmarks-export`

Safety wrapper around `yichen-social-bookmarks-exporter`:

- Requires explicit authorization for each platform and scope in the current task
- Exports links only and does not transfer that authorization to downloads
- Produces a minimal handoff that references files without embedding private URLs

### 20) `yichen-asr`

Unified ASR router:

- Defaults text-only work to a compatible Step executor and timestamp/SRT work to `yichen-volc-asr`
- Uses only environment-provided App IDs and tokens
- Never silently resubmits an already submitted job to another provider

### 21) `yichen-wecom-operations`

Owner-authorized WeCom cloud operations through the official `@wecom/cli`:

- Creates normal documents and Markdown-based smart documents
- Reads or overwrites documents only after permission and exact-target checks
- Creates and manages todos; meetings and schedules are available only when the enterprise grants those categories
- Never controls the WeCom desktop app and never sends messages
- Keeps credentials, internal IDs, receipts, source files, and customer data out of Git
- Treats local-image upload as an optional external-helper capability that is not distributed in this repository

See [yichen-wecom-operations/README.md](./yichen-wecom-operations/README.md) for installation, permission boundaries, and the local-image limitation.

### 22) `yichen-x-slicer` — Yichen X Slicer

Turn one public X status URL into finished social assets:

- Generates a verified 1080×1440 image sequence, a PNG-only ZIP, and an H.264 video by default
- Uses the bundled Sunset Amber template by default and includes 11 visual templates
- Keeps only the focal Post or verified same-author Thread; quoted content and unrelated replies are excluded
- Keeps text and photo holds static, limits added motion to four-frame page transitions, and plays every selected native video in full inside its media stage instead of freezing its poster
- Reads public data anonymously through FxTwitter and never uses X login state or cookies
- Never generates TTS, voice-over, BGM, or music; selected native-video audio stays aligned to its matching page, while source-silent intervals remain silent and all-source-silent runs contain no audio stream

Install this Skill directly with `npx skills add mcncarl/yichen-skills --skill yichen-x-slicer`.

## Project Structure

```text
yichen-skills/
├─ yichen-summary/
│  └─ SKILL.md
├─ yichen-x-article-draft-uploader/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  └─ scripts/
│     ├─ export_x_cookies_from_chrome.py
│     ├─ parse_markdown.py
│     └─ upload_markdown_to_x_article.py
├─ yichen-wechat-local-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ decrypt_all_dbs.py
│     ├─ export_chat.py
│     ├─ extract_keys.py
│     ├─ list_contacts.py
│     ├─ search_sns.py
│     └─ wechat_digest.py
├─ yichen-mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ yichen-volc-asr/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ transcribe.py
├─ yichen-video-content/
│  ├─ SKILL.md
│  └─ references/
│     └─ title-formulas.md
├─ yichen-chatgpt-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ agents/
├─ yichen-jianying-editor/
│  └─ SKILL.md
├─ yichen-agent-memory/
│  ├─ SKILL.md
│  └─ agents/
├─ yichen-wechat-mp-batch-exporter/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-wecom-local-vault/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-social-bookmarks-exporter/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ scripts/
│  └─ tests/
├─ yichen-unified-search/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-content-archive/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-bookmarks-export/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  └─ tests/
├─ yichen-asr/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-wecom-operations/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-x-slicer/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ assets/
│  ├─ references/
│  └─ scripts/
├─ .agents/plugins/
│  └─ marketplace.json
├─ plugins/yichen-grok-consult/
│  ├─ .codex-plugin/plugin.json
│  ├─ .mcp.json
│  ├─ README.md
│  ├─ README.zh.md
│  ├─ mcp/server.mjs
│  └─ skills/yichen-grok-consult/
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## Requirements

- Claude Code / Codex CLI (with local skill loading)
- Python Playwright (required by `yichen-x-article-draft-uploader`)
- Python 3.9+
- Dependencies:
  - X article drafts: `pip install playwright pycryptodome && python3 -m playwright install chromium`
  - WeChat local vault: `pip install pycryptodome zstandard`
  - WeChat dual open: `pip install Pillow`
  - Content archive (Douyin): `pip install playwright requests && python3 -m playwright install chromium`
  - Content archive (Xiaohongshu): `pip install requests`
  - Volc ASR rough cut: `pip install requests` plus local `ffmpeg` / `ffprobe`
  - ChatGPT Web research: Chrome signed in to ChatGPT, plus Chrome/Computer Use capability in your agent environment
  - WeChat MP batch export: Python 3 standard library for known URL downloads; `wechat-article-exporter` / `wxdown-service` only for account history, metrics, and comments
  - WeCom local vault: `pycryptodome`; `frida` only for explicitly authorized raw-key capture
  - Grok Consult: Node.js 18+, the official Grok Build CLI, and an active `grok login`; local OpenCodex is optional for non-search consultation tools
  - Social bookmarks exporter: Xiaohongshu/Douyin require an agent environment with `chrome:control-chrome`; the X route optionally requires a Field Theory `ft` CLI build whose version contains `graphql-only`
  - Web research family: install all five family directories together; optional coverage uses AnySearch, OpenCLI, Grok CLI, `xreach`, `gh`, `yt-dlp`, `bili`, `ffmpeg`, and the companion Skills listed in its README
  - Yichen X Slicer: Node.js 18+, Playwright, local Chrome, `ffmpeg`, and `ffprobe`

## Installation

Copy this repository into your local skills directory:

- Common Claude path: `~/.claude/skills/`
- Common Agents path: `~/.agents/skills/`
- Custom skill path also works if your setup supports it

Keep directory names unchanged:
- `yichen-summary`
- `yichen-x-article-draft-uploader`
- `yichen-wechat-local-vault`
- `yichen-mac-wechat-dual-open`
- `yichen-volc-asr`
- `yichen-video-content`
- `yichen-chatgpt-web-research`
- `yichen-jianying-editor`
- `yichen-agent-memory`
- `yichen-wechat-mp-batch-exporter`
- `yichen-wecom-local-vault`
- `yichen-social-bookmarks-exporter`
- `yichen-web-research`
- `yichen-unified-search`
- `yichen-content-archive`
- `yichen-bookmarks-export`
- `yichen-asr`
- `yichen-wecom-operations`
- `yichen-x-slicer`

`yichen-grok-consult` is a Codex plugin rather than a standalone copied skill. Install it through this repository's marketplace:

```bash
codex plugin marketplace add mcncarl/yichen-skills --ref main
codex plugin add yichen-grok-consult@yichen-skills
```

## Quick Start (3 Minutes)

### A) Enable `yichen-summary`

1. Ensure `yichen-summary/SKILL.md` is available in your loaded skills path
2. Start a new session and run `/yichen-summary`
3. Confirm output is written to your Obsidian folder (example paths may use `<OBSIDIAN_VAULT>/...`)

### B) Enable `yichen-x-article-draft-uploader`

1. Install Python Playwright: `pip3 install playwright pycryptodome && python3 -m playwright install chromium`
2. Make sure Chrome is already logged in to X
3. Say "upload this Markdown article to X Articles draft" or run the script directly
4. The skill creates a fresh draft, preserves the first image as the cover, and inserts body images in place
5. See [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md) for commands

### C) Enable `yichen-mac-wechat-dual-open`

1. Install Python dependency: `pip3 install Pillow`
2. In Claude Code, say "帮我微信双开" or "WeChat dual open"
3. The skill will create a second WeChat at `~/Applications/WeChat-2.app` with a blue icon
4. See `yichen-mac-wechat-dual-open/SKILL.md` for all commands

### D) Enable `yichen-wechat-local-vault`

1. Install Python dependencies: `pip3 install pycryptodome zstandard`
2. In Claude Code or Codex, say "微信解析", "导出聊天", or "收藏夹整理"
3. First run will guide you through key extraction and choosing among the 9 playbooks
4. If unsure, start with the recommended trio: group chat digest + Moments report + Favorites cleanup
5. Subsequent runs generate the selected digest, report, or draft workflow
6. See [yichen-wechat-local-vault/README.md](./yichen-wechat-local-vault/README.md) for details

### E) Enable the creator video workflow

1. Install Playwright, requests, and ffmpeg
2. Use `yichen-content-archive` to save known Douyin or Xiaohongshu benchmark media locally
3. Use `yichen-volc-asr` to transcribe or rough-cut recorded talking-head videos
4. Use `yichen-video-content` to diagnose benchmark transcripts
5. Use `yichen-jianying-editor` for final Jianying/CapCut import, subtitle, polish, and export steps

### F) Enable `yichen-chatgpt-web-research`

1. Make sure Chrome is already signed in to the intended ChatGPT account
2. Keep the ChatGPT tab or profile visible when a Pro route must be confirmed
3. Ask for official-site research, for example: "Use ChatGPT Web to research Anthropic and save a Markdown report"
4. The skill waits for a complete answer, verifies the marker, and saves raw/readable Markdown reports

### G) Enable `yichen-agent-memory`

1. Make sure `yichen-agent-memory/SKILL.md` is available in your loaded skills path
2. Ask Codex to "install Agent Memory Vault" or "set up a local Agent Memory Vault vault"
3. The skill will use [mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault) to create a private local vault
4. After setup, use `codex_memory_search.py`, `codex_memory_closeout.py`, and `codex_memory_audit.py` for search, task-end cleanup, and periodic review

### H) Enable `yichen-wechat-mp-batch-exporter`

1. Make sure `yichen-wechat-mp-batch-exporter/SKILL.md` is available in your loaded skills path
2. For known article URLs, ask for a Markdown download directly
3. For account history, configure `WECHAT_ARTICLE_EXPORTER_DIR` or use the public exporter route supported by `wechat-article-exporter`
4. For read counts and comments, configure `WXDOWN_SERVICE_DIR` and confirm the credential-capture workflow before starting any local helper
5. See [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md) before using metrics, comments, proxy, certificate, or WeChat desktop workflows

### I) Enable `yichen-wecom-local-vault`

1. Ensure `yichen-wecom-local-vault/SKILL.md` is available in your loaded skills path
2. Install `pycryptodome`; install `frida` only if you need an explicitly authorized local raw-key capture
3. Ask to inspect or export your local WeCom data; the workflow never controls the original app

### J) Enable `yichen-grok-consult`

1. Install the official Grok Build CLI and run `grok login`
2. Add the `mcncarl/yichen-skills` marketplace and install `yichen-grok-consult`
3. Start a new Codex task
4. Ask GPT to search public X posts with Grok or request a Grok second opinion
5. See [plugins/yichen-grok-consult/README.md](./plugins/yichen-grok-consult/README.md) before configuring proxies or OpenCodex

### K) Enable `yichen-social-bookmarks-exporter`

1. Ensure `yichen-social-bookmarks-exporter/SKILL.md` is available in your loaded skills path
2. For Xiaohongshu or Douyin, sign in with the current Chrome session and open the intended favorites page
3. For X, verify that the separately installed `ft --version` contains `graphql-only`
4. Explicitly authorize the platforms, export scope, and output directory for the current task
5. The Skill exports and validates links only; it does not automatically download media or change collection state

### L) Enable the Web Research family

1. Install `yichen-web-research`, `yichen-unified-search`, `yichen-content-archive`, `yichen-bookmarks-export`, and `yichen-asr` together
2. Install only the optional backends needed for your platforms
3. Run `python3 yichen-web-research/scripts/validate_family.py`
4. Start with `$yichen-web-research` for multi-stage work, or call a child directly for search-only, known-link archive, bookmark export, or local ASR
5. See [yichen-web-research/README.md](./yichen-web-research/README.md) before enabling account-session or paid-ASR routes

## Support This Project

If these Skills are useful to you, you can voluntarily buy me a coffee through
the WeChat appreciation code below.

<p align="center">
  <img src="./assets/wechat-reward-code.jpg" width="280" alt="Yichen's WeChat appreciation code">
</p>

Appreciation is entirely voluntary. It does not create a paid-service,
technical-support, feature-delivery, or response-time commitment.

## X Cookie Handling

This repo does not include real credentials or cookie templates.

`yichen-x-article-draft-uploader` exports current X cookies from the user's local Chrome profile into a temporary Playwright cookie file:

```bash
python3 ~/.codex/skills/yichen-x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py --output /tmp/x_current_cookies.json
```

The temporary file is sensitive and should be deleted after use:

```bash
rm -f /tmp/x_current_cookies.json
```

`.gitignore` already ignores `**/cookies.json`.

## Security Notes

- Real token/cookie values are not included
- History/cache artifacts are excluded from tracking
- Personal absolute paths are replaced with generic forms
- Third-party AppID, AppToken, TableID, bucket names, and ASR tokens must be supplied through environment variables or private config
- WeChat exporter auth-keys, credential files, QR secrets, captured cookies, and downloaded article archives must stay local and private
- `yichen-grok-consult` contains no fixed proxy or credentials; Grok queries and results are still sent to xAI and retained in an isolated local session directory
- The Web Research family contains no personal absolute paths, App IDs, tokens, fixed Keychain items, or private proxy values; account-backed routes remain opt-in
- `yichen-wecom-operations` contains no Bot ID, Secret, internal user/resource ID, receipt, source document, or customer data; authorization remains tenant-specific

If you ever exposed real cookies in a public repo, rotate them immediately.

## FAQ

### Why doesn't a skill trigger?
- Verify the skill folder is in your actually loaded skill path
- Restart the session and retry
- Check `name` and `description` in `SKILL.md` frontmatter

### Why did X Articles draft upload fail?
- Check whether Chrome is still logged in to X
- Re-export temporary cookies
- Verify Python Playwright is installed
- Verify local Markdown/image paths exist

### Can I use my own Obsidian path?
- Yes. Replace example paths in skill files
- `<OBSIDIAN_VAULT>/...` is only an example

## For Redistributors

This repository is published for personal learning and non-commercial personal use only. Do not use it for commercial services, client delivery, paid products, internal company toolkits, marketplace packages, courses, or any other revenue-generating purpose without explicit written permission.

If you fork for personal study, keep at least:
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- `yichen-x-article-draft-uploader/README.md`

Do not republish or repackage this repository as a public skill bundle. Always remind users not to publish real credentials or private data.

## Acknowledgments

Parts of the X Articles draft workflow and Markdown parsing approach are adapted with references to:

- `wshuyi/x-article-publisher-skill`
  - Repo: <https://github.com/wshuyi/x-article-publisher-skill>
  - Docs: <https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - License: MIT

The WeChat database decryption approach in `yichen-wechat-local-vault` is adapted from:

- `zhuyansen/wx-favorites-report`
  - Repo: <https://github.com/zhuyansen/wx-favorites-report>
  - Author: zhuyansen
  - License: MIT
  - Specifically: the frida hook method for `CCKeyDerivationPBKDF` key extraction and SQLCipher 4 page-level decryption logic

The WeChat dual-open method in `yichen-mac-wechat-dual-open` is based on:

- [@koffuxu](https://x.com/koffuxu) — original tutorial (2026-04): [Mac 微信双开最完美方案](https://x.com/koffuxu/status/2043110831584690427)
- [@MinLiBuilds](https://x.com/MinLiBuilds) — independent confirmation (2026-04)

The isolated Grok Build search design in `yichen-grok-consult` was informed by:

- [`sudoHG/codex-grok-search`](https://github.com/sudoHG/codex-grok-search) — MIT-licensed public reference; no source code is vendored here

The X bookmark route in `yichen-social-bookmarks-exporter` calls:

- [`afar1/fieldtheory-cli`](https://github.com/afar1/fieldtheory-cli) — MIT-licensed optional external runtime; no Field Theory source or binary is vendored here
- The required `graphql-only` marker refers to a user-maintained modified build, not an official upstream release name; that build is not distributed by this repository

`yichen-wecom-operations` calls the separately installed official WeCom CLI:

- [`WeComTeam/wecom-cli`](https://github.com/WecomTeam/wecom-cli) — MIT-licensed external runtime; no upstream source, binary, Bot credential, or tenant data is vendored here
- Local-image upload requires an optional user-provided helper exposing `doc +doc_upload_image`; that local extension is not distributed here or represented as an upstream feature

See `THIRD_PARTY_NOTICES.md` for details.

## Compliance Boundary

- This project is not affiliated with, endorsed by, or sponsored by X, xAI, OpenAI, WeChat, Tencent, Xiaohongshu, Douyin, or Field Theory.
- This repository is for personal learning and non-commercial personal workflow use only.
- Commercial use, client delivery, resale, paid redistribution, marketplace packaging, course bundling, and internal company deployment are prohibited without prior written permission.
- Users are responsible for complying with X platform terms/policies and local laws.
- Collection-export workflows are only for data the user is authorized to access; do not bypass access controls, CAPTCHA, rate limits, or platform security measures.
- X internal GraphQL and platform-DOM routes are unofficial compatibility methods and may change or trigger platform controls.
- `yichen-wechat-local-vault` is for personal use only — only decrypt and read your own chat data.
- `yichen-wecom-local-vault` is for owner-authorized local data only — never upload keys, plaintext snapshots, or chat exports.
- `yichen-wecom-operations` is for owner-authorized bot resources only — never send messages, automate the client, bypass missing enterprise authorization, or commit IDs, receipts, source documents, and customer data.
- Never upload real account credentials (for example, `cookies.json`, `wechat-keys.json`) to public repositories.
- Never upload real chat records, WeChat databases, customer data, private notes, API keys, local paths, or other personal data.

## License

Personal Learning and Non-Commercial Use License. See [LICENSE](./LICENSE).
