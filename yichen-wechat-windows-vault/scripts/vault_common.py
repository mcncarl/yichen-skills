from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path

PAGE_SIZE = 4096
SALT_SIZE = 16
KEY_SIZE = 32
RESERVE_SIZE = 80
HMAC_SIZE = 64

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "wechat-windows-vault"
KEYS_FILE = APP_DIR / "keys.json"
DECRYPTED_DIR = APP_DIR / "vault" / "decrypted"

PROFILES = {
    "AB35CFBD7AA9514EC0530747CFC59CAE9DEB0DD46D953548D3CF01919C62A577": {
        "version": "4.1.10.53",
        "pbkdf2_rva": 0x68831B0,
        "prologue": "40535556574154415541564157",
    },
    "4914A621A810ECBC0A132B6FF8F612658CFCE323D3989B3E5FE32D4FF343BA46": {
        "version": "4.1.12.26",
        "pbkdf2_rva": 0x561D730,
        "prologue": "415741564155415456575553B8A8000000",
    },
}


def discover_db_roots() -> list[Path]:
    bases = (
        Path.home() / "Documents" / "xwechat_files",
        Path.home() / "xwechat_files",
    )
    roots = {
        path.resolve()
        for base in bases
        if base.is_dir()
        for path in base.glob("*/db_storage")
        if path.is_dir()
    }
    return sorted(roots)


def choose_db_root(value: str | None = None) -> Path:
    if value:
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"database root does not exist: {root}")
        return root
    roots = discover_db_roots()
    if len(roots) == 1:
        return roots[0]
    if not roots:
        raise FileNotFoundError("no xwechat_files/*/db_storage directory found")
    raise RuntimeError("multiple WeChat accounts found; pass --db-root explicitly")


def collect_databases(root: Path) -> list[tuple[str, Path, bytes]]:
    result = []
    for path in root.rglob("*.db"):
        if path.name.endswith(("-wal", "-shm")):
            continue
        try:
            with path.open("rb") as handle:
                page = handle.read(PAGE_SIZE)
        except OSError:
            continue
        if len(page) == PAGE_SIZE:
            result.append((str(path.relative_to(root)), path, page))
    return sorted(result)


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    mac_salt = bytes(value ^ 0x3A for value in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SIZE)


def verify_key(enc_key: bytes, page: bytes) -> bool:
    if len(enc_key) != KEY_SIZE or len(page) < PAGE_SIZE:
        return False
    mac_key = derive_mac_key(enc_key, page[:SALT_SIZE])
    digest = hmac.new(
        mac_key,
        page[SALT_SIZE : PAGE_SIZE - RESERVE_SIZE + 16],
        hashlib.sha512,
    )
    digest.update(struct.pack("<I", 1))
    return hmac.compare_digest(digest.digest(), page[PAGE_SIZE - HMAC_SIZE : PAGE_SIZE])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def discover_weixin_dlls() -> list[Path]:
    candidates = []
    app_path = None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\Weixin.exe",
        ) as key:
            app_path = Path(winreg.QueryValue(key, None))
    except OSError:
        pass
    if app_path and app_path.exists():
        candidates.extend(app_path.parent.glob("*/Weixin.dll"))
        candidates.append(app_path.parent / "Weixin.dll")
    for base in (
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tencent/Weixin",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Tencent/Weixin",
    ):
        if base.exists():
            candidates.extend(base.glob("*/Weixin.dll"))
    return sorted({p.resolve() for p in candidates if p.is_file()})


def choose_profile(dll_value: str | None = None) -> tuple[Path, str, dict]:
    paths = [Path(dll_value).expanduser().resolve()] if dll_value else discover_weixin_dlls()
    for path in paths:
        if not path.is_file():
            continue
        fingerprint = file_sha256(path)
        profile = PROFILES.get(fingerprint)
        if profile:
            return path, fingerprint, profile
    fingerprints = [file_sha256(path) for path in paths if path.is_file()]
    detail = ", ".join(fingerprints) if fingerprints else "none found"
    raise RuntimeError(f"unknown Weixin.dll fingerprint: {detail}")


def weixin_pids() -> list[int]:
    output = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids = []
    for row in csv.reader(output.splitlines()):
        if len(row) >= 2 and row[0].lower() == "weixin.exe":
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return sorted(set(pids))


def load_keys(path: Path = KEYS_FILE) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def save_keys(value: dict, path: Path = KEYS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="keys-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
