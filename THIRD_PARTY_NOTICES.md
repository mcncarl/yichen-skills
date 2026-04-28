# THIRD_PARTY_NOTICES

Last updated: 2026-04-28

This repository references and adapts ideas/workflows from external projects.

## 1) wshuyi/x-article-publisher-skill

- Upstream: https://github.com/wshuyi/x-article-publisher-skill
- Referenced docs: https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md
- License: MIT (copyright notice: wshuyi)
- Local copy of license: `licenses/wshuyi-x-article-publisher-skill-LICENSE.txt`
- Usage in this repo:
  - Workflow and publishing approach references
  - Adapted skill instructions and script-level implementation ideas

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
- Usage in this repo (`wechat-daily`):
  - Frida hook method for intercepting `CCKeyDerivationPBKDF` (Apple CommonCrypto PBKDF2) to extract SQLCipher encryption keys at runtime
  - SQLCipher 4 page-level decryption logic (AES-256-CBC, page_size=4096, reserve=80)
  - The approach of codesign-bypass to remove Hardened Runtime for frida injection
- What was adapted:
  - The frida JS hook script structure was adapted from the original project's key extraction methodology
  - The database decryption function was implemented based on the documented decryption parameters
  - The overall workflow (codesign → frida spawn → hook → capture keys → match to DB files) follows the same approach

## Notes

- This repository maintains its own license (`LICENSE`) for original contributions. It is personal-learning and non-commercial only.
- The upstream projects listed above retain their original licenses and copyrights.
- Upstream licenses and notices should be preserved when redistributing derived works.
- `wechat-daily` is an independent implementation that adapts specific technical approaches from `wx-favorites-report`. It does not contain any code directly copied from the upstream project.
- `x-publisher` references workflow and implementation ideas from `wshuyi/x-article-publisher-skill`; local cookie templates contain placeholders only, not real credentials.
- `summary` and the broader skill packaging conventions reference public Claude skill community practices, including JimLiu/baoyu-skills.
- `mac-wechat-dual-open` references public X/Twitter discussion and implements the copy + bundle-id + ad-hoc signing workflow locally.
- Do not remove this file when forking for personal study. It is the attribution record for borrowed ideas, workflows, and license notices.
