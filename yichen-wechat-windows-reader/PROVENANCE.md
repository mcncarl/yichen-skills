# Provenance and independent-development record

## Scope decision

This contribution was restarted from upstream `mcncarl/yichen-skills` commit `2e3ea626519a08232871b56fdc899684ca921901` on 2026-08-25. It excludes every extraction and decryption feature from the earlier draft PR #13.

## Sources consulted

| Source | Pinned reference | Accessed | Use |
|---|---|---:|---|
| `mcncarl/yichen-skills` | commit `2e3ea626519a08232871b56fdc899684ca921901` | 2026-08-25 | Repository conventions and the Mac skill's user-facing query vocabulary |
| Python documentation | Python 3.12 `sqlite3` documentation | 2026-08-25 | SQLite URI and query-only implementation |
| SQLite documentation | `uri.html` and `pragma.html#pragma_query_only` | 2026-08-25 | Read-only/immutable connection contract |
| python-zstandard | release `0.25.0` | 2026-08-25 | Decoding compressed plaintext message fields |

Production code was written independently for this contribution. Synthetic fixtures contain invented identities and messages and do not import production code. No WeChat binary, decrypted user database, memory dump, secret, or third-party extraction/decryption implementation is included.

## Excluded exposure

The implementation does not copy code from `wx-cli` or any key-extraction/decryption project. The earlier local draft was used only to identify review failures; no extraction, DPAPI, SQLCipher, WAL/SHM recovery, or process-access module was carried into this branch.
