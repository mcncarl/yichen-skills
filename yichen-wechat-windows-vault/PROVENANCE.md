# Provenance and clean implementation statement

This directory is a new Windows implementation created after the earlier Windows proposal was rejected. It does not contain or invoke `wx-cli`, and no code from that rejected implementation was reused.

## File lineage

- `scripts/windows_memory.py`, `windows_vault.py`, `secret_store.py`, `sqlcipher_codec.py`, and `wal_snapshot.py` are new implementations written for this contribution.
- SQLCipher geometry and HMAC behavior were implemented from the public Tencent SQLCipher source, Tencent WCDB documentation, Zetetic SQLCipher documentation, and SQLite's official WAL format documentation.
- Windows process-memory and DPAPI calls use Microsoft-documented APIs through Python `ctypes`.
- `scripts/vault_cli.py` is adapted from this repository's own `yichen-wechat-local-vault/scripts/vault_cli.py` so that Windows and Mac expose the same read-only query commands. Its configuration and data-root handling were changed for Windows.
- No Tencent, Zetetic, SQLite, Microsoft, `cryptography`, or `zstandard` source code is copied or vendored here.

## Deliberately excluded behavior

- no spawning or relaunching Weixin;
- no process termination, suspension, resume, debugging, injection, hooking, remote allocation, or memory writes;
- no UI automation or message sending;
- no third-party Weixin CLI or binary;
- no hard-coded key, salt, account identifier, process address, or private test data;
- no silent key capture or plaintext export.

## Validation evidence expected for a release

1. Windows CI passes all synthetic codec, WAL, DPAPI, query, export, and safety tests.
2. `skill-creator` metadata validation passes.
3. A current official Windows Weixin build is diagnosed without exposing account data.
4. With explicit consent, at least one real active database key is captured and validates.
5. After the user manually exits Weixin, every discovered DB/WAL/SHM set is snapshotted, all required capability databases refresh into a promoted generation, optional gaps are explicitly disclosed, and query smoke tests pass.

Items 4 and 5 are local-only evidence and must never publish keys, database files, account paths, or chat content.
