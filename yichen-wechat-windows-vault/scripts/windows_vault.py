"""Independent Windows Weixin local-vault capture and snapshot CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from secret_store import KeyStore, account_binding, fingerprint
from sqlcipher_codec import key_matches_page, sqlite_integrity_check
from wal_snapshot import decrypt_database_with_wal
from windows_memory import DatabaseTarget, capture_keys, find_process_ids


PRIVATE_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "YichenWeChatVault"
DEFAULT_KEY_STORE = PRIVATE_ROOT / "keys/account.json"
DEFAULT_VAULT = PRIVATE_ROOT / "vault"


def discover_roots() -> list[Path]:
    base = Path.home() / "Documents" / "xwechat_files"
    roots: list[Path] = []
    if base.is_dir():
        for storage in base.glob("**/db_storage"):
            if (storage / "contact/contact.db").is_file() and (storage / "message").is_dir():
                roots.append(storage.parent.resolve())
    return sorted(set(roots), key=lambda path: path.stat().st_mtime, reverse=True)


def choose_root(value: str | None) -> Path:
    if value:
        root = Path(value).expanduser().resolve()
        if not (root / "db_storage").is_dir():
            raise ValueError("selected root does not contain db_storage")
        return root
    roots = discover_roots()
    if len(roots) != 1:
        raise RuntimeError(f"expected exactly one account root, found {len(roots)}; pass --root")
    return roots[0]


def redact_root(root: Path) -> str:
    return f"<account-root:{account_binding(root)[:12]}>"


def ensure_paths_separate(output: Path, account_root: Path, label: str) -> None:
    """Refuse output locations that contain or sit inside the source account tree."""
    output = Path(output).expanduser().resolve()
    account_root = Path(account_root).expanduser().resolve()
    if output.is_relative_to(account_root) or account_root.is_relative_to(output):
        raise ValueError(f"{label} must be separate from the Weixin account tree")


def database_paths(root: Path) -> dict[str, Path]:
    storage = root / "db_storage"
    result: dict[str, Path] = {}
    for path in sorted(storage.glob("**/*.db")):
        if path.stat().st_size >= 4096:
            result[path.relative_to(storage).as_posix()] = path
    return result


def select_databases(root: Path, expression: str) -> list[DatabaseTarget]:
    available = database_paths(root)
    requested = list(available) if expression.strip().casefold() == "all" else [
        item.strip().replace("\\", "/") for item in expression.split(",") if item.strip()
    ]
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"unknown database path(s): {', '.join(unknown)}")
    return [DatabaseTarget.from_path(relative, available[relative]) for relative in requested]


def diagnostics(root: Path | None = None) -> dict:
    roots = [root] if root else discover_roots()
    return {
        "platform": sys.platform,
        "weixin_processes": len(find_process_ids()) if os.name == "nt" else 0,
        "accounts": [
            {
                "root": redact_root(item),
                "database_count": len(database_paths(item)),
                "wal_count": len(list((item / "db_storage").glob("**/*.db-wal"))),
            }
            for item in roots
        ],
        "private_vault": r"%LOCALAPPDATA%\YichenWeChatVault",
    }


def capture(
    root: Path,
    targets_expression: str,
    duration: float,
    key_store_path: Path,
    consent: bool,
) -> dict:
    if not consent:
        raise PermissionError(
            "capture requires --consent-read-process-memory after the user explicitly approves this scope"
        )
    ensure_paths_separate(key_store_path, root, "key store")
    targets = select_databases(root, targets_expression)
    store = KeyStore(key_store_path, root)
    pending: list[DatabaseTarget] = []
    reused: list[str] = []
    for target in targets:
        try:
            key, profile = store.get(target.database)
        except (KeyError, ValueError):
            pending.append(target)
            continue
        if key_matches_page(target.page, key, profile):
            reused.append(target.database)
        else:
            pending.append(target)

    if pending:
        report = capture_keys(pending, duration)
        by_database = {target.database: target for target in pending}
        for match in report.matches:
            target = by_database[match.database]
            store.put(
                match.database,
                match.key,
                target.salt,
                match.profile,
                match.key_kind,
            )
        safe = report.safe_dict()
    else:
        safe = {
            "pids_checked": 0,
            "codec_contexts": 0,
            "monitored_buffers": 0,
            "matched_databases": [],
            "matched_count": 0,
        }
    stored = sorted(store.metadata())
    return {
        "account": redact_root(root),
        "requested": len(targets),
        "reused": sorted(reused),
        **safe,
        "stored_databases": stored,
        "missing_databases": sorted(target.database for target in targets if target.database not in stored),
        "key_store": str(key_store_path),
        "keys_redacted": True,
    }


def _source_set(database: Path) -> list[Path]:
    result = [database]
    for suffix in ("-wal", "-shm"):
        companion = Path(str(database) + suffix)
        if companion.exists():
            result.append(companion)
    return result


def _metadata(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {path.name: (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}


def stable_copy_set(database: Path, destination: Path, retries: int = 5) -> list[Path]:
    """Copy DB/WAL/SHM as one stable set without replacing source files."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        sources = _source_set(database)
        before = _metadata(sources)
        copied: list[Path] = []
        try:
            for source in sources:
                suffix = source.name[len(database.name) :]
                target = Path(str(destination) + suffix)
                temporary = Path(str(target) + ".tmp")
                copied.append(temporary)
                shutil.copyfile(source, temporary)
        except OSError:
            for temporary in copied:
                temporary.unlink(missing_ok=True)
            raise
        after_sources = _source_set(database)
        after = _metadata(after_sources)
        if before == after and [path.name for path in sources] == [path.name for path in after_sources]:
            finals: list[Path] = []
            for temporary in copied:
                final = Path(str(temporary)[:-4])
                os.replace(temporary, final)
                finals.append(final)
            return finals
        for temporary in copied:
            temporary.unlink(missing_ok=True)
        time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(f"source set changed while copying: {database.name}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encrypted_file_records(database: Path, copied: list[Path]) -> list[dict]:
    """Describe a copied DB/WAL/SHM set without exposing account paths."""
    records: list[dict] = []
    for path in copied:
        suffix = path.name[len(database.name) :]
        records.append(
            {
                "kind": "database" if not suffix else suffix.removeprefix("-"),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return records


def _load_previous_snapshot(
    vault: Path, expected_account_binding: str
) -> tuple[dict[str, dict], Path | None]:
    """Load only the vault-owned current snapshot metadata for incremental reuse."""
    current_path = Path(vault) / "current.json"
    if not current_path.is_file():
        return {}, None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        vault_root = Path(vault).resolve()
        manifest_path = Path(current["manifest"]).resolve()
        decrypted_root = Path(current["decrypted_dir"]).resolve()
        manifest_path.relative_to(vault_root)
        decrypted_root.relative_to(vault_root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("account_binding") != expected_account_binding:
            return {}, None
        records = {
            record["database"]: record
            for record in manifest.get("records", [])
            if record.get("status") == "ok"
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}, None
    return records, decrypted_root


def _copy_plaintext_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        sqlite_integrity_check(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def refresh(root: Path, key_store_path: Path, vault: Path, mode: str = "incremental") -> dict:
    if mode not in {"full", "incremental"}:
        raise ValueError("refresh mode must be 'full' or 'incremental'")
    ensure_paths_separate(key_store_path, root, "key store")
    ensure_paths_separate(vault, root, "vault")
    if find_process_ids():
        raise RuntimeError(
            "Weixin is running; exit it manually before refresh so DB/WAL/SHM form a stable snapshot"
        )
    store = KeyStore(key_store_path, root)
    databases = database_paths(root)
    if not databases:
        raise RuntimeError("no databases found under selected root")

    binding = account_binding(root)
    previous_records, previous_decrypted_root = (
        _load_previous_snapshot(vault, binding) if mode == "incremental" else ({}, None)
    )
    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    generation_root = Path(vault) / "generations" / generation
    encrypted_root = generation_root / "encrypted/db_storage"
    decrypted_root = generation_root / "decrypted/db_storage"
    manifest_path = generation_root / "manifest.json"
    records: list[dict] = []
    manifest = {
        "format": 1,
        "generation": generation,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account_binding": binding,
        "mode": mode,
        "complete": False,
        "privacy": {
            "contains_plaintext_weixin_data": True,
            "local_only": True,
            "do_not_sync_or_commit": True,
        },
        "records": records,
    }
    _write_json_atomic(manifest_path, manifest)
    for relative, source in databases.items():
        encrypted = encrypted_root / relative
        try:
            copied = stable_copy_set(source, encrypted)
        except (OSError, RuntimeError) as error:
            records.append(
                {
                    "database": relative,
                    "status": "snapshot-copy-failed",
                    "reason": type(error).__name__,
                }
            )
            continue
        record = {
            "database": relative,
            "encrypted_sha256": file_sha256(encrypted),
            "companions": [path.name[len(encrypted.name) :] for path in copied[1:]],
            "encrypted_files": encrypted_file_records(encrypted, copied),
        }
        try:
            key, profile = store.get(relative)
        except (KeyError, ValueError) as error:
            record.update({"status": "missing-key", "reason": type(error).__name__})
            records.append(record)
            continue
        with encrypted.open("rb") as stream:
            first_page = stream.read(profile.page_size)
        if not key_matches_page(first_page, key, profile):
            record.update({"status": "stale-key"})
            records.append(record)
            continue
        destination = decrypted_root / relative
        key_fingerprint = fingerprint(key)
        previous = previous_records.get(relative)
        previous_plaintext = (
            previous_decrypted_root / relative if previous_decrypted_root is not None else None
        )
        if (
            mode == "incremental"
            and previous is not None
            and previous.get("encrypted_files") == record["encrypted_files"]
            and previous.get("key_fingerprint") == key_fingerprint
            and previous_plaintext is not None
            and previous_plaintext.is_file()
        ):
            try:
                _copy_plaintext_atomic(previous_plaintext, destination)
            except (OSError, ValueError):
                pass
            else:
                record.update(
                    {
                        "status": "ok",
                        "key_fingerprint": key_fingerprint,
                        "decrypted_bytes": destination.stat().st_size,
                        "decrypted_sha256": file_sha256(destination),
                        "integrity": "ok",
                        "incremental_reuse": True,
                        "wal": previous.get("wal", {"present": False, "applied_frames": 0}),
                    }
                )
                records.append(record)
                continue
        wal = Path(str(encrypted) + "-wal")
        try:
            wal_report = decrypt_database_with_wal(
                encrypted,
                wal if wal.exists() else None,
                destination,
                key,
                profile,
            )
        except (OSError, RuntimeError, ValueError) as error:
            record.update({"status": "decode-failed", "reason": type(error).__name__})
            records.append(record)
            continue
        record.update(
            {
                "status": "ok",
                "key_fingerprint": key_fingerprint,
                "decrypted_bytes": destination.stat().st_size,
                "decrypted_sha256": file_sha256(destination),
                "integrity": "ok",
                "incremental_reuse": False,
                "wal": wal_report.as_dict(),
            }
        )
        records.append(record)
    manifest["complete"] = all(record["status"] == "ok" for record in records)
    manifest["database_count"] = len(records)
    manifest["decrypted_count"] = sum(record["status"] == "ok" for record in records)
    manifest["missing_count"] = sum(record["status"] != "ok" for record in records)
    _write_json_atomic(manifest_path, manifest)
    if manifest["complete"]:
        _write_json_atomic(
            Path(vault) / "current.json",
            {
                "format": 1,
                "generation": generation,
                "manifest": str(manifest_path),
                "decrypted_dir": str(decrypted_root),
            },
        )
    return {
        "generation": generation,
        "complete": manifest["complete"],
        "database_count": manifest["database_count"],
        "decrypted_count": manifest["decrypted_count"],
        "missing_count": manifest["missing_count"],
        "manifest": str(manifest_path),
        "decrypted_dir": str(decrypted_root),
    }


def status(root: Path, key_store_path: Path, vault: Path) -> dict:
    available = database_paths(root)
    try:
        stored = KeyStore(key_store_path, root).metadata()
    except (FileNotFoundError, ValueError):
        stored = {}
    current_path = Path(vault) / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else None
    return {
        "account": redact_root(root),
        "databases": len(available),
        "stored_keys": len(stored),
        "missing_keys": sorted(set(available) - set(stored)),
        "current_snapshot": current,
        "weixin_running": bool(find_process_ids()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent Windows Weixin local vault")
    sub = parser.add_subparsers(dest="command", required=True)
    diagnose = sub.add_parser("diagnose")
    diagnose.add_argument("--root")
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--root")
    capture_parser.add_argument("--targets", default="all")
    capture_parser.add_argument("--duration", type=float, default=120.0)
    capture_parser.add_argument("--key-store", default=str(DEFAULT_KEY_STORE))
    capture_parser.add_argument("--consent-read-process-memory", action="store_true")
    refresh_parser = sub.add_parser("refresh")
    refresh_parser.add_argument("--root")
    refresh_parser.add_argument("--key-store", default=str(DEFAULT_KEY_STORE))
    refresh_parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    refresh_parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--root")
    status_parser.add_argument("--key-store", default=str(DEFAULT_KEY_STORE))
    status_parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "diagnose":
        selected = choose_root(args.root) if args.root else None
        print(json.dumps(diagnostics(selected), ensure_ascii=False, indent=2))
        return 0
    root = choose_root(args.root)
    if args.command == "capture":
        result = capture(
            root,
            args.targets,
            args.duration,
            Path(args.key_store),
            args.consent_read_process_memory,
        )
    elif args.command == "refresh":
        result = refresh(root, Path(args.key_store), Path(args.vault), args.mode)
    elif args.command == "status":
        result = status(root, Path(args.key_store), Path(args.vault))
    else:
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
