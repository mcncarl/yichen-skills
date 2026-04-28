# yichen-skills

English | [中文](./README.zh.md)

A skill collection for creators who want to streamline writing, publishing, WeChat digital-asset capture, and daily workflows with Claude Code and Codex.

## What This Repo Does

1. Turn Claude Code conversations into structured Obsidian notes (`summary`)
2. Publish Obsidian/Markdown content to X (`x-publisher`)
3. Turn WeChat chats, Moments, and Favorites into AI-powered digital assets (`wechat-daily`)
4. Run two WeChat accounts on one Mac with a distinct blue icon (`mac-wechat-dual-open`)

## Included Skills

### 1) `summary`
- Purpose: extract key insights from the current conversation and save to Obsidian
- Typical triggers: `/summary`, "save conversation", "export highlights"
- Capabilities:
  - Filters out low-value chat transitions
  - Produces structured notes (Background, Core Content, Solution, Key Points, Related)
  - Useful for long-term knowledge accumulation

### 2) `x-publisher`
A focused publishing suite for long-form article publishing:
- `x-article-publisher`: publish long-form articles to X Articles
- `scripts/`: shared tooling for markdown parsing and clipboard handling

Windows-focused design, strong path handling, and a very high success rate for uploading articles to X Articles.

### 3) `mac-wechat-dual-open`
Run two WeChat accounts simultaneously on macOS — no third-party tools:
- Copies WeChat, changes the bundle identifier, and re-signs locally
- Recolors the second app's icon from green to blue for visual distinction
- Handles both outer and embedded icon files, Finder custom icon, and cache refresh
- One-command workflow: `create` → `recolor-icon` → `launch`
- Typical triggers: "微信双开", "WeChat dual open", "double WeChat"
- Requirements: macOS 12+, WeChat at `/Applications/WeChat.app`, Python 3.10+, Pillow
- Limitations: breaks after WeChat updates (re-run `repair`), push notifications may be unreliable
- Based on the well-known copy + bundle-id + ad-hoc signing method documented by [@koffuxu](https://x.com/koffuxu/status/2043110831584690427)

### 4) `wechat-daily`
WeChat digital-asset assistant for macOS:
- Decrypts WeChat Mac 4.x local SQLCipher databases (AES-256-CBC)
- Extracts chats, Moments (`sns.db`), and Favorites (`favorite.db`)
- Generates AI-powered chat digests, Moments reports, Favorites cleanup notes, customer follow-up drafts, and relationship review prompts
- First-time onboarding introduces 3 categories and 9 playbooks: chat records, Moments, and Favorites
- Configurable monitoring for groups, contacts, Moments targets, and Favorites cleanup preferences
- First-time setup guided via frida key extraction
- Typical triggers: "日报", "微信日报", "朋友圈日报", "收藏夹整理", "客户跟进", "数字资产沉淀", "wechat-daily"
- Requirements: macOS, WeChat Mac 4.x, Python 3.9+, `pycryptodome`, `zstandard`
- See [wechat-daily/README.md](./wechat-daily/README.md) for full documentation

## Project Structure

```text
yichen-skills/
├─ summary/
│  └─ skill.md
├─ x-publisher/
│  ├─ cookies.template.json
│  ├─ scripts/
│  ├─ x-article-publisher/
│  │  ├─ cookies.template.json
│  │  ├─ skill.md
│  │  ├─ scripts/
│  │  └─ references/
│  └─ (article-focused only)
├─ wechat-daily/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ extract_keys.py
│     ├─ wechat_daily.py
│     └─ list_contacts.py
├─ mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## Requirements

- Claude Code / Codex CLI (with local skill loading)
- Playwright MCP (required by `x-publisher`)
- Python 3.9+
- Dependencies:
  - Windows: `pip install Pillow pywin32 clip-util`
  - macOS: `pip install Pillow pyobjc-framework-Cocoa`

## Installation

Copy this repository into your local skills directory:

- Common Claude path: `~/.claude/skills/`
- Common Agents path: `~/.agents/skills/`
- Custom skill path also works if your setup supports it

Keep directory names unchanged:
- `summary`
- `x-publisher`
- `wechat-daily`
- `mac-wechat-dual-open`

## Quick Start (3 Minutes)

### A) Enable `summary`

1. Ensure `summary/skill.md` is available in your loaded skills path
2. Start a new session and run `/summary`
3. Confirm output is written to your Obsidian folder (example paths may use `<OBSIDIAN_VAULT>/...`)

### B) Enable `x-publisher`

1. Configure cookies (see next section)
2. Confirm Playwright MCP is connected
3. Use by scenario:
   - Long article: trigger `x-article-publisher`

### C) Enable `mac-wechat-dual-open`

1. Install Python dependency: `pip3 install Pillow`
2. In Claude Code, say "帮我微信双开" or "WeChat dual open"
3. The skill will create a second WeChat at `~/Applications/WeChat-2.app` with a blue icon
4. See `mac-wechat-dual-open/SKILL.md` for all commands

### D) Enable `wechat-daily`

1. Install Python dependencies: `pip3 install pycryptodome zstandard`
2. In Claude Code or Codex, say "日报", "朋友圈日报", or "收藏夹整理"
3. First run will guide you through key extraction and choosing among the 9 playbooks
4. If unsure, start with the recommended trio: group chat digest + Moments report + Favorites cleanup
5. Subsequent runs generate the selected digest, report, or draft workflow
6. See [wechat-daily/README.md](./wechat-daily/README.md) for details

## Cookie Setup (Required)

This repo does not include real credentials and only provides templates.

1. Copy template files:
   - `x-publisher/cookies.template.json` -> `x-publisher/cookies.json`
   - `x-publisher/x-article-publisher/cookies.template.json` -> `x-publisher/x-article-publisher/cookies.json`
2. Fill in your own `auth_token` and `ct0`
3. Never commit real `cookies.json`

`.gitignore` already ignores `**/cookies.json`.

## Security Notes

- Real token/cookie values are not included
- History/cache artifacts are excluded from tracking
- Personal absolute paths are replaced with generic forms

If you ever exposed real cookies in a public repo, rotate them immediately.

## FAQ

### Why doesn't a skill trigger?
- Verify the skill folder is in your actually loaded skill path
- Restart the session and retry
- Check `name` and `description` in `skill.md` frontmatter

### Why did X publishing fail?
- Check whether cookies expired
- Verify Playwright MCP connectivity
- Verify local markdown/image paths exist

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
- both `cookies.template.json` files

Do not republish or repackage this repository as a public skill bundle. Always remind users not to publish real credentials or private data.

## Acknowledgments

Parts of the X publishing workflow and engineering practices are adapted with references to:

- `wshuyi/x-article-publisher-skill`
  - Repo: <https://github.com/wshuyi/x-article-publisher-skill>
  - Docs: <https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - License: MIT

The WeChat database decryption approach in `wechat-daily` is adapted from:

- `zhuyansen/wx-favorites-report`
  - Repo: <https://github.com/zhuyansen/wx-favorites-report>
  - Author: zhuyansen
  - License: MIT
  - Specifically: the frida hook method for `CCKeyDerivationPBKDF` key extraction and SQLCipher 4 page-level decryption logic

The WeChat dual-open method in `mac-wechat-dual-open` is based on:

- [@koffuxu](https://x.com/koffuxu) — original tutorial (2026-04): [Mac 微信双开最完美方案](https://x.com/koffuxu/status/2043110831584690427)
- [@MinLiBuilds](https://x.com/MinLiBuilds) — independent confirmation (2026-04)

See `THIRD_PARTY_NOTICES.md` for details.

## Compliance Boundary

- This project is not affiliated with, endorsed by, or sponsored by X (Twitter) or WeChat (Tencent).
- This repository is for personal learning and non-commercial personal workflow use only.
- Commercial use, client delivery, resale, paid redistribution, marketplace packaging, course bundling, and internal company deployment are prohibited without prior written permission.
- Users are responsible for complying with X platform terms/policies and local laws.
- `wechat-daily` is for personal use only — only decrypt and read your own chat data.
- Never upload real account credentials (for example, `cookies.json`, `wechat-keys.json`) to public repositories.
- Never upload real chat records, WeChat databases, customer data, private notes, API keys, local paths, or other personal data.

## License

Personal Learning and Non-Commercial Use License. See [LICENSE](./LICENSE).
