# Test Plan

All tests use temporary directories and synthetic SQLite databases generated locally. No fixture contains real accounts, conversations, paths, credentials, or media.

## Acceptance coverage

1. `--vault-root` is mandatory and no common user directory is scanned.
2. `status` returns only redacted metadata.
3. Content-bearing commands fail without `--allow-private-content`.
4. Sessions and contacts are queried from a synthetic, already-decrypted Vault.
5. History and global search return only text content and never expose internal account identifiers.
6. Statistics return counts and redacted display labels.
7. Wrong roots, paths that escape the Vault, links/reparse points, unsupported schemas, and corrupt SQLite files fail closed.
8. WAL-backed committed rows are visible from a stable temporary snapshot without writing beside the source database.
9. A source that changes during snapshot creation fails closed and no cached result is returned.
10. Ambiguous contact names return a selection error rather than choosing the first match.
11. Non-text message bodies are omitted; image and audio payloads are not parsed.
12. Output and errors do not disclose absolute paths, Windows usernames, internal account identifiers, or secrets.
13. Source files contain no prohibited runtime capability or disallowed dependency.
14. `git diff --check` and the complete unit-test suite pass on Windows.

## Commands

```powershell
python yichen-wechat-windows-readonly/tests/fixtures/build_synthetic_vault.py --output <temporary-directory>
python -m unittest discover -s yichen-wechat-windows-readonly/tests -v
git diff --check
```
