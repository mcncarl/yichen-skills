# yichen-skills

English | [中文](./README.zh.md)

A skill collection for creators who want to streamline writing, X Articles draft publishing, WeChat digital-asset capture, and local workflows with Claude Code and Codex.

## What This Repo Does

1. Turn Claude Code conversations into structured Obsidian notes (`summary`)
2. Upload Obsidian/Markdown articles to X Articles drafts (`x-article-draft-uploader`)
3. Turn WeChat chats, Moments, and Favorites into AI-powered digital assets (`wechat-local-vault`)
4. Run two WeChat accounts on one Mac with a distinct blue icon (`mac-wechat-dual-open`)
5. Fetch benchmark videos/posts from Douyin and Xiaohongshu (`douyin-fetcher`, `xiaohongshu-fetch`)
6. Transcribe, caption, and rough-cut talking-head videos with Volcengine ASR (`volc-asr`)
7. Diagnose benchmark videos and creator scripts (`yichen-video-content`, `dbs-content`)
8. Hand off rough cuts to Jianying/CapCut for final editing (`jianying-editor`)

## Included Skills

### 1) `summary`
- Purpose: extract key insights from the current conversation and save to Obsidian
- Typical triggers: `/summary`, "save conversation", "export highlights"
- Capabilities:
  - Filters out low-value chat transitions
  - Produces structured notes (Background, Core Content, Solution, Key Points, Related)
  - Useful for long-term knowledge accumulation

### 2) `x-article-draft-uploader`
Upload Obsidian/Markdown long-form articles to X Articles drafts:
- Uses the first image as the X Article cover
- Converts Markdown into rich text for the X editor
- Inserts body images at their original Markdown positions
- Runs in an independent Playwright browser so it does not take over the user's current Chrome window
- Reuses Chrome login state through temporary exported cookies
- Saves drafts only and does not click the final `发布` button

See [x-article-draft-uploader/README.md](./x-article-draft-uploader/README.md) for installation, privacy notes, and troubleshooting.

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

### 4) `wechat-local-vault`
WeChat digital-asset assistant for macOS:
- Decrypts WeChat Mac 4.x local SQLCipher databases (AES-256-CBC)
- Extracts chats, Moments (`sns.db`), and Favorites (`favorite.db`)
- Generates AI-powered chat digests, Moments reports, Favorites cleanup notes, customer follow-up drafts, and relationship review prompts
- First-time onboarding introduces 3 categories and 9 playbooks: chat records, Moments, and Favorites
- Configurable monitoring for groups, contacts, Moments targets, and Favorites cleanup preferences
- First-time setup guided via frida key extraction
- Typical triggers: "微信解析", "微信全量", "微信增量", "导出聊天", "朋友圈解析", "收藏夹整理", "客户跟进", "wechat-local-vault"
- Requirements: macOS, WeChat Mac 4.x, Python 3.9+, `pycryptodome`, `zstandard`
- See [wechat-local-vault/README.md](./wechat-local-vault/README.md) for full documentation

### 5) `douyin-fetcher`
Fetch Douyin video metadata and download an MP4 through Playwright network interception:
- Supports `/video/<id>` links and selected modal-style URLs
- Writes a compact `.metadata.json` next to the downloaded video
- Use `--metadata-only` to validate a link without downloading media

### 6) `xiaohongshu-fetch`
Fetch Xiaohongshu video/image posts into local files:
- Parses `window.__INITIAL_STATE__`
- Downloads video, subtitles, images, and metadata when available
- Keeps cookies, Feishu AppToken/TableID, and target table IDs out of the repo

### 7) `volc-asr`
Transcribe local audio/video files and generate rough cuts:
- Uses environment variables for Volcengine ASR and TOS configuration
- Produces transcript text, SRT subtitles, ASR cache, and optional rough-cut MP4
- Requires explicit user approval before cleaning temporary files

### 8) `yichen-video-content`
Analyze benchmark video transcripts:
- Breaks a transcript down sentence by sentence
- Labels each sentence's role
- Produces a structured imitation and improvement report

### 9) `dbs-content`
Diagnose content ideas and scripts:
- Checks whether a topic, format, expression, and platform fit
- Gives rewrite direction without replacing the creator's own writing

### 10) `jianying-editor`
Guide Jianying/CapCut desktop finishing:
- Confirms media files and imports rough cuts
- Handles timeline placement, subtitles, visual polishing, and export notes
- Leaves automatic rough-cut logic to `volc-asr`

## Project Structure

```text
yichen-skills/
├─ summary/
│  └─ SKILL.md
├─ x-article-draft-uploader/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  └─ scripts/
│     ├─ export_x_cookies_from_chrome.py
│     ├─ parse_markdown.py
│     └─ upload_markdown_to_x_article.py
├─ wechat-local-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ decrypt_all_dbs.py
│     ├─ export_chat.py
│     ├─ extract_keys.py
│     ├─ list_contacts.py
│     ├─ search_sns.py
│     └─ wechat_digest.py
├─ mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ douyin-fetcher/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ download.py
├─ xiaohongshu-fetch/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ fetch.py
├─ volc-asr/
│  ├─ SKILL.md
│  └─ scripts/
│     └─ transcribe.py
├─ yichen-video-content/
│  ├─ SKILL.md
│  └─ references/
│     └─ title-formulas.md
├─ dbs-content/
│  └─ SKILL.md
├─ jianying-editor/
│  └─ SKILL.md
├─ README.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## Requirements

- Claude Code / Codex CLI (with local skill loading)
- Python Playwright (required by `x-article-draft-uploader`)
- Python 3.9+
- Dependencies:
  - X article drafts: `pip install playwright pycryptodome && python3 -m playwright install chromium`
  - WeChat local vault: `pip install pycryptodome zstandard`
  - WeChat dual open: `pip install Pillow`
  - Douyin fetcher: `pip install playwright requests && python3 -m playwright install chromium`
  - Xiaohongshu fetcher: `pip install requests`
  - Volc ASR rough cut: `pip install requests` plus local `ffmpeg` / `ffprobe`

## Installation

Copy this repository into your local skills directory:

- Common Claude path: `~/.claude/skills/`
- Common Agents path: `~/.agents/skills/`
- Custom skill path also works if your setup supports it

Keep directory names unchanged:
- `summary`
- `x-article-draft-uploader`
- `wechat-local-vault`
- `mac-wechat-dual-open`
- `douyin-fetcher`
- `xiaohongshu-fetch`
- `volc-asr`
- `yichen-video-content`
- `dbs-content`
- `jianying-editor`

## Quick Start (3 Minutes)

### A) Enable `summary`

1. Ensure `summary/SKILL.md` is available in your loaded skills path
2. Start a new session and run `/summary`
3. Confirm output is written to your Obsidian folder (example paths may use `<OBSIDIAN_VAULT>/...`)

### B) Enable `x-article-draft-uploader`

1. Install Python Playwright: `pip3 install playwright pycryptodome && python3 -m playwright install chromium`
2. Make sure Chrome is already logged in to X
3. Say "upload this Markdown article to X Articles draft" or run the script directly
4. The skill creates a fresh draft, preserves the first image as the cover, and inserts body images in place
5. See [x-article-draft-uploader/README.md](./x-article-draft-uploader/README.md) for commands

### C) Enable `mac-wechat-dual-open`

1. Install Python dependency: `pip3 install Pillow`
2. In Claude Code, say "帮我微信双开" or "WeChat dual open"
3. The skill will create a second WeChat at `~/Applications/WeChat-2.app` with a blue icon
4. See `mac-wechat-dual-open/SKILL.md` for all commands

### D) Enable `wechat-local-vault`

1. Install Python dependencies: `pip3 install pycryptodome zstandard`
2. In Claude Code or Codex, say "微信解析", "导出聊天", or "收藏夹整理"
3. First run will guide you through key extraction and choosing among the 9 playbooks
4. If unsure, start with the recommended trio: group chat digest + Moments report + Favorites cleanup
5. Subsequent runs generate the selected digest, report, or draft workflow
6. See [wechat-local-vault/README.md](./wechat-local-vault/README.md) for details

### E) Enable the creator video workflow

1. Install Playwright, requests, and ffmpeg
2. Use `douyin-fetcher` or `xiaohongshu-fetch` to save benchmark media locally
3. Use `volc-asr` to transcribe or rough-cut recorded talking-head videos
4. Use `yichen-video-content` and `dbs-content` to diagnose benchmark transcripts and drafts
5. Use `jianying-editor` for final Jianying/CapCut import, subtitle, polish, and export steps

## X Cookie Handling

This repo does not include real credentials or cookie templates.

`x-article-draft-uploader` exports current X cookies from the user's local Chrome profile into a temporary Playwright cookie file:

```bash
python3 ~/.codex/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py --output /tmp/x_current_cookies.json
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
- `x-article-draft-uploader/README.md`

Do not republish or repackage this repository as a public skill bundle. Always remind users not to publish real credentials or private data.

## Acknowledgments

Parts of the X Articles draft workflow and Markdown parsing approach are adapted with references to:

- `wshuyi/x-article-publisher-skill`
  - Repo: <https://github.com/wshuyi/x-article-publisher-skill>
  - Docs: <https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - License: MIT

The WeChat database decryption approach in `wechat-local-vault` is adapted from:

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
- `wechat-local-vault` is for personal use only — only decrypt and read your own chat data.
- Never upload real account credentials (for example, `cookies.json`, `wechat-keys.json`) to public repositories.
- Never upload real chat records, WeChat databases, customer data, private notes, API keys, local paths, or other personal data.

## License

Personal Learning and Non-Commercial Use License. See [LICENSE](./LICENSE).
