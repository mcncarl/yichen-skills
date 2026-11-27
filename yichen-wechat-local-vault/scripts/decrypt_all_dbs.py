#!/usr/bin/env python3
"""
Decrypt all WeChat Mac 4.x SQLCipher databases that have captured keys.

Input:
  ~/.config/wechat-local-vault.json
  ~/.config/wechat-keys.json

Output:
  ~/Library/Application Support/wechat-local-vault/decrypted/current/<relative db path>
  ~/Library/Application Support/wechat-local-vault/manifests/decrypt-*.json

Each copy is decrypted into a hidden temp file beside it, checked with SQLite and
then swapped in with os.replace. A failed refresh never removes the previous copy;
the manifest records it as "miss" with kept_previous_copy/stale. If no keyed source
can be read because of a permission error (e.g. a sandboxed process), the run stops
before touching any output, writes an "aborted" manifest and exits with status 2.
Printed paths and recorded errors show the account folder (named after the wxid)
as <账号目录>.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime
import hashlib
import json
import os
import re
import sqlite3
import struct
import shutil
import sys
import tempfile
from pathlib import Path

from Crypto.Cipher import AES

PAGE_SIZE = 4096
RESERVE = 80
IV_SIZE = 16
LOCK_BYTE_OFFSET = 0x40000000
LOCK_BYTE_PAGE = LOCK_BYTE_OFFSET // PAGE_SIZE + 1  # SQLite 1 GiB lock-byte page (262145)
ZERO_PAGE = bytes(PAGE_SIZE)
NO_KEYS_EXIT_CODE = 1
ABORT_EXIT_CODE = 2
ACCOUNT_PLACEHOLDER = "<账号目录>"

CONFIG_FILE = Path("~/.config/wechat-local-vault.json").expanduser()
KEYS_FILE = Path("~/.config/wechat-keys.json").expanduser()
DEFAULT_VAULT_DIR = Path("~/Library/Application Support/wechat-local-vault").expanduser()
DEFAULT_OUTPUT_DIR = DEFAULT_VAULT_DIR / "decrypted/current"
DECRYPT_STATE_FILE = DEFAULT_VAULT_DIR / "state/decrypt_state.json"

ALIAS_TO_REL = {
    "message_0": "message/message_0.db",
    "message_1": "message/message_1.db",
    "message_2": "message/message_2.db",
    "message_3": "message/message_3.db",
    "message_fts": "message/message_fts.db",
    "message_resource": "message/message_resource.db",
    "contact": "contact/contact.db",
    "session": "session/session.db",
    "sns": "sns/sns.db",
    "favorite": "favorite/favorite.db",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def load_config() -> dict:
    return load_json(CONFIG_FILE)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if str(path).startswith(str(DEFAULT_VAULT_DIR)):
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    current = path
    while current != current.parent and str(current).startswith(str(DEFAULT_VAULT_DIR.parent)):
        try:
            os.chmod(current, 0o700)
        except OSError:
            pass
        if current == DEFAULT_VAULT_DIR:
            break
        current = current.parent


def resolve_db_base() -> Path:
    config = load_config()
    if config.get("db_base_path"):
        return Path(config["db_base_path"]).expanduser()
    wxid = config.get("wxid")
    if wxid:
        return Path(
            "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
        ).expanduser() / wxid / "db_storage"
    raise SystemExit(f"Missing db_base_path/wxid in {CONFIG_FILE}")


def public_db_base(db_base: Path) -> str:
    """db_base as printed and recorded; reads keep using the real path.

    WeChat names the folder above db_storage after the account's wxid, so that
    folder, and any folder named after the configured wxid, becomes a placeholder.
    """
    wxid = str(load_config().get("wxid") or "")
    hidden = {wxid, re.sub(r"_[0-9a-f]{4}$", "", wxid)} - {""}
    parts = list(db_base.parts)
    if len(parts) > 2 and parts[-1] == "db_storage":
        parts[-2] = ACCOUNT_PLACEHOLDER
    return str(Path(*(ACCOUNT_PLACEHOLDER if part in hidden else part for part in parts)))


def hide_account(text: str, db_base: Path) -> str:
    """Error text, such as an unreadable source path, with db_base shown as in public_db_base."""
    return text.replace(str(db_base), public_db_base(db_base))


def key_name_to_rel(name: str) -> str | None:
    if name.startswith("__"):
        return None
    if name in ALIAS_TO_REL:
        return ALIAS_TO_REL[name]
    if name.endswith(".db") and "/" in name:
        return name
    return None


def decrypt_db(src: Path, dst: Path, key_hex: str) -> None:
    key = bytes.fromhex(key_hex)
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")

    data = src.read_bytes()
    total_pages = len(data) // PAGE_SIZE
    if total_pages == 0:
        raise ValueError("database is smaller than one page")

    result = bytearray()
    for pn in range(total_pages):
        page = data[pn * PAGE_SIZE : (pn + 1) * PAGE_SIZE]
        if pn + 1 == LOCK_BYTE_PAGE and page == ZERO_PAGE:
            result.extend(ZERO_PAGE)
            continue
        enc_start = 16 if pn == 0 else 0
        enc_size = PAGE_SIZE - RESERVE - enc_start
        iv = page[PAGE_SIZE - RESERVE : PAGE_SIZE - RESERVE + IV_SIZE]
        dec = AES.new(key, AES.MODE_CBC, iv).decrypt(
            page[enc_start : enc_start + enc_size]
        )

        out_page = bytearray(PAGE_SIZE)
        if pn == 0:
            out_page[:16] = b"SQLite format 3\x00"
            out_page[16 : 16 + len(dec)] = dec
            out_page[16:18] = struct.pack(">H", PAGE_SIZE)
        else:
            out_page[: len(dec)] = dec
        result.extend(out_page)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as f:
        f.write(result)
        f.flush()
        os.fsync(f.fileno())


def sqlite_table_count(path: Path) -> int:
    # immutable=1 reads without creating -wal/-shm files, so checking a temp copy
    # leaves no sidecars behind once it is renamed (decrypted copies are WAL-mode).
    con = sqlite3.connect(f"{path.absolute().as_uri()}?immutable=1", uri=True)
    try:
        return con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
    finally:
        con.close()


def refresh_copy(src: Path, dst: Path, key_hex: str) -> tuple[int, int]:
    """Decrypt src into a temp file beside dst, check it, then swap it in.

    Any failure removes only the temp file, so an existing dst is never touched.
    The temp name starts with "." and ends with ".tmp" so globs such as
    "message_*.db" never pick it up. Returns (sqlite_master entries, bytes).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        decrypt_db(src, tmp, key_hex)
        count = sqlite_table_count(tmp)
        size = tmp.stat().st_size
        os.replace(tmp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return count, size


def miss_record(name: str, rel: str, dst: Path, reason: str) -> dict:
    """Describe a database that was not refreshed and whatever copy is left."""
    record = {"name": name, "rel": rel, "status": "miss", "reason": reason}
    try:
        previous = dst.stat()
    except OSError:
        previous = None
    # stale: an older decrypted copy is still on disk but does not include this run.
    record["kept_previous_copy"] = previous is not None
    record["stale"] = previous is not None
    if previous is not None:
        record["previous_copy_mtime"] = datetime.fromtimestamp(previous.st_mtime).isoformat(timespec="seconds")
    return record


def denied_sources(sources: list[tuple[str, Path]]) -> dict[str, PermissionError]:
    """Return {rel: error} when every existing source fails to open with a permission error.

    A sandboxed or unauthorised process can usually stat WeChat's container but not
    read it (Errno 1/13), so every refresh would fail. Returns {} when any source is
    readable, when a failure is not a permission problem, or when no source exists;
    the per-database loop then handles each case as before.
    """
    denied: dict[str, PermissionError] = {}
    for rel, src in sources:
        try:
            with src.open("rb") as f:
                f.read(1)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except PermissionError as exc:
            denied[rel] = exc
            continue
        except OSError:
            return {}
        return {}
    return denied


def write_manifest(out_base: Path, records: list[dict], abort_reason: str | None = None) -> Path:
    manifest_dir = DEFAULT_VAULT_DIR / "manifests"
    ensure_private_dir(manifest_dir)
    manifest_path = manifest_dir / f"decrypt-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "decrypted_dir": str(out_base),
        "database_count": sum(1 for item in records if item.get("status") == "ok"),
        "aborted": abort_reason is not None,
        "stale_databases": [item["rel"] for item in records if item.get("stale")],
        "records": records,
        "privacy": {
            "contains_plaintext_wechat_data": True,
            "do_not_sync_or_share": True,
            "keys_file": str(KEYS_FILE),
        },
    }
    if abort_reason is not None:
        manifest["abort_reason"] = abort_reason
    save_json(manifest_path, manifest)
    return manifest_path


def update_config_paths(out_base: Path) -> None:
    config = load_config()
    config["vault_dir"] = str(DEFAULT_VAULT_DIR)
    config["decrypted_dir"] = str(out_base)
    config.setdefault("exports_dir", "~/Documents/wechat-local-vault/exports")
    save_json(CONFIG_FILE, config)


def source_fingerprint(src: Path, key_hex: str) -> dict:
    stat = src.stat()
    return {
        "source_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "key_sha256": hashlib.sha256(key_hex.encode()).hexdigest(),
    }


def unchanged(src: Path, dst: Path, key_hex: str, state: dict, rel: str) -> bool:
    if not dst.exists():
        return False
    previous = state.get(rel)
    if not previous:
        return False
    return previous == source_fingerprint(src, key_hex)


def abort_unreadable(
    args: argparse.Namespace,
    keys: dict,
    out_base: Path,
    denied: dict[str, PermissionError],
) -> int:
    """Stop before touching outputs; record every keyed database as not refreshed."""
    first = next(iter(denied.values()))
    detail = f"[Errno {first.errno}] {first.strerror}"
    records: list[dict] = []
    for name in sorted(keys):
        rel = key_name_to_rel(name)
        if not rel:
            continue
        if rel in denied:
            records.append(miss_record(name, rel, out_base / rel, f"not attempted: source unreadable {detail}"))
        else:
            records.append({"name": name, "rel": rel, "status": "skip", "reason": "source not found"})
    kept = sum(1 for item in records if item.get("stale"))
    print(
        f"ABORT: none of the {len(denied)} keyed WeChat source databases can be read {detail}.\n"
        "This process is probably sandboxed or lacks macOS permission to read the WeChat container\n"
        "(~/Library/Containers/com.tencent.xinWeChat). Nothing was decrypted, replaced or deleted;\n"
        f"{kept} existing decrypted copies are kept but NOT refreshed (stale).\n"
        "Re-run from a process that can read the WeChat container (outside the sandbox).",
        file=sys.stderr,
    )
    if not args.no_manifest:
        manifest_path = write_manifest(out_base, records, abort_reason=f"source unreadable {detail}")
        print(f"Manifest: {manifest_path}")
    print(f"Aborted: 0 decrypted, {len(denied)} unreadable, outputs unchanged")
    return ABORT_EXIT_CODE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decrypt all known WeChat DB keys.")
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="output directory; default is the private local wechat-local-vault vault",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the output directory before decrypting",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="full decrypts every keyed DB; incremental skips unchanged sources",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="do not write a decrypt manifest",
    )
    args = parser.parse_args(argv)

    db_base = resolve_db_base()
    keys = load_json(KEYS_FILE)
    out_base = Path(args.output).expanduser()

    print(f"DB base: {public_db_base(db_base)}")
    print(f"Output:  {out_base}")

    # Check before --clean or any refresh: empty keys or unreadable sources must not cost a copy.
    rels = sorted({rel for rel in map(key_name_to_rel, keys) if rel})
    if not rels:
        print(
            f"WARNING: no database keys found in {KEYS_FILE}; nothing was decrypted or refreshed.\n"
            "Run extract_keys.py first to capture and match local database keys.",
            file=sys.stderr,
        )
        if not args.no_manifest:
            manifest_path = write_manifest(out_base, [], abort_reason="no database keys configured")
            print(f"Manifest: {manifest_path}")
        print("Aborted (no keys): 0 database keys configured; nothing decrypted, outputs unchanged")
        return NO_KEYS_EXIT_CODE

    denied = denied_sources([(rel, db_base / rel) for rel in rels])
    if denied:
        return abort_unreadable(args, keys, out_base, denied)

    if args.clean and out_base.exists():
        shutil.rmtree(out_base)
    ensure_private_dir(out_base)
    state = load_json(DECRYPT_STATE_FILE)

    passed = 0
    failed = 0
    skipped = 0
    records: list[dict] = []

    for name, key_hex in sorted(keys.items()):
        rel = key_name_to_rel(name)
        if not rel:
            skipped += 1
            continue
        src = db_base / rel
        dst = out_base / rel
        try:
            if not src.exists():
                print(f"SKIP {name}: source not found ({rel})")
                skipped += 1
                records.append({"name": name, "rel": rel, "status": "skip", "reason": "source not found"})
                continue
            if args.mode == "incremental" and unchanged(src, dst, key_hex, state, rel):
                print(f"SKIP {name:24s}: unchanged")
                skipped += 1
                records.append({"name": name, "rel": rel, "status": "unchanged"})
                continue
            # Fingerprint before reading: if WeChat writes during the read, the next
            # incremental run sees a newer source and refreshes again.
            fingerprint = source_fingerprint(src, key_hex)
            count, size = refresh_copy(src, dst, key_hex)
            state[rel] = fingerprint
            print(f"OK   {name:24s} -> {dst} ({count} tables)")
            passed += 1
            records.append({
                "name": name,
                "rel": rel,
                "status": "ok",
                "tables": count,
                "bytes": size,
            })
        except Exception as exc:
            reason = hide_account(str(exc), db_base)
            record = miss_record(name, rel, dst, reason)
            kept = "kept previous copy, now stale" if record["kept_previous_copy"] else "no previous copy"
            print(f"MISS {name:24s}: {reason} ({kept})")
            failed += 1
            records.append(record)

    update_config_paths(out_base)
    save_json(DECRYPT_STATE_FILE, state)
    if not args.no_manifest:
        manifest_path = write_manifest(out_base, records)
        print(f"Manifest: {manifest_path}")
    stale = [item["rel"] for item in records if item.get("stale")]
    if stale:
        print(f"Stale: {len(stale)} previous copies kept but not refreshed: {', '.join(stale)}")
    print(f"Done: {passed} decrypted, {failed} failed, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
