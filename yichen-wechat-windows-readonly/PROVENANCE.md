# Provenance

## Contribution boundary

- Clean upstream baseline: `ca8281900412e2256e5a45f4d6995fa340af5a71` from `mcncarl/yichen-skills`.
- Authorization: the repository author approved a new, clean, reduced-scope Windows contribution, as recorded in the contributor's private execution handoff.
- Functional and documentation reference: the clean-baseline `yichen-wechat-local-vault` documentation and its read-only query entry point only.
- Excluded implementation sources: every earlier Windows implementation and audit bundle, and every third-party Windows WeChat extraction/decryption implementation.

Earlier private Windows archives were inspected separately only to audit prohibited names, dependencies, and direct file lineage. That audit happened after this contribution was written. No archived implementation was copied, translated, adapted, or used as a design or code source. Third-party Windows WeChat extraction/decryption source was not inspected.

## File-by-file record

| File | Origin |
| --- | --- |
| `README.md` | New text written for this contribution from the approved scope and safety requirements. |
| `SKILL.md` | New minimal skill instructions written for this contribution from the approved scope and safety requirements. |
| `PROVENANCE.md` | New audit record written for this contribution. |
| `THIRD_PARTY.md` | New dependency and license record written for this contribution. |
| `tests/README.md` | New test plan derived from the approved acceptance gates. |
| `tests/fixtures/README.md` | New synthetic-fixture policy written for this contribution. |
| `tests/fixtures/build_synthetic_vault.py` | New Python standard-library fixture generator. Table and command semantics are limited to the clean-baseline Mac skill's read-only query interface. All records are fictional. |
| `scripts/windows_readonly_adapter.py` | New Python standard-library implementation written for this contribution. Command and table semantics use only the clean-baseline Mac skill's read-only query interface; Windows path, consent, snapshot, redaction, and fail-closed controls are new. |
| `tests/test_windows_readonly_adapter.py` | New unit and integration tests written for this contribution using only generated fictional data and temporary directories. |
| `.github/workflows/windows-readonly-adapter.yml` | New Windows CI workflow. Structure and pinned official action versions follow the clean-baseline `.github/workflows/x-article-draft-uploader.yml`. |

No earlier Windows implementation, binary, package, fork, mirror, or audit bundle was used to produce the contribution.
