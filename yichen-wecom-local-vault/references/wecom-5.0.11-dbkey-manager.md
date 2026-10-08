# WeCom 5.0.11 / 70742 DbKeyManager compatibility

Related discussion: [Issue #16](https://github.com/mcncarl/yichen-skills/issues/16).

## Scope and evidence

This is an explicitly selected, build-specific alternative to the existing
function-hook and Mach VM capture routes. It does not change their defaults.

The contributing implementation was exercised locally on 2026-10-01 with:

| Property | Verified value |
| --- | --- |
| WeCom version / build | 5.0.11 / 70742 |
| Architecture | arm64 |
| macOS | 27.0.1 |
| Mach-O UUID | BBC8DDE9-AC04-3DF1-BF5A-D6887B956966 |
| DbKeyManager vtable RVA | `0x0cd5fb50` |
| Manager version / string offsets | `+0x60` / `+0x68` |

The local acceptance record reported successful candidate validation against
16 encrypted database first pages, followed by complete private snapshots of
the three core databases (`message.db`, `session.db`, `user.db`) with committed
WAL content and successful SQLite integrity checks. The contributed wrapper
is covered by offline regression tests; it has not been rerun against a live
process as part of this contribution. These are contributor-reported local
results, not a maintainer certification or a guarantee for other machines.

No private acceptance receipt, database, database hash, account identifier,
password, captured key, or chat content is included. There is no verification
claim for 5.0.9, Intel, other 5.0.11 builds, or all 5.x versions.

## Two independent compatibility changes

1. **Object location.** The older scanner's unslid vtable address does not
   identify the DbKeyManager vtable in this exact build. This entry point uses
   the RVA above only after checking the loaded image's architecture and UUID.
   The vtable must lie in a readable mapped range; `module.size` alone is not a
   reliable bound for this observed image layout.
2. **Password versus database master.** The observed 16-byte cached string is
   used as a password. The wxSQLite3 AES128 PDF-style KDF derives the 16-byte
   database master. Treating the cached bytes directly as the master failed in
   the successful local case. For compatibility, raw bytes are tried only if
   the derived master does not validate all three core database first pages.

The existing per-page derivation, `MD5(master || LE32(page) || "sAlT")`, remained
usable in this local case. This observation does not establish which internal
encryption function a different build calls, nor does it disprove other
participants' capture failures.

The KDF is a Python port of `GenerateKeyAES128Cipher` in
[SQLite3MultipleCiphers, pinned commit 7a7f16a](https://github.com/utelle/SQLite3MultipleCiphers/blob/7a7f16a5270e0157db43c8c3cfcf6088e11f72b1/src/cipher_wxaes128.c#L133-L187).
Its source attribution and MIT license are preserved in
[`../../licenses/utelle-SQLite3MultipleCiphers-LICENSE.txt`](../../licenses/utelle-SQLite3MultipleCiphers-LICENSE.txt).
The repository's existing license continues to govern the surrounding project.

## Running with owner authorization

Use only on the local owner's explicitly authorized data, after confirming the
process PID and database directory belong to the intended account. Do not
paste a key or password on the command line.

```bash
python3 scripts/scan_dbkey_manager_frida_macos.py \
  --confirm-attach --pid <WeCom-main-process-PID> \
  --data-dir "/private/path/to/authorized/database-directory"
```

Python needs the existing `frida` and `pycryptodome` dependencies. The command
does not install them, escalate privileges, disable SIP, re-sign an application,
launch a copy, or operate the client's UI. Frida attachment injects a scanner
script into the process; it is not the no-injection Mach VM route. The script
reads mappings and manager objects without installing function hooks or
deliberately writing target memory. OS permission failures are reported rather
than bypassed.

The installed version/build check precedes attachment. Runtime architecture,
Mach-O UUID and readable-vtable checks precede candidate scanning. Stage
timeouts are bounded, and unload/detach are attempted in cleanup. Unsuccessful
candidates are not written to disk or printed. A successful master is saved
through the existing private-vault helper with restrictive permissions only
after all three core database first pages validate and cleanup succeeds.

The string layout and 16-byte filter are observations of this build, not a
generic libc++ or DbKeyManager contract. The manager version field is observed
but is not an independent compatibility gate. Wrong-account selection should
fail validation; it must never trigger automatic dataset switching.

AES-CBC pages are not authenticated. A first-page match verifies a candidate
and the expected format, not the integrity or completeness of every page or
WAL frame. Validate complete private snapshots separately before using them.

## Offline verification

```bash
cd scripts
python3 test_wecom_local_vault.py
python3 -m unittest test_dbkey_manager_frida -v
python3 -m py_compile scan_dbkey_manager_frida_macos.py test_dbkey_manager_frida.py
```

The regression suite uses synthetic passwords/pages and mocked process APIs.
Node.js runs the injected JavaScript against a synthetic memory model; those
tests are explicitly skipped when Node.js is unavailable.
It must not attach to a live process, inspect real database directories, or
write into the user's real vault. It covers password derivation, raw fallback,
the three-core-database save gate, explicit authorization, and cleanup/failure
behavior. A passing offline test is not additional live compatibility evidence.
