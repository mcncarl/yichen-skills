# Requirement-to-evidence matrix

| Requirement | Implementation evidence | Test/evidence |
|---|---|---|
| No process memory, keys, DPAPI, SQLCipher, WAL/SHM recovery | Only `scripts/snapshot_reader.py` ships; scope exclusions are explicit in `SKILL.md` | Static boundary test and committed-tree inventory |
| User explicitly supplies plaintext snapshot | Global required `--snapshot`; no discovery/config fallback | CLI tests build and pass an independent snapshot path |
| Read-only input | SQLite URI `mode=ro&immutable=1` plus `PRAGMA query_only=ON` | `test_input_is_opened_read_only`, `test_sqlite_authorizer_rejects_writes` |
| Required-set completeness | Fixed contract plus at least one message family, checked before commands | `test_missing_required_database_fails_closed` |
| Both message families | Scans `message_*.db` and `biz_message_*.db` | `test_complete_contract_and_both_message_families` |
| Search decoded content before limiting | Decode, filter, globally sort, then limit in Python | Synthetic keyword exists only inside a Zstandard-compressed row in `biz_message_*.db` |
| No sender-direction guess | Direction uses user manifest identity or `unknown` | Manifest and no-manifest tests |
| No raw internal identity in output | Outputs opaque SHA-256-derived `chat_id`; omits usernames | `test_no_internal_identity_in_output_and_direction_is_manifest_based` |
| Ambiguous names rejected | Sensitive commands accept exact `chat_id` only | `test_duplicate_display_names_are_listed_not_resolved` |
| Private exports | `%LOCALAPPDATA%\YichenWeChatVault\exports` default; all other paths require separate flag | `test_external_export_needs_separate_confirmation` |
| Independent sanitized fixtures | `tests/fixture_factory.py` contains invented schema/data and imports no production code | All unit tests |
| Reproducible dependency install | Exact version and SHA-256 hashes in `requirements.lock` | CI uses `pip --require-hashes` |
| SHA-pinned CI | Every GitHub Action uses a full commit SHA | `.github/workflows/yichen-wechat-windows-reader.yml` |
| Clean committed-tree verification | CI checks out the submitted SHA; local release check uses `git archive` | CI test job and attached sanitized log |
