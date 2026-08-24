# Security and privacy model

## Protected assets

- Weixin SQLCipher keys
- encrypted and plaintext Weixin databases
- account paths and identifiers
- chat, contact, Moments, Favorites, and media metadata

## Trust boundary

The tool runs as the same Windows user who owns the local Weixin profile. It is for personal, authorized local use only. It makes no claim to isolate a plaintext snapshot from malware or another process already running as that user.

## Consent gates

Process-memory capture requires both:

1. explicit approval in the current user task after explaining the data and destination; and
2. the literal `--consent-read-process-memory` flag.

Exports may contain plaintext personal data. Confirm the destination and scope before writing a report.

## Secret handling

- A candidate key is accepted only after SQLCipher HMAC and SQLite-header validation.
- Accepted keys are protected with current-user DPAPI and account-binding entropy.
- Raw keys and salts are never printed.
- Key stores, database snapshots, and normal exports are ignored by repository `.gitignore` patterns.
- Manifests contain fingerprints and hashes, not raw keys.

## Source integrity and rollback

- Source DB/WAL/SHM files are opened only for reading.
- SHM wal-index header copies, native-endian checksums, salt, `maxFrame`, and `nBackfill` are validated before deciding which WAL frames are active. Stale file capacity beyond the validated boundary is never applied.
- Plaintext query connections use SQLite URI `mode=ro` and `PRAGMA query_only`.
- Export writes are atomic and refuse existing destinations unless the caller explicitly supplies `--overwrite`.
- Snapshot promotion is atomic and occurs only after every required capability database passes integrity checks.
- Optional feature stores remain listed as failures in the manifest and never masquerade as decrypted; `all_databases_decrypted` distinguishes zero-gap coverage.
- A generation missing any required capability database never replaces `current.json`.
- Old generations are retained, allowing rollback without destructive commands.

## Version changes

An unknown codec layout, unreadable pointer, HMAC mismatch, stale DPAPI entry, invalid active WAL checksum, invalid SHM state, or required-database SQLite integrity failure is a hard error. A feature-specific optional database that the standard Python SQLite runtime cannot integrity-check is isolated and disclosed instead of aborting the generation. Do not bypass validation or add version-specific absolute addresses. Re-audit the public structures and add tests first.

## Reporting a vulnerability

Follow the repository's maintainer contact policy. Never attach keys, databases, account paths, screenshots of private chats, or full memory dumps to a public issue.
