# Yichen WeChat Windows Vault

An independent Windows counterpart to `yichen-wechat-local-vault`. It creates local, immutable plaintext snapshots of the current Windows user's Weixin 4.x databases and provides the same read-only query/export surface as the Mac skill.

## What it does

- Discovers official Windows Weixin account databases under the current user's `Documents\xwechat_files`.
- With explicit current-task consent, reads only `Weixin.exe` process memory and waits for an ordinary SQLCipher key-use window.
- Validates every captured key against both the SQLCipher page HMAC and SQLite header before accepting it.
- Protects accepted keys with current-user Windows DPAPI; raw keys are never printed or stored in the repository.
- Copies DB/WAL/SHM only after the user manually exits Weixin.
- Validates SQLite WAL header/frame checksums and applies only frames through the last valid commit.
- Runs `quick_check` and `integrity_check` before atomically promoting a snapshot.
- Supports contacts, sessions, unread/new messages, history, global search, statistics, Markdown export, group digest sources, Favorites, and Moments.

It does not use `wx-cli`, Frida, injection, hooks, drivers, Weixin UI automation, or process-control APIs.

## Supported environment

- Windows 10/11 x64
- Official Weixin 4.x
- Python 3.10+

Local validation was performed on Windows 11 with Weixin `4.1.13.7`. The memory scanner recognizes documented Tencent SQLCipher context geometry and fails closed if the ABI or page validation changes.

## Install

```powershell
py -3 -m venv "$env:LOCALAPPDATA\YichenWeChatVault\runtime"
& "$env:LOCALAPPDATA\YichenWeChatVault\runtime\Scripts\python.exe" -m pip install --upgrade pip
& "$env:LOCALAPPDATA\YichenWeChatVault\runtime\Scripts\python.exe" -m pip install -r ".\requirements.txt"
```

Runtime dependencies are exactly pinned. See `THIRD_PARTY_NOTICES.md` and `sbom.spdx.json`.

## Quick start

```powershell
python .\scripts\windows_vault.py diagnose
```

After the user explicitly approves reading Weixin process memory and storing the resulting database keys locally:

```powershell
python .\scripts\windows_vault.py capture --targets all --duration 240 --consent-read-process-memory
```

The user should manually visit the relevant Weixin areas while capture runs. Key buffers are protected while idle and are visible only during normal database operations. The tool does not create that activity itself.

Then the user manually exits Weixin and runs:

```powershell
python .\scripts\windows_vault.py refresh --mode full
python .\scripts\windows_vault.py status
python .\scripts\vault_cli.py sessions --limit 20 --format text
```

Run `python .\scripts\vault_cli.py --help` for all query commands.

For later runs, `refresh --mode incremental` is the default. It still creates a new immutable generation and re-copies and hashes every encrypted DB/WAL/SHM set, but it reuses an integrity-checked plaintext database when the encrypted set and DPAPI key fingerprint are unchanged. Use `--mode full` to force decryption of every database.

## Private data layout

```text
%LOCALAPPDATA%\YichenWeChatVault\
├── keys\account.json              # DPAPI ciphertext and non-secret metadata
└── vault\
    ├── current.json                # updated only after a complete generation
    ├── state\                      # read-only query cursors
    └── generations\<id>\
        ├── encrypted\db_storage\  # stable DB/WAL/SHM copies
        ├── decrypted\db_storage\  # plaintext local snapshot
        └── manifest.json           # hashes, WAL report, integrity result
```

Old generations are never deleted automatically. Exports default to `%USERPROFILE%\Documents\YichenWeChatVault\exports` and may contain plaintext personal data.

## Why process-memory reading is necessary

Current Weixin protects SQLCipher key buffers while they are idle. During normal database page encryption/decryption, the existing buffer is briefly made usable and then protected again. This project samples the already-running process using the read-only Windows access rights `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`; a candidate is retained only when it verifies against the target database. It does not modify the process or invoke Weixin code.

This is sensitive behavior and therefore requires an explicit command-line consent flag in addition to the Skill's instruction to obtain current-task user approval.

## WAL correctness

Copying or decrypting only the `.db` file can lose committed updates that exist only in `-wal`. The snapshot pipeline validates the original encrypted WAL's rolling checksums and frame salts, finds its last valid commit, decrypts each committed page using its database page number, applies the committed prefix, truncates to the commit's declared database size, and finally runs SQLite integrity checks.

The test suite constructs a real reserved-byte SQLite fixture, encrypts it page-by-page, writes a valid WAL-only update, and proves the merged plaintext database contains the update. It also covers tampered page HMACs, corrupted WAL frames, DPAPI round trips, consent gating, safety API bans, and query/export behavior.

## Verification

```powershell
python -m unittest discover -s .\tests -v
python -m py_compile .\scripts\sqlcipher_codec.py .\scripts\wal_snapshot.py .\scripts\secret_store.py .\scripts\windows_memory.py .\scripts\windows_vault.py .\scripts\vault_cli.py
```

## Technical references

- [Tencent SQLCipher fork](https://github.com/Tencent/sqlcipher) — codec and cipher-context layout.
- [Tencent WCDB encryption documentation](https://github.com/Tencent/wcdb/wiki/C%2B%2B-%E5%8A%A0%E5%AF%86%E4%B8%8E%E9%85%8D%E7%BD%AE) — WCDB cipher-key behavior and defaults.
- [SQLCipher design](https://www.zetetic.net/sqlcipher/design/) — salt, page encryption, IV, and HMAC design.
- [SQLite WAL file format](https://www.sqlite.org/fileformat2.html#walformat) — header, frame, commit, and checksum semantics.
- [Microsoft `VirtualQueryEx`](https://learn.microsoft.com/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex) and [`ReadProcessMemory`](https://learn.microsoft.com/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory) — read-only process inspection APIs.
- [Microsoft DPAPI `CryptProtectData`](https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) — current-user key protection.

See `PROVENANCE.md` for the implementation lineage and clean-version statement.
