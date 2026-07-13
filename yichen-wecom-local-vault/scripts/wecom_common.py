#!/usr/bin/env python3
"""Shared paths, discovery, and private key-file helpers."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from wecom_crypto import PAGE_SIZE, database_format, verify_key


CONFIG_PATH = Path("~/.config/wecom-local-vault.json").expanduser()
DEFAULT_VAULT = Path("~/Library/Application Support/wecom-local-vault").expanduser()
KNOWN_ROOTS = (
    Path("~/Library/Containers/com.tencent.WeWorkMac/Data/Library/Application Support/WXWork").expanduser(),
    Path("~/Library/Containers/com.tencent.WeWorkMac/Data/Library/WecomPrivate").expanduser(),
    Path("~/Library/Group Containers/88L2Q4487U.com.tencent.WeWorkMac/WeWorkMac").expanduser(),
)
CORE_DATABASES = ("message.db", "session.db", "user.db")


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def vault_root() -> Path:
    configured = load_config().get("vault_dir")
    return Path(configured).expanduser() if configured else DEFAULT_VAULT


def dataset_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def discover_datasets(explicit: str | None = None) -> list[Path]:
    candidates: set[Path] = set()
    configured = explicit or load_config().get("data_dir")
    if configured:
        path = Path(configured).expanduser()
        if all((path / name).exists() for name in CORE_DATABASES):
            candidates.add(path.resolve())
        return sorted(candidates)

    for root in KNOWN_ROOTS:
        if not root.exists():
            continue
        for message_db in root.rglob("message.db"):
            parent = message_db.parent
            if all((parent / name).is_file() for name in CORE_DATABASES):
                candidates.add(parent.resolve())
    return sorted(candidates)


def choose_dataset(explicit: str | None = None) -> Path:
    datasets = discover_datasets(explicit)
    if not datasets:
        raise SystemExit("未发现企业微信数据集；可用 --data-dir 指定包含 message.db/session.db/user.db 的目录")
    if len(datasets) > 1 and not explicit and not load_config().get("data_dir"):
        labels = ", ".join(dataset_id(path) for path in datasets)
        raise SystemExit(f"发现多个企业微信数据集 ({labels})；请用 --data-dir 明确指定")
    return datasets[0]


def iter_databases(dataset: Path):
    for path in sorted(dataset.rglob("*.db")):
        if path.name.endswith(("-wal", "-shm")) or path.stat().st_size < PAGE_SIZE:
            continue
        yield path.relative_to(dataset), path


def inspect_dataset(dataset: Path) -> dict:
    formats: dict[str, int] = {}
    databases = []
    wal_count = 0
    for relative, path in iter_databases(dataset):
        with path.open("rb") as handle:
            kind = database_format(handle.read(PAGE_SIZE))
        formats[kind] = formats.get(kind, 0) + 1
        has_wal = Path(str(path) + "-wal").exists()
        wal_count += int(has_wal)
        databases.append({
            "name": str(relative),
            "format": kind,
            "size": path.stat().st_size,
            "has_wal": has_wal,
        })
    return {
        "dataset_id": dataset_id(dataset),
        "database_count": len(databases),
        "formats": formats,
        "wal_count": wal_count,
        "databases": databases,
    }


def load_key_file(path: Path | None = None) -> dict:
    if path is not None:
        key_path = path
    else:
        private_dir = vault_root() / "private"
        candidates = sorted(private_dir.glob("keys-*.json")) if private_dir.exists() else []
        legacy = private_dir / "keys.json"
        key_path = candidates[-1] if candidates else legacy
    if not key_path.exists():
        raise SystemExit(f"找不到密钥文件: {key_path}")
    mode = key_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise SystemExit(f"密钥文件权限过宽 ({oct(mode)})，请先改为 0600: {key_path}")
    with key_path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SystemExit("密钥文件格式错误")
    return value


def key_for_database(keys: dict, relative: Path) -> bytes | None:
    candidates = keys.get("keys", {})
    value = candidates.get(str(relative)) or candidates.get(relative.name) or keys.get("global_key")
    if not value:
        return None
    try:
        key = bytes.fromhex(str(value))
    except ValueError:
        return None
    return key if len(key) == 16 else None


def validate_candidate(candidate: bytes, dataset: Path) -> list[str]:
    validated = []
    for relative, path in iter_databases(dataset):
        with path.open("rb") as handle:
            page = handle.read(PAGE_SIZE)
        if database_format(page) == "wecom-wxsqlite3-aes128" and verify_key(candidate, page):
            validated.append(str(relative))
    return validated


def save_validated_key(candidate: bytes, dataset: Path, validated: list[str], destination: Path | None = None) -> Path:
    if not validated:
        raise ValueError("refusing to save an unvalidated key")
    if destination is None:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        destination = vault_root() / "private" / f"keys-{stamp}.json"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing key file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    payload = {
        "version": 1,
        "dataset_id": dataset_id(dataset),
        "captured_at": utc_now(),
        "global_key": candidate.hex(),
        "validated_databases": validated,
    }
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(destination, 0o600)
    return destination


def latest_snapshot(root: Path | None = None) -> Path:
    snapshots = (root or vault_root()) / "snapshots"
    candidates = sorted(path for path in snapshots.glob("*") if path.is_dir()) if snapshots.exists() else []
    if not candidates:
        raise SystemExit("尚无解密快照；请先运行 decrypt")
    return candidates[-1]
