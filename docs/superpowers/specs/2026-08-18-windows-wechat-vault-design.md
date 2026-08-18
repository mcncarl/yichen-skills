# Windows WeChat Vault Skill Design

## Goal

Publish the supplied Windows WeChat local-vault skill in `mcncarl/yichen-skills` without altering the maintained macOS vault or exposing personal data.

## Scope

- Add a new, self-contained `yichen-wechat-windows-vault/` skill directory from the supplied v0.3.0 archive.
- Preserve the archive's Windows-only implementation, privacy rules, compatibility reference, MCP configuration, and self-test.
- Add concise English and Chinese entries to the repository indexes so users can discover the Windows skill and its OS boundary.
- Add the new directory to the README project trees and the documented stable directory-name lists.

## Deliberate boundaries

- Do not merge this implementation into `yichen-wechat-local-vault`; that directory is macOS-only and uses a different database format, key extraction flow, filesystem layout, and dependencies.
- Do not change existing macOS behavior or installation guidance.
- Do not include keys, live databases, decrypted exports, media caches, credentials, user paths, or chat content.
- Do not claim support for an unlisted WeChat build; the bundled compatibility checks remain authoritative.

## Layout

```text
yichen-wechat-windows-vault/
├─ SKILL.md
├─ README.md
├─ agents/openai.yaml
├─ references/
│  ├─ compatibility.md
│  └─ profile-fixtures.json
└─ scripts/
   ├─ setup.ps1
   ├─ uninstall.ps1
   ├─ capture_keys.py
   ├─ decrypt_databases.py
   ├─ refresh_vault.py
   ├─ diagnose.py
   ├─ self_test.py
   ├─ vault_cli.py
   ├─ vault_common.py
   ├─ wechat_media.py
   ├─ decode_silk.cjs
   ├─ gateway_query.py
   ├─ mcp_server.py
   └─ requirements.txt
```

## Validation

1. Check that the imported file set matches the archive and that no tracked file matches repository secret/database/media exclusions.
2. Run Python syntax compilation for the bundled Windows scripts on the current host; this checks syntax only and does not attach to WeChat or read local user data.
3. Run the archive's profile-fixture validation in an isolated import context; full `self_test.py` is intentionally not expected to pass on macOS because it validates Windows-only dependencies and paths.
4. Review the final diff and README links before committing and opening the PR.
