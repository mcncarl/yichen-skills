from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

from Crypto.Cipher import AES

from vault_common import (
    DECRYPTED_DIR,
    KEYS_FILE,
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    choose_db_root,
    collect_databases,
    load_keys,
    verify_key,
)

SQLITE_HEADER = b"SQLite format 3\x00"


def decrypt_page(key: bytes, page: bytes, page_number: int) -> bytes:
    iv = page[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + 16]
    start = SALT_SIZE if page_number == 1 else 0
    plaintext = AES.new(key, AES.MODE_CBC, iv).decrypt(page[start : PAGE_SIZE - RESERVE_SIZE])
    if page_number == 1:
        return SQLITE_HEADER + plaintext + (b"\x00" * RESERVE_SIZE)
    return plaintext + (b"\x00" * RESERVE_SIZE)


def decrypt_database(source: Path, destination: Path, key: bytes) -> tuple[bool, str]:
    size = source.stat().st_size
    if size < PAGE_SIZE or size % PAGE_SIZE:
        return False, "source size is not a complete SQLCipher page set"
    with source.open("rb") as handle:
        first_page = handle.read(PAGE_SIZE)
    if not verify_key(key, first_page):
        return False, "page-1 HMAC verification failed"

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=destination.name + "-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as encrypted, temporary.open("wb") as plaintext:
            page_number = 1
            while page := encrypted.read(PAGE_SIZE):
                if len(page) != PAGE_SIZE:
                    return False, "short final page"
                plaintext.write(decrypt_page(key, page, page_number))
                page_number += 1

        connection = sqlite3.connect(
            f"file:{temporary.as_posix()}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            table_count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            connection.close()
        os.replace(temporary, destination)
        os.utime(destination, (source.stat().st_atime, source.stat().st_mtime))
        return True, f"tables={table_count}"
    except (OSError, sqlite3.Error, ValueError) as exc:
        return False, str(exc)
    finally:
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + "-shm").unlink(missing_ok=True)
        Path(str(temporary) + "-wal").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decrypt verified WeChat databases into a private vault")
    parser.add_argument("--db-root")
    parser.add_argument("--output", default=str(DECRYPTED_DIR))
    parser.add_argument("--keys", default=str(KEYS_FILE))
    parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    output = Path(args.output).expanduser().resolve()
    keys = load_keys(Path(args.keys).expanduser())
    recorded_root = keys.get("_db_dir") if isinstance(keys.get("_db_dir"), str) else None
    root = choose_db_root(args.db_root or recorded_root)
    databases = collect_databases(root)
    success = failed = skipped = 0

    print(f"source_databases: {len(databases)}")
    print(f"output: {output}")
    for relative, source, _page in databases:
        info = keys.get(relative)
        if not isinstance(info, dict) or not info.get("enc_key"):
            print(f"skip: {relative} (no verified key)")
            skipped += 1
            continue
        destination = output / relative
        if (
            args.mode == "incremental"
            and destination.is_file()
            and destination.stat().st_mtime >= source.stat().st_mtime
        ):
            skipped += 1
            continue
        if args.dry_run:
            print(f"would_decrypt: {relative}")
            continue
        try:
            key = bytes.fromhex(info["enc_key"])
        except ValueError:
            print(f"failed: {relative} (invalid key encoding)")
            failed += 1
            continue
        ok, detail = decrypt_database(source, destination, key)
        if ok:
            print(f"ok: {relative} ({detail})", flush=True)
            success += 1
        else:
            print(f"failed: {relative} ({detail})", flush=True)
            failed += 1

    print(f"complete: success={success}; failed={failed}; skipped={skipped}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
