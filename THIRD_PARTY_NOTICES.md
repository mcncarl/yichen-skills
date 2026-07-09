# THIRD_PARTY_NOTICES

Last updated: 2026-05-09

This repository references and adapts ideas/workflows from external projects.

## 1) wshuyi/x-article-publisher-skill

- Upstream: https://github.com/wshuyi/x-article-publisher-skill
- Referenced docs: https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md
- License: MIT (copyright notice: wshuyi)
- Local copy of license: `licenses/wshuyi-x-article-publisher-skill-LICENSE.txt`
- Usage in this repo:
  - Workflow and X Articles editor automation references
  - Adapted Markdown parsing and rich-text conversion ideas now used by `x-article-draft-uploader`

## 2) JimLiu/baoyu-skills

- Upstream: https://github.com/JimLiu/baoyu-skills
- License declaration source: https://github.com/JimLiu/baoyu-skills/blob/main/README.md#license
- Repository state checked on 2026-02-11:
  - README contains `## License` and `MIT` statement
  - No top-level LICENSE file found in repository root at check time
- Local notice: `licenses/JimLiu-baoyu-skills-license-note.txt`
- Usage in this repo:
  - Referenced workflow/experience for Claude skills packaging and usage patterns

## 3) zhuyansen/wx-favorites-report

- Upstream: https://github.com/zhuyansen/wx-favorites-report
- Author: zhuyansen
- License: MIT
- Usage in this repo (`wechat-local-vault`):
  - Frida hook method for intercepting `CCKeyDerivationPBKDF` (Apple CommonCrypto PBKDF2) to extract SQLCipher encryption keys at runtime
  - SQLCipher 4 page-level decryption logic (AES-256-CBC, page_size=4096, reserve=80)
  - The approach of codesign-bypass to remove Hardened Runtime for frida injection
- What was adapted:
  - The frida JS hook script structure was adapted from the original project's key extraction methodology
  - The database decryption function was implemented based on the documented decryption parameters
  - The overall workflow (codesign → frida spawn → hook → capture keys → match to DB files) follows the same approach

## 4) wechat-article/wechat-article-exporter

- Upstream: https://github.com/wechat-article/wechat-article-exporter
- License: MIT
- Usage in this repo (`wechat-mp-batch-exporter`):
  - Referenced workflow for WeChat Official Account search, history sync, multi-format export, and enhanced metric/comment export.
  - The skill points users to their own local or hosted `wechat-article-exporter` instance instead of vendoring upstream code.
- What was copied:
  - No upstream source code is vendored in this repository.
  - The public skill only includes local wrapper scripts, runbooks, output schemas, safety gates, and attribution links.

## 5) wechat-article/wxdown-service

- Upstream: https://github.com/wechat-article/wxdown-service
- Documentation: https://docs.mptext.top/advanced/wxdown-service
- License: MIT, according to the upstream documentation footer.
- Usage in this repo (`wechat-mp-batch-exporter`):
  - Referenced the credential-capture workflow needed for read counts, likes, shares, comments, and replies.
  - The skill requires explicit user confirmation before any certificate, proxy, credential, or WeChat desktop step.
- What was copied:
  - No upstream source code is vendored in this repository.
  - `start_wxdown_service.py` only starts a user-provided local checkout path and does not modify system proxy settings.

## Notes

- This repository maintains its own license (`LICENSE`) for original contributions. It is personal-learning and non-commercial only.
- The upstream projects listed above retain their original licenses and copyrights.
- Upstream licenses and notices should be preserved when redistributing derived works.
- `wechat-local-vault` is an independent implementation that adapts specific technical approaches from `wx-favorites-report`. It does not contain any code directly copied from the upstream project.
- `wechat-mp-batch-exporter` references workflows from `wechat-article-exporter` and `wxdown-service`, but does not include their source code, credentials, cached browser data, or downloaded article archives.
- `x-article-draft-uploader` references workflow and Markdown parsing ideas from `wshuyi/x-article-publisher-skill`; it stores no real credentials and writes cookies only to temporary runtime files.
- `summary` and the broader skill packaging conventions reference public Claude skill community practices, including JimLiu/baoyu-skills.
- `mac-wechat-dual-open` references public X/Twitter discussion and implements the copy + bundle-id + ad-hoc signing workflow locally.
- Do not remove this file when forking for personal study. It is the attribution record for borrowed ideas, workflows, and license notices.
