"""Explicit Windows live capture. No UI, network, injection, or stored keys."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from snapshot_reader import _secure_existing_path, validate_snapshot, connect_read_only
from windows_crypto import PAGE, decrypt_pages, verify_enc_key
from windows_wal import read_snapshot

PROFILE = "windows-chat-capture-v1"
MESSAGE_RE = re.compile(r"(?:message|biz_message)_[0-9]+\.db\Z")


def private_root():
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_absolute():
        raise RuntimeError("LOCALAPPDATA is required for private Windows output")
    return local / "YichenWeChatVault" / "windows-live"


def source_id(root):
    return hashlib.sha256(os.fsencode(str(root).casefold())).hexdigest()[:16]


def selected_files(root, scope="chat"):
    root = _secure_existing_path(root, label="authorized db_storage", expected="directory")
    if root.name.casefold() != "db_storage":
        raise ValueError("The source must be an explicit db_storage directory")
    selected = [root / "contact/contact.db", root / "session/session.db"]
    message = _secure_existing_path(root / "message", label="message directory", expected="directory", allowed_root=root)
    selected.extend(sorted(path for path in message.iterdir() if MESSAGE_RE.fullmatch(path.name)))
    if len(selected) < 3:
        raise ValueError("No chat message shard is available in this account")
    if scope not in ("chat", "all"):
        raise ValueError("Unsupported capture scope")
    if scope == "all":
        selected, pending, visited = [], [root], 0
        while pending:
            directory = _secure_existing_path(pending.pop(), label="source directory", expected="directory", allowed_root=root)
            visited += 1
            if visited > 256 or len(directory.relative_to(root).parts) > 8:
                raise ValueError("Source directory traversal exceeds the capture bounds")
            for path in sorted(directory.iterdir()):
                if path.is_dir():
                    pending.append(path)
                elif path.suffix.casefold() == ".db":
                    selected.append(_secure_existing_path(path, label="source database", expected="file", allowed_root=root))
            if len(selected) > 258:
                raise ValueError("Too many databases for one capture")
    if len(selected) > 258:
        raise ValueError("Too many message shards for one capture")
    return [_secure_existing_path(path, label="source database", expected="file", allowed_root=root) for path in selected]


def discover(db_root=None):
    candidates = []
    if db_root:
        roots = [Path(db_root)]
    else:
        profile = Path(os.environ["USERPROFILE"])
        bases = [profile / "Documents/xwechat_files", profile / "Documents/WeChat Files/xwechat_files"]
        roots = []
        for base in bases:
            if base.is_dir():
                _secure_existing_path(base, label="Windows data directory", expected="directory")
                roots.extend(child / "db_storage" for child in base.iterdir() if child.is_dir())
    for root in roots:
        if not root.is_dir():
            continue
        try:
            files = selected_files(root)
        except (OSError, ValueError, RuntimeError):
            continue
        candidates.append((root.resolve(), files))
    return candidates


def choose_source(candidates, requested):
    matches = [item for item in candidates if not requested or source_id(item[0]) == requested]
    if len(matches) != 1:
        raise ValueError("Select exactly one account using discover and --source-id (or --db-root)")
    return matches[0]


def child_directory(root: Path, relative: Path) -> Path:
    """Inspect existing components before creating or writing below the vault."""
    current = _secure_existing_path(root, label="private output", expected="directory")
    if relative.is_absolute() or any(part in ("..", ".") for part in relative.parts):
        raise ValueError("Invalid private output component")
    for component in relative.parts:
        current = current / component
        if not os.path.lexists(current):
            current.mkdir(exist_ok=False)
        current = _secure_existing_path(current, label="private output component", expected="directory", allowed_root=root)
    return current


def atomic_json(path: Path, value: dict) -> None:
    parent = _secure_existing_path(path.parent, label="private JSON parent", expected="directory")
    if os.path.lexists(path):
        _secure_existing_path(path, label="private JSON output", expected="file", allowed_root=parent)
    temporary = parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    # On failure the previous pointer and the diagnostic temp file are retained.
    os.replace(temporary, path)


def extract_keys(files, pids, seconds=90):
    from windows_native import ProcessReader, profile_owner
    from windows_keyscan import _scan_windows_v411_config_cipher, _iter_windows_region_chunks, _HEX_RE
    owner, deadline = profile_owner(), time.monotonic() + seconds
    databases, salts = [], {}
    for path in files:
        with path.open("rb") as handle:
            page = handle.read(PAGE)
        if len(page) != PAGE or page.startswith(b"SQLite format 3\0"):
            raise ValueError("Expected encrypted WeChat 4.x databases")
        salt = page[:16].hex()
        databases.append((path.name, None, path.stat().st_size, salt, page))
        salts.setdefault(salt, []).append(path.name)
    remaining, keys, statistics = set(salts), {}, []
    for pid in pids:
        process = ProcessReader(pid, owner)
        try:
            regions = process.regions()
            budget = [0]
            def read(address, size):
                if time.monotonic() > deadline or budget[0] + size > 6 * 1024**3:
                    raise ValueError("Read-only memory scan reached its time or byte limit")
                budget[0] += size
                return process.read(address, size)
            stats = _scan_windows_v411_config_cipher(pid, regions, read, read, databases, salts, keys, remaining, lambda *args: None)
            if remaining:
                for _, chunk in _iter_windows_region_chunks(regions, read, overlap=256):
                    for match in _HEX_RE.finditer(chunk):
                        candidate = match.group(1).decode("ascii")
                        if len(candidate) < 96:
                            continue
                        salt = candidate[64:96].lower()
                        if salt not in remaining:
                            continue
                        key = bytes.fromhex(candidate[:64])
                        if any(record[3] == salt and verify_enc_key(key, record[4]) for record in databases):
                            keys[salt] = candidate[:64]
                            remaining.remove(salt)
                    if not remaining:
                        break
            statistics.append({"pid": pid, "runtime_candidates": stats["candidate_count"], "matched_databases": len(keys), "read_bytes": budget[0]})
        finally:
            process.close()
        if not remaining:
            break
    if remaining:
        raise ValueError(f"Verified keys unavailable for {len(remaining)} chat database salts; keep the authorized account logged in and retry")
    return keys, statistics


def _load_reusable_previous(vault: Path, expected_source_id: str) -> dict[str, dict]:
    """Return {relative_posix: metadata} from the previous verified snapshot of the same source."""
    latest_path = vault / "latest.json"
    if not os.path.lexists(latest_path):
        return {}
    try:
        latest_path = _secure_existing_path(latest_path, label="previous latest.json", expected="file", allowed_root=vault)
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(latest, dict) or latest.get("source_id") != expected_source_id:
            return {}
        prev_snapshot = latest.get("snapshot")
        if not isinstance(prev_snapshot, str) or not prev_snapshot:
            return {}
        prev_root = _secure_existing_path(Path(prev_snapshot), label="previous snapshot", expected="directory", allowed_root=vault)
        if not validate_snapshot(prev_root)["valid"]:
            return {}
        manifest_path = _secure_existing_path(prev_root / "snapshot-manifest.json", label="previous manifest", expected="file", allowed_root=prev_root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_id") != expected_source_id:
            return {}
        index: dict[str, dict] = {}
        for item in manifest.get("databases") or []:
            if not isinstance(item, dict):
                continue
            rel = item.get("database")
            enc_sha = item.get("encrypted_snapshot_sha256")
            plain_sha = item.get("plaintext_sha256")
            if not (isinstance(rel, str) and isinstance(enc_sha, str) and isinstance(plain_sha, str)):
                continue
            prev_file = _secure_existing_path(prev_root / rel, label=f"previous {rel}", expected="file", allowed_root=prev_root)
            index[rel] = {
                "path": prev_file,
                "encrypted_snapshot_sha256": enc_sha,
                "plaintext_sha256": plain_sha,
                "pages": int(item.get("pages") or 0),
                "sqlite_integrity": str(item.get("sqlite_integrity") or "passed"),
            }
        return index
    except (OSError, ValueError, RuntimeError):
        return {}


def _verify_fts_physical_btrees(destination: Path) -> tuple[str, str]:
    """Verify every non-virtual physical B-tree when custom MMFtsTokenizer blocks whole-DB integrity_check."""
    try:
        con_ctx = connect_read_only(destination)
    except sqlite3.OperationalError as exc:
        if str(exc) == "SQL logic error":
            return "unverified", "SQLite integrity_check returned SQL logic error"
        raise
    with con_ctx as con:
        rows = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        virts = [
            (str(r[0]), str(r[1] or ""))
            for r in rows
            if str(r[1] or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")
        ]
        if not virts or not any("mmftstokenizer" in sql.lower() for _, sql in virts):
            raise sqlite3.OperationalError("SQL logic error")
        phys = [
            str(r[0])
            for r in rows
            if not str(r[1] or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")
        ]
        for tbl in phys:
            safe_tbl = tbl.replace("]", "]]")
            checks = con.execute(f"PRAGMA integrity_check([{safe_tbl}])").fetchall()
            if len(checks) != 1 or checks[0][0] != "ok":
                raise ValueError(f"Decrypted FTS physical B-tree {tbl} failed SQLite integrity_check")
        return (
            "unverified",
            f"MMFtsTokenizer virtual-table tokenizer unavailable; all {len(phys)} physical B-tree tables passed integrity_check",
        )


def capture(root, files, pids, *, max_bytes, seconds, scope="chat", mode="full"):
    from windows_native import secure_output_root
    if scope not in ("chat", "all"):
        raise ValueError("Unsupported capture scope")
    if mode not in ("full", "incremental"):
        raise ValueError("Unsupported capture mode")
    vault = secure_output_root(private_root())
    identifier = str(uuid.uuid4())
    # New directory per attempt: an incomplete capture never replaces a good one.
    snapshots = child_directory(vault, Path("snapshots"))
    output = snapshots / identifier
    output.mkdir(exist_ok=False)
    output = _secure_existing_path(output, label="new snapshot", expected="directory", allowed_root=vault)
    started = datetime.now(timezone.utc).isoformat()
    src_id = source_id(root)
    previous_index = _load_reusable_previous(vault, src_id) if mode == "incremental" else {}
    records, keys, integrity_gaps, statistics = [], {}, [], []
    reused_count = 0
    decrypted_count = 0
    try:
        reused_map: dict[str, dict] = {}
        changed_files: list[Path] = []
        if previous_index:
            for path in files:
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(str(path) + suffix)
                    if os.path.lexists(sidecar):
                        _secure_existing_path(sidecar, label="source sidecar", expected="file", allowed_root=root)
                rel = path.relative_to(root).as_posix()
                prev = previous_index.get(rel)
                if prev is None:
                    changed_files.append(path)
                    continue
                data = read_snapshot(path, max_bytes=max_bytes)
                enc_sha = hashlib.sha256(data).hexdigest()
                if enc_sha != prev["encrypted_snapshot_sha256"]:
                    changed_files.append(path)
                    continue
                plain = prev["path"].read_bytes()
                if hashlib.sha256(plain).hexdigest() != prev["plaintext_sha256"]:
                    changed_files.append(path)
                    continue
                relative = path.relative_to(root)
                destination = output / relative
                child_directory(output, relative.parent)
                with destination.open("xb") as target:
                    target.write(plain)
                    target.flush()
                    os.fsync(target.fileno())
                integrity = prev["sqlite_integrity"]
                if integrity == "unverified":
                    integrity_gaps.append({"database": rel, "reason": "SQLite integrity_check returned SQL logic error"})
                reused_map[rel] = {
                    "database": rel,
                    "pages": len(data) // PAGE,
                    "authenticated": True,
                    "reused": True,
                    "sqlite_integrity": integrity,
                    "encrypted_snapshot_sha256": enc_sha,
                    "plaintext_sha256": prev["plaintext_sha256"],
                }
                reused_count += 1
        else:
            changed_files = list(files)

        if changed_files:
            keys, statistics = extract_keys(changed_files, pids, seconds)
        for path in files:
            relative = path.relative_to(root)
            rel = relative.as_posix()
            if rel in reused_map:
                records.append(reused_map[rel])
                continue
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(path) + suffix)
                if os.path.lexists(sidecar):
                    _secure_existing_path(sidecar, label="source sidecar", expected="file", allowed_root=root)
            data = read_snapshot(path, max_bytes=max_bytes)
            key = keys.get(data[:16].hex())
            if key is None:
                raise ValueError("Database salt changed during capture; retry")
            plain = decrypt_pages(data, bytes.fromhex(key))
            destination = output / relative
            child_directory(output, relative.parent)
            with destination.open("xb") as target:
                target.write(plain)
                target.flush()
                os.fsync(target.fileno())
            integrity = "passed"
            try:
                with connect_read_only(destination) as con:
                    checks = con.execute("PRAGMA integrity_check").fetchall()
                    if len(checks) != 1 or checks[0][0] != "ok":
                        raise ValueError("Decrypted database failed SQLite integrity_check")
            except sqlite3.OperationalError as exc:
                # Only the observed optional FTS-index check is recorded as a gap after verifying
                # every physical B-tree table. Authentication is still mandatory; no main data check is waived.
                optional_indexes = {"contact/contact_fts.db", "favorite/favorite_fts.db", "message/message_fts.db"}
                if scope != "all" or rel not in optional_indexes or str(exc) != "SQL logic error":
                    raise
                integrity, gap_reason = _verify_fts_physical_btrees(destination)
                integrity_gaps.append({"database": rel, "reason": gap_reason})
            decrypted_count += 1
            records.append({
                "database": rel,
                "pages": len(data) // PAGE,
                "authenticated": True,
                "reused": False,
                "sqlite_integrity": integrity,
                "encrypted_snapshot_sha256": hashlib.sha256(data).hexdigest(),
                "plaintext_sha256": hashlib.sha256(plain).hexdigest(),
            })
        manifest = {
            "snapshot_id": identifier,
            "profile": "full-snapshot-v1" if scope == "all" else PROFILE,
            "mode": mode,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "capture_started_at": started,
            "capture_consistency": "per-database stable main/WAL pair, committed frames only; not an account-wide atomic transaction",
            "source_id": src_id,
            "databases": records,
            "integrity_gaps": integrity_gaps,
        }
        atomic_json(output / "snapshot-manifest.json", manifest)
        validation = validate_snapshot(output)
        if not validation["valid"]:
            raise ValueError("Captured chat schema is not supported by the snapshot reader")
        receipt = {
            "status": "complete_with_index_gaps" if integrity_gaps else "complete",
            "scope": scope,
            "mode": mode,
            "snapshot_id": identifier,
            "snapshot": str(output),
            "source_id": src_id,
            "databases": len(records),
            "decrypted_databases": decrypted_count,
            "reused_databases": reused_count,
            "authenticated_pages": sum(item["pages"] for item in records),
            "validation": "passed_core_with_index_gaps" if integrity_gaps else "passed",
            "integrity_gaps": integrity_gaps,
            "read_only_source": True,
            "keys_persisted": False,
            "scan": statistics,
        }
        atomic_json(vault / "latest.json", receipt)
        return receipt
    except BaseException:
        atomic_json(output / "capture-failed.json", {"status": "incomplete", "usable": False, "at": datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        keys.clear()


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _extract_v2_image_key_live(
    sample_dat: bytes,
    pids: list[int],
    *,
    account_names: tuple[str, ...] = (),
    seconds: int = 30,
) -> dict | None:
    from windows_native import ProcessReader, profile_owner
    from windows_keyscan import scan_v2_image_key_in_regions
    owner = profile_owner()
    deadline = time.monotonic() + max(1, min(seconds, 120))
    for pid in pids:
        if time.monotonic() >= deadline:
            break
        try:
            reader = ProcessReader(pid, owner)
        except RuntimeError:
            continue
        try:
            hit = scan_v2_image_key_in_regions(
                reader.regions(),
                reader.read,
                sample_dat,
                account_names=account_names,
                deadline=deadline,
            )
            if hit:
                return hit
        finally:
            reader.close()
    return None


def _run_windows_images(args) -> int:
    import snapshot_reader as sr
    import snapshot_workflows as wf
    from windows_native import process_ids, secure_output_root

    vault = private_root()
    if args.snapshot:
        snap_root = sr.require_valid(args.snapshot)
    else:
        latest_path = vault / "latest.json"
        if not latest_path.is_file():
            raise ValueError("未找到 latest.json，请先执行 windows capture 或显式传入 --snapshot")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        snap_str = latest.get("snapshot")
        if not isinstance(snap_str, str) or not snap_str:
            raise ValueError("latest.json 缺少有效的 snapshot 路径")
        snap_root = sr.require_valid(Path(snap_str))

    manifest = sr._read_manifest(snap_root)
    attach_dir = args.attach_dir
    if attach_dir is None:
        candidates = discover(args.db_root)
        target_sid = args.source_id or manifest.get("source_id") or ""
        matched_root = None
        if target_sid:
            matched = [r for r, _ in candidates if source_id(r) == target_sid]
            if len(matched) == 1:
                matched_root = matched[0]
        if matched_root is None and len(candidates) == 1:
            matched_root = candidates[0][0]
        if matched_root is not None:
            cand_attach = matched_root.parent / "msg" / "attach"
            if cand_attach.is_dir() and not cand_attach.is_symlink():
                attach_dir = cand_attach

    cache_dir = args.cache_dir
    if (args.decode or args.ocr) and cache_dir is None:
        cache_dir = secure_output_root(sr.DEFAULT_LOCAL_ROOT / "cache" / "images")

    acct_names: list[str] = []
    for raw_hint in (
        str(manifest.get("account_username") or "").strip(),
        attach_dir.parent.parent.name.strip() if (attach_dir and attach_dir.name.casefold() == "attach" and attach_dir.parent.name.casefold() == "msg") else "",
    ):
        if not raw_hint:
            continue
        stripped = re.sub(r"_[0-9a-fA-F]{4}$", "", raw_hint)
        if stripped and stripped not in acct_names:
            acct_names.append(stripped)
        if raw_hint.startswith("wxid_") and raw_hint.count("_") > 1:
            base_wx = "_".join(raw_hint.split("_", 2)[:2])
            if base_wx and base_wx not in acct_names:
                acct_names.append(base_wx)
        if raw_hint not in acct_names:
            acct_names.append(raw_hint)

    memory_fallback = None
    if (args.decode or args.ocr) and not args.no_memory_fallback and not args.aes_key_hex:
        pids = args.pid or process_ids()
        if pids:
            acct_tuple = tuple(acct_names)
            memory_fallback = lambda sample_raw: _extract_v2_image_key_live(
                sample_raw, pids, account_names=acct_tuple, seconds=args.seconds
            )

    try:
        data = wf.snapshot_images(
            sr,
            snap_root,
            args.chat_id,
            start=sr.parse_date(args.start),
            end=sr.parse_date(args.end, True),
            limit=args.limit,
            message_ids=tuple(args.message_id or ()),
            attach_dir=attach_dir,
            kvcomm_dirs=tuple(args.kvcomm_dir or ()),
            decode_images=args.decode,
            ocr=args.ocr,
            aes_key_hex=args.aes_key_hex,
            xor_key=args.xor_key,
            memory_key_fallback=memory_fallback,
            cache_dir=cache_dir,
            confirm_external=args.confirm_external_output,
        )
    except sr.ReaderError as exc:
        raise ValueError(str(exc)) from None
    if args.format == "text":
        print(wf.render_images_text(data))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Windows live chat capture; requires explicit authorization for the selected local account")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "capture"):
        command = sub.add_parser(name)
        command.add_argument("--db-root", help="Explicit local db_storage directory, including a moved data directory")
        if name == "capture":
            command.add_argument("--scope", choices=("chat", "all"), default="chat", help="chat databases (default), or all local account databases")
            command.add_argument("--mode", choices=("full", "incremental"), default="full", help="full decrypts every DB; incremental reuses verified unchanged DBs from latest snapshot")
            command.add_argument("--source-id")
            command.add_argument("--pid", action="append", type=int)
            command.add_argument("--max-db-mib", type=int, default=512)
            command.add_argument("--seconds", type=int, default=90)
    img = sub.add_parser("images", help="定位、自动解码（kvcomm/CNG/内存兜底）并 OCR 识别 Windows 聊天图片")
    img.add_argument("chat_id")
    img.add_argument("--snapshot", type=Path, help="已验证的明文快照目录（默认使用 latest.json）")
    img.add_argument("--db-root", help="显式指定本地 db_storage 目录以自动定位 msg/attach")
    img.add_argument("--source-id", help="多账号时指定 source_id")
    img.add_argument("--attach-dir", type=Path, help="显式指定本账号 msg/attach 目录")
    img.add_argument("--kvcomm-dir", action="append", type=Path, help="额外指定 kvcomm 目录，可重复")
    img.add_argument("--start")
    img.add_argument("--end")
    img.add_argument("--limit", type=int, default=20)
    img.add_argument("--message-id", action="append", help="指定一条或多条 message_id（可跨过 --limit 定位更早图片），可重复")
    img.add_argument("--decode", action="store_true", help="自动解码为可查看图片，写入 NTFS 私有缓存")
    img.add_argument("--ocr", action="store_true", help="解码后用 Windows 原生 WinRT OCR（或 Tesseract）识字；隐含 --decode")
    img.add_argument("--aes-key-hex", help="手动覆盖 V1/V2 .dat 的 16 字节 AES 密钥（32 位十六进制）")
    img.add_argument("--xor-key", type=int, help="手动覆盖 .dat 的单字节 XOR 密钥（0-255）")
    img.add_argument("--cache-dir", type=Path, help="解码缓存目录，默认本机私有 NTFS ACL cache/images")
    img.add_argument("--confirm-external-output", action="store_true")
    img.add_argument("--pid", action="append", type=int)
    img.add_argument("--seconds", type=int, default=30)
    img.add_argument("--no-memory-fallback", action="store_true", help="禁用 kvcomm 未命中时的 Weixin.exe 只读内存密钥回退")
    img.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args(argv)
    try:
        from windows_native import require_windows, process_ids
        require_windows()
        if args.command == "images":
            return _run_windows_images(args)
        if args.command == "capture" and (not 1 <= args.max_db_mib <= 8192 or not 1 <= args.seconds <= 300):
            raise ValueError("Capture bounds are outside the allowed range")
        candidates = discover(args.db_root)
        pids = process_ids()
        if args.command == "discover":
            result = {"accounts": [{"source_id": source_id(root), "chat_databases": len(files)} for root, files in candidates], "weixin_processes": pids, "memory_read": False}
        else:
            root, files = choose_source(candidates, args.source_id)
            if args.scope == "all":
                files = selected_files(root, scope="all")
            selected = args.pid or pids
            if not selected or any(pid not in pids for pid in selected):
                raise ValueError("An authorized running Weixin.exe process is required")
            result = capture(root, files, selected, max_bytes=args.max_db_mib * 1024**2, seconds=args.seconds, scope=args.scope, mode=args.mode)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        # Do not echo Windows errors containing account paths or memory values.
        reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else "Windows capture could not complete; check the local account, permissions, client version, and data path"
        print(json.dumps({"status": "failed", "reason": reason}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
