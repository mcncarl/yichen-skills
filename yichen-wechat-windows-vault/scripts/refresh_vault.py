"""Incrementally copy and decrypt an explicit WeChat database root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from key_store import load_keys, save_keys
from sqlcipher import SQLITE_HEADER, copy_plain_database, decrypt_database, verify_database
from vault_common import VaultError, atomic_json, ensure_private_dir, load_json, require_explicit_dir, vault_home


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    with path.open("rb") as handle:
        first = handle.read(16)
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "header_sha256": hashlib.sha256(first).hexdigest(),
    }


def validate_plaintext(path: Path) -> None:
    try:
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise VaultError(f"decrypted SQLite validation failed: {path.name}") from exc


def matching_key(snapshot: Path, relative: str, keys: dict[str, bytes]) -> bytes | None:
    preferred = keys.get(relative)
    if preferred is not None and verify_database(snapshot, preferred):
        return preferred
    seen: set[bytes] = set()
    for candidate in keys.values():
        if candidate in seen:
            continue
        seen.add(candidate)
        if verify_database(snapshot, candidate):
            return candidate
    return None


def refresh(db_root: Path, home: Path) -> dict:
    ensure_private_dir(home)
    decrypted_root = ensure_private_dir(home / "vault" / "decrypted")
    staging = ensure_private_dir(home / "staging")
    key_file = home / "keys.dpapi"
    manifest_path = home / "manifest.json"
    keys = load_keys(key_file)
    manifest = load_json(manifest_path, {"databases": {}})
    previous = manifest.get("databases", {})
    current: dict[str, dict] = {}
    result = {"ok": 0, "unchanged": 0, "missing_key": 0, "failed": 0, "databases": []}

    for source in sorted(db_root.rglob("*.db")):
        relative = source.relative_to(db_root).as_posix()
        state = fingerprint(source)
        destination = decrypted_root / Path(relative)
        if previous.get(relative) == state and destination.is_file():
            current[relative] = state
            result["unchanged"] += 1
            result["databases"].append({"path": relative, "status": "unchanged"})
            continue
        token = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
        fd, snapshot_name = tempfile.mkstemp(prefix=token + ".", suffix=".db", dir=staging)
        os.close(fd)
        snapshot = Path(snapshot_name)
        try:
            shutil.copyfile(source, snapshot)
            with snapshot.open("rb") as handle:
                plain = handle.read(16) == SQLITE_HEADER
            if plain:
                copy_plain_database(snapshot, destination)
            else:
                key = matching_key(snapshot, relative, keys)
                if key is None:
                    result["missing_key"] += 1
                    result["databases"].append({"path": relative, "status": "missing_key"})
                    continue
                decrypt_database(snapshot, destination, key)
                keys[relative] = key
            validate_plaintext(destination)
            current[relative] = state
            result["ok"] += 1
            result["databases"].append({"path": relative, "status": "ok"})
        except (OSError, VaultError) as exc:
            result["failed"] += 1
            result["databases"].append({"path": relative, "status": "failed", "error": str(exc)})
        finally:
            snapshot.unlink(missing_ok=True)

    save_keys(key_file, keys)
    atomic_json(manifest_path, {"databases": current}, private=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-root", required=True, help="Explicit WeChat db_storage root")
    parser.add_argument("--vault-home")
    args = parser.parse_args()
    try:
        result = refresh(
            require_explicit_dir(args.db_root, "--db-root"),
            vault_home(args.vault_home),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["failed"] or result["missing_key"]:
            raise SystemExit(2)
    except VaultError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
