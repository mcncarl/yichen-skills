# Yichen WeChat Windows Vault

An independent Windows implementation of the repository's WeChat local-vault experience. It supports finite, version-pinned key capture; verified SQLCipher decryption; incremental private-vault refresh; and read-only queries for sessions, contacts, group members, history, search, statistics, exports, Favorites, Moments, and message-resource metadata.

## Requirements

- Windows 10 or 11
- Python 3.11+
- Desktop WeChat 4.x with an exact supported profile
- Data belonging to the current user, with explicit authorization

## Install

```powershell
Set-Location yichen-wechat-windows-vault
.\scripts\setup.ps1
```

This creates an isolated environment under `%LOCALAPPDATA%\yichen-wechat-windows-vault`. It does not modify Codex, Hermes, MCP, WeChat, logon tasks, or system configuration.

## Diagnose, capture, and refresh

Always provide the database root explicitly:

```powershell
$Python = Join-Path $env:LOCALAPPDATA "yichen-wechat-windows-vault\venv\Scripts\python.exe"
& $Python .\scripts\diagnose.py --db-root "C:\explicit\path\to\db_storage"
.\scripts\capture_keys_on_demand.ps1 -DbRoot "C:\explicit\path\to\db_storage" -Duration 20
```

Keep WeChat running and open the needed area during the finite capture window. If no new database derivation occurs, the command may correctly report zero captured candidates; retry during a normal WeChat restart or while opening a database-backed feature. Unknown DLL hashes fail closed.

## Query

```powershell
$Root = Join-Path $env:LOCALAPPDATA "yichen-wechat-windows-vault\vault\decrypted"
& $Python .\scripts\vault_cli.py --decrypted-root $Root sessions --limit 20
& $Python .\scripts\vault_cli.py --decrypted-root $Root history "chat name" --limit 50
& $Python .\scripts\vault_cli.py --decrypted-root $Root search "keyword" --start-time 2026-08-01
& $Python .\scripts\vault_cli.py --decrypted-root $Root stats "chat name"
```

Run `vault_cli.py --help` and the subcommand help for all options. Exports must point to a deliberate private destination.

## Scope

The Windows implementation keeps the Mac Skill's command-level concepts and interaction model. Its Windows process integration, version profile, DPAPI storage, database refresh, schema adapters, and tests were implemented independently. See [PROVENANCE.md](PROVENANCE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
