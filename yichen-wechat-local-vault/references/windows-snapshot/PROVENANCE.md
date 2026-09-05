# Provenance and maintainer-takeover record

## Scope decision

The original contribution commit `fe589d60d719a5304469b583cf1a48e863a8348d` was based directly on upstream `mcncarl/yichen-skills` commit `2526175fba7e67b2ae6ab89461c48d32a3ce718b` and submitted in PR #14 on 2026-08-25. On 2026-08-26 the upstream maintainer took over the branch to address review findings while preserving the contributor-authored commit and grant.

The resulting feature excludes the extraction and decryption functionality proposed in the earlier PR #13. It accepts only a user-authorized, already-decrypted, detached plaintext snapshot.

## Sources consulted

| Source | Pinned reference | Accessed | Use |
|---|---|---:|---|
| `mcncarl/yichen-skills` | commit `2526175fba7e67b2ae6ab89461c48d32a3ce718b` | 2026-08-25 | Repository conventions and the existing Mac reader's structure, `Msg_<md5>` / `Name2Id` query vocabulary, column mappings, and decoding approach |
| Original PR #14 contribution | commit `fe589d60d719a5304469b583cf1a48e863a8348d` | 2026-08-25 | Windows plaintext-snapshot reader, synthetic fixtures, documentation, workflow, and contributor grant used as the takeover starting point |
| Python documentation | Python 3.12 `sqlite3` documentation | 2026-08-25 | SQLite URI and query-only implementation |
| SQLite documentation | `uri.html` and `pragma.html#pragma_query_only` | 2026-08-25 | Read-only/immutable connection contract |
| python-zstandard | release `0.25.0` | 2026-08-25 | Decoding compressed plaintext message fields |

The Windows reader is an adaptation within this repository, not an independently invented replacement for the existing Mac reader. Its acquisition boundary, snapshot validation, path protections, resource bounds, output trust labeling, Windows CI, and experimental documentation are specific to this feature. Synthetic fixtures contain invented identities and messages and do not import production code. They test only the documented supported schema and do not establish broad compatibility with real Windows Weixin 4.x databases.

`CONTRIBUTOR_GRANT.md` was committed by the contributor in `fe589d60d719a5304469b583cf1a48e863a8348d` and is retained unchanged. This provenance record describes repository evidence; it does not make an independent legal determination about rights or validity.

## Excluded exposure

No `wx-cli` or other key-extraction/decryption implementation is included. No extraction, DPAPI, SQLCipher, WAL/SHM recovery, process-access, UI-control, or network module was carried into this branch. No WeChat binary, real decrypted user database, memory dump, key, secret, or private chat fixture is included.
