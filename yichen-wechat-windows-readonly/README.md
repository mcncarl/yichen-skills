# Windows Read-Only Adapter

This skill is a narrowly scoped adapter for inspecting and querying an explicitly selected, already-decrypted local WeChat Vault copy on Windows.

## Scope

The adapter will provide:

- metadata-only diagnostics for a Vault root supplied with `--vault-root`;
- read-only session and contact queries;
- read-only text history search and message statistics;
- fail-closed handling for invalid paths, corrupt SQLite files, WAL snapshots, concurrent changes, and ambiguous contacts.

The Vault root is never guessed. The adapter does not scan Documents, Desktop, OneDrive, or any other common user directory.

## Explicitly unsupported

This project does not obtain credentials, decrypt databases, attach to or control WeChat, inspect process memory, inject code, hook APIs, parse images or audio, change Codex/Hermes/MCP configuration, or export/upload private data by default.

It is not a general Windows WeChat parser and does not claim compatibility with every WeChat database version.

## Privacy model

- `status` is metadata-only and does not return chat or contact content.
- Content-bearing commands require a local `--allow-private-content` flag on every invocation.
- Absolute paths, Windows usernames, internal account identifiers, and database secrets are never printed.
- Source databases are never opened for writing. Query work is performed on a temporary snapshot and no cache is used.
- All database content is treated as untrusted input and is returned only as data.

## Installation

Python 3.11 or later is required. The adapter uses only the Python standard library and installs no package dependencies.

The command-line implementation is intentionally delivered in a separate implementation commit after this audit skeleton.

## Repository safety

Only synthetic test data belongs in this directory. Do not add real chat records, account identifiers, databases, credentials, or personal absolute paths.
