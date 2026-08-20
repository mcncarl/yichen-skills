---
name: yichen-wechat-windows-vault
description: Capture, decrypt, refresh, and query the current user's authorized local Windows WeChat 4.x vault. Use for Windows chat sessions, contacts, group members, history, search, statistics, exports, Favorites, Moments, or digest-source requests; key capture is finite and version-pinned.
---

# Yichen WeChat Windows Vault

Operate only on the current user's authorized Windows WeChat data. Treat the live database tree as read-only and keep keys, decrypted databases, state, and exports out of repositories.

## Workflow

1. Require an explicit `db_storage` path. Do not search Documents, Desktop, OneDrive, or other user folders.
2. Run `scripts/diagnose.py --db-root <path>` before capture.
3. Run `scripts/setup.ps1` once when the isolated runtime is missing. It does not edit Codex, Hermes, MCP, startup, or WeChat configuration.
4. Use `scripts/capture_keys_on_demand.ps1 -DbRoot <path> -Duration 20` only with authorization to attach to the user's own Weixin process. Keep the window finite. The wrapper selects exactly one process that has `Weixin.dll` loaded.
5. Stop when the DLL fingerprint or function prologue is unknown. Read [references/compatibility.md](references/compatibility.md) before adding a profile.
6. Query only the private decrypted copy with `scripts/vault_cli.py --decrypted-root <path> <command>`.

Use bounded limits and explicit dates for large searches. Prefer `digest-source` for a reusable group-chat material pack and `export` for a direct transcript. Use `resources` only for metadata; this Skill does not decode images or transcribe voice.

## Commands

- `status`, `sessions`, `unread`, `new-messages`
- `contacts`, `members`
- `history`, `search`, `stats`
- `favorites`, `moments`, `resources`
- `export`, `digest-source`

## Invariants

- Never print, return, commit, or upload captured keys.
- Accept a captured candidate only after SQLCipher page-HMAC verification.
- Store verified keys with Windows DPAPI for the current user.
- Never modify a live WeChat database or control the WeChat process.
- Never create persistent hooks, watchers, services, or scheduled tasks.
- Do not claim capture success when the result reports zero verified databases.
- Do not commit private vault files, real chat data, account identifiers, or absolute personal paths.

Read [references/privacy.md](references/privacy.md) when handling real data or exports.
