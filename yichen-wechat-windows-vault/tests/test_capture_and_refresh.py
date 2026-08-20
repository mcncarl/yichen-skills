from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import capture_keys
import diagnose
import refresh_vault
from key_store import load_keys, save_keys
from test_sqlcipher import make_encrypted


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_key_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "keys.dpapi"
    expected = {"message/message_0.db": bytes(range(32))}
    save_keys(path, expected)
    assert load_keys(path) == expected
    assert bytes(range(32)).hex().encode("ascii") not in path.read_bytes()


class FakeExports:
    def __init__(self, script) -> None:
        self.script = script

    def inspectmodule(self, name: str) -> dict:
        return {"path": str(self.script.dll), "base": "0x1000", "size": 64}

    def install(self, module: str, rva: int, prologue: str) -> bool:
        self.script.callback({"type": "send", "payload": {"kind": "derived-key"}}, self.script.key)
        return True

    def uninstall(self) -> None:
        pass


class FakeScript:
    def __init__(self, dll: Path, key: bytes) -> None:
        self.dll = dll
        self.key = key
        self.callback = None
        self.exports_sync = FakeExports(self)

    def on(self, event: str, callback) -> None:
        self.callback = callback

    def load(self) -> None:
        pass

    def unload(self) -> None:
        pass


class FakeSession:
    def __init__(self, script: FakeScript) -> None:
        self.script = script

    def create_script(self, source: str) -> FakeScript:
        return self.script

    def detach(self) -> None:
        pass


class FakeDevice:
    def __init__(self, script: FakeScript) -> None:
        self.script = script

    def attach(self, pid: int) -> FakeSession:
        return FakeSession(self.script)


class FakeFrida:
    def __init__(self, script: FakeScript) -> None:
        self.device = FakeDevice(script)

    def get_local_device(self) -> FakeDevice:
        return self.device


def test_capture_stores_only_verified_candidate(tmp_path: Path, monkeypatch) -> None:
    key = bytes(range(32))
    db_root = tmp_path / "db"
    db_root.mkdir()
    make_encrypted(db_root / "message_0.db", key, 1)
    dll = tmp_path / "Weixin.dll"
    dll.write_bytes(b"synthetic-dll")
    script = FakeScript(dll, key)
    digest = hashlib.sha256(dll.read_bytes()).hexdigest().upper()
    monkeypatch.setitem(__import__("sys").modules, "frida", FakeFrida(script))
    monkeypatch.setattr(capture_keys, "load_profiles", lambda: {digest: {"module":"Weixin.dll", "rva":1, "prologue":"00"}})
    stored = {}
    monkeypatch.setattr(capture_keys, "load_keys", lambda path: {})
    monkeypatch.setattr(capture_keys, "save_keys", lambda path, keys: stored.update(keys))
    result = capture_keys.capture(db_root, tmp_path / "keys.dpapi", 1, 123)
    assert result["candidate_count"] == 1
    assert result["verified_database_count"] == 1
    assert stored == {"message_0.db": key}
    assert key.hex() not in str(result)


def test_refresh_uses_verified_key_and_incremental_state(tmp_path: Path, monkeypatch) -> None:
    key = bytes(range(32))
    root = tmp_path / "source"
    root.mkdir()
    make_encrypted(root / "message_0.db", key, 1)
    home = tmp_path / "home"
    monkeypatch.setattr(refresh_vault, "load_keys", lambda path: {"message_0.db": key})
    monkeypatch.setattr(refresh_vault, "save_keys", lambda path, keys: None)
    monkeypatch.setattr(refresh_vault, "validate_plaintext", lambda path: None)
    first = refresh_vault.refresh(root, home)
    second = refresh_vault.refresh(root, home)
    assert first["ok"] == 1 and first["failed"] == 0
    assert second["unchanged"] == 1
    assert (home / "vault" / "decrypted" / "message_0.db").is_file()


def test_unknown_dll_is_reported_without_guessing(tmp_path: Path) -> None:
    dll = tmp_path / "Weixin.dll"
    dll.write_bytes(b"unknown-build")
    result = diagnose.inspect_dll(dll)
    assert result["supported"] is False
    assert len(result["sha256"]) == 64
