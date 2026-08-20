# Windows Read-Only Adapter

Windows adapter for explicit, read-only queries against an already-decrypted local WeChat Vault copy.

It is deliberately narrower than a general Windows WeChat parser. The user must select the Vault root, the supported layout must already contain readable SQLite files, and every content-bearing command requires consent on that invocation.

## Supported Vault layout

```text
<vault-root>/
  contact/contact.db
  session/session.db
  message/message_*.db
```

The table semantics follow the clean-baseline `yichen-wechat-local-vault` read-only query interface. Schema mismatches fail closed with a redacted error.

## Requirements and installation

- Windows
- Python 3.11 or later
- no package installation; runtime and tests use only the Python standard library

Do not place a private Vault inside this repository. Keep it in a user-controlled local directory and pass that directory explicitly.

## Usage

Run commands from the repository root. `--vault-root` must be an absolute path.

```powershell
$VaultRoot = 'C:\path\to\already-readable-vault'
$Adapter = 'yichen-wechat-windows-readonly\scripts\windows_readonly_adapter.py'

# Metadata only; no consent flag is needed.
python $Adapter --vault-root $VaultRoot status

# These commands return private local data and require consent every time.
python $Adapter --vault-root $VaultRoot --allow-private-content sessions --limit 20
python $Adapter --vault-root $VaultRoot --allow-private-content contacts --query 'Casey'
python $Adapter --vault-root $VaultRoot --allow-private-content history 'Casey' --limit 100
python $Adapter --vault-root $VaultRoot --allow-private-content search 'review' --limit 100
python $Adapter --vault-root $VaultRoot --allow-private-content stats 'Project Lantern'
```

All output is JSON. Contacts receive an opaque `contact_id`; if a display-name query matches more than one contact, the command returns candidate IDs and requires the caller to choose one.

Dates use ISO 8601. A date without a time is interpreted in UTC; `--end YYYY-MM-DD` includes that entire UTC day.

## Read-only and privacy guarantees

- The adapter never guesses a path and never scans Documents, Desktop, OneDrive, or other common directories.
- Path components that are links or Windows reparse points are rejected.
- The source database and any WAL sidecar are copied to a system temporary directory only after stability checks. Queries open the temporary copy with SQLite `mode=ro` and `query_only` enabled.
- If the source changes while the snapshot is made, the command fails. There is no result cache to fall back to.
- Corrupt files and unsupported schemas fail closed.
- Absolute paths, Windows usernames, internal account identifiers, and database secrets are not returned.
- Stored text is treated as untrusted data and is JSON-serialized, never executed.
- Non-text messages may be counted and type-labelled, but their bodies are always omitted.

## Explicitly unsupported

This project does not obtain credentials, decrypt databases, attach to or control WeChat, inspect process memory, inject code, hook APIs, parse image/audio content, change Codex/Hermes/MCP configuration, or export/upload private data by default.

It does not claim compatibility with every WeChat database version.

## Tests

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest discover -s yichen-wechat-windows-readonly\tests -v
git diff --check
```

The suite creates only fictional databases in temporary directories and covers consent, redaction, path rejection, WAL visibility, corruption, concurrent mutation, fail-closed behavior, ambiguous contacts, read-only source preservation, non-text omission, sessions, contacts, history, search, and statistics.
