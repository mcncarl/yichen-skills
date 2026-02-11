# yichen-skills

English | [中文](./README.zh.md)

A skill collection for creators who want to streamline writing and publishing workflows with Claude Code.

## What This Repo Does

1. Turn Claude Code conversations into structured Obsidian notes (`summary`)
2. Publish Obsidian/Markdown content to X (`x-publisher`)
3. Provide a Windows-friendly X Articles workflow with a very high success rate for article uploads

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

## Quick Start (3 Minutes)

### A) Enable `summary`

1. Ensure `summary/skill.md` is available in your loaded skills path
2. Start a new session and run `/summary`
3. Confirm output is written to your Obsidian folder (example paths may use `E:/obsidian/...`)

### B) Enable `x-publisher`

1. Configure cookies (see next section)
2. Confirm Playwright MCP is connected
3. Use by scenario:
   - Long article: trigger `x-article-publisher`

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
- `E:/obsidian/...` is only an example

## For Redistributors

If you fork or redistribute, keep at least:
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- both `cookies.template.json` files

And always remind users not to publish real credentials.

## Acknowledgments

Parts of the X publishing workflow and engineering practices are adapted with references to:

- `wshuyi/x-article-publisher-skill`
  - Repo: <https://github.com/wshuyi/x-article-publisher-skill>
  - Docs: <https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - License: MIT

See `THIRD_PARTY_NOTICES.md` for details.

## Compliance Boundary

- This project is not affiliated with, endorsed by, or sponsored by X (Twitter).
- Users are responsible for complying with X platform terms/policies and local laws.
- Never upload real account credentials (for example, `cookies.json`) to public repositories.

## License

MIT
