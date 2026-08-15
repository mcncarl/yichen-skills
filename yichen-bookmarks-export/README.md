# yichen-bookmarks-export

A read-only Skill for exporting the user's explicitly authorized Xiaohongshu favorites, Douyin favorites, and X/Twitter bookmarks as validated local URL files.

## Capabilities

- Reuses the user's current authenticated Chrome session for Xiaohongshu and Douyin.
- Scrolls to a stable bottom, extracts strict content IDs, deduplicates, and reports accessible counts.
- Optionally uses a separately installed Field Theory `ft` build marked `graphql-only` for X bookmark sync and local-index export.
- Validates blanks, duplicates, malformed rows, and small accessibility samples without printing private URLs.
- Produces a privacy-safe handoff to `yichen-content-archive`; it never starts media download automatically.

## Safety

Every private collection read requires current-task authorization for the exact platform and scope. The Skill is read-only, does not export browser credentials, does not overwrite existing exports by default, and does not bypass access controls, CAPTCHA, rate limits, or platform security measures.

## Optional X dependency

The X route calls [afar1/fieldtheory-cli](https://github.com/afar1/fieldtheory-cli) as an external runtime. No Field Theory source, binary, private Query ID, Cookie, credential, or bookmark data is bundled. The required `graphql-only` marker refers to a user-maintained compatibility and safety overlay, not an official upstream release name. See [the local MIT license copy](../licenses/afar1-fieldtheory-cli-LICENSE.txt) and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Installation

Install the Web Research family together, or copy this directory into a Skill path supported by your host:

- `~/.agents/skills/yichen-bookmarks-export/`
- `~/.claude/skills/yichen-bookmarks-export/`
- `~/.codex/skills/yichen-bookmarks-export/`

For Xiaohongshu or Douyin, the host must provide the `chrome:control-chrome` capability. For X, install and authenticate a compatible `ft` runtime separately.

## Validation

From the repository root:

```bash
python3 yichen-bookmarks-export/tests/test_skill_contract.py
python3 yichen-web-research/scripts/validate_family.py
```
