"""Windows DPAPI-backed storage for verified database keys."""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from vault_common import VaultError, ensure_private_dir


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _input_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _crypt(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise VaultError("DPAPI key storage is available only on Windows")
    source, keepalive = _input_blob(data)
    destination = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "Yichen WeChat vault key", None, None, None,
            0x01, ctypes.byref(destination),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x01,
            ctypes.byref(destination),
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def save_keys(path: Path, keys: dict[str, bytes]) -> None:
    ensure_private_dir(path.parent)
    payload = json.dumps({name: value.hex() for name, value in keys.items()}).encode("ascii")
    protected = _crypt(payload, True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(protected)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_keys(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(_crypt(path.read_bytes(), False).decode("ascii"))
        result = {str(name): bytes.fromhex(str(value)) for name, value in raw.items()}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VaultError(f"unable to read DPAPI key store: {path}") from exc
    if any(len(value) != 32 for value in result.values()):
        raise VaultError("DPAPI key store contains an invalid key")
    return result
