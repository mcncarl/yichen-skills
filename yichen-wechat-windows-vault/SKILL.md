---
name: yichen-wechat-windows-vault
description: "From WeChat local vault: query sessions, contacts, history, search, stats, Favorites, Moments; decode voice/image messages; batch-process media. Use when user wants to search Windows WeChat chats, transcribe voice messages, recognize chat images, or maintain a private local WeChat knowledge vault."
---

# Windows WeChat Local Vault

Use the bundled scripts and MCP tools to access only the current user's own local WeChat data. Keep live databases read-only and write all derived data to the private vault.

## Privacy Rules

- Never print, return, commit, or upload database or image keys.
- Never copy plaintext databases, transcripts, or decoded media into a repository or cloud folder.
- Keep keys and derived data under `%LOCALAPPDATA%\wechat-windows-vault`.
- Treat `xwechat_files\*\db_storage` and `msg\attach` as read-only.
- Refuse requests involving another person's account or data without authorization.

## Setup

Install the skill directory at any path (e.g. `~/.workbuddy/skills/wechat-windows-vault/` for WorkBuddy, or any directory for other MCP clients). The isolated runtime (venv, node-runtime, whisper model) lives under `%LOCALAPPDATA%\wechat-windows-vault\`.

Run `scripts\setup.ps1` to auto-create the venv, install dependencies, and register the MCP server. For manual configuration, see [README.md](README.md).

The MCP server uses the local faster-whisper `small` model for Chinese voice transcription and loads it only when first requested. If the local model or its native runtime is unavailable, text queries and image extraction must remain usable and the voice result must report `transcript_error`.

Verify installation with the private runtime Python:

```powershell
$VaultPython = Join-Path $env:LOCALAPPDATA "wechat-windows-vault\venv\Scripts\python.exe"
& $VaultPython scripts\self_test.py
& $VaultPython scripts\diagnose.py
```

Read [references/compatibility.md](references/compatibility.md) before key capture or when diagnostics report an unknown fingerprint.

## First Capture

1. Back up the detected `xwechat_files` directory.
2. Keep desktop WeChat logged in.
3. Run `capture_keys.py --duration 120` with the private runtime Python.
4. During capture, open chats, Favorites, Moments, and image messages needed by the user.
5. Run `refresh_vault.py` and confirm all required databases report `ok`.

Never bypass fingerprint or prologue verification for an unsupported WeChat build.

## Preferred MCP Workflow

Use MCP tools instead of shell or direct filesystem access when they are available.

- `wechat_vault_query`: query status, sessions, contacts, history, search, statistics, Favorites, and Moments. Use bounded limits and explicit dates for large requests.
- `wechat_vault_media`: decode one voice or image identified by `db` and `local_id`.
- `wechat_vault_media_batch`: process at most five media messages and return `next_offset`. Continue with `offset=next_offset` until `done=true` or preserve the offset for the next turn.
- `wechat_vault_image`: load only a decoded image inside the private media cache into visual context.

For voice messages, use `transcript` and report `transcript_error` explicitly. For images, call `wechat_vault_image` immediately and inspect the returned image. Do not claim image recognition when extraction failed.

If an image returns `retry_action`, ask the user to open that exact image in desktop WeChat, preferably with “view original,” keep WeChat running, and retry the same offset.

## Long Ranges

Query text with the requested start and end dates. Process media newest-to-oldest with `wechat_vault_media_batch`, five items per batch. Summarize completed batches and retain `next_offset`; do not increase the per-batch cap to avoid model and gateway timeouts.

Cached transcripts and decoded images are reused automatically. “All records” means all records currently present in the user's local Windows account; server-only, deleted, expired, or never-synchronized data cannot be recovered by this skill.

## Failure Rules

- `unknown Weixin.dll fingerprint`: stop; add and validate a version profile before capture.
- `no attachable Weixin process`: confirm WeChat is running and retry from an elevated terminal if required.
- `0 verified keys`: keep WeChat active during capture; do not claim decryption support.
- `database is locked`: retry after WeChat is idle; never repair or modify the live database.
- `verified Windows WeChat V2 image key not found`: ask the user to open the image and retry.
