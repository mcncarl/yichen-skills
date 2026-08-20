"""Capture and store only page-verified keys during a finite Frida session."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from key_store import load_keys, save_keys
from sqlcipher import SQLITE_HEADER, verify_database
from vault_common import VaultError, require_explicit_dir, vault_home


AGENT = r"""
'use strict';
let listener = null;
rpc.exports = {
  inspectmodule(moduleName) {
    const wanted = moduleName.toLowerCase();
    const module = Process.enumerateModules().find(m => m.name.toLowerCase() === wanted);
    if (module === undefined) throw new Error(moduleName + ' is not loaded');
    return {path: module.path, base: module.base.toString(), size: module.size};
  },
  install(moduleName, rva, expectedHex) {
    const wanted = moduleName.toLowerCase();
    const module = Process.enumerateModules().find(m => m.name.toLowerCase() === wanted);
    if (module === undefined) throw new Error(moduleName + ' is not loaded');
    const target = module.base.add(rva);
    const actual = target.readByteArray(expectedHex.length / 2);
    const actualHex = Array.from(new Uint8Array(actual), b => b.toString(16).padStart(2, '0')).join('');
    if (actualHex !== expectedHex.toLowerCase()) throw new Error('function prologue mismatch');
    listener = Interceptor.attach(target, {
      onEnter(args) {
        this.output = args[7];
        this.keyLength = args[6].toInt32();
      },
      onLeave(retval) {
        if (!retval.isNull() && this.keyLength === 32 && !this.output.isNull()) {
          send({kind: 'derived-key'}, this.output.readByteArray(32));
        }
      }
    });
    return true;
  },
  uninstall() {
    if (listener !== null) { listener.detach(); listener = null; }
  }
};
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def encrypted_databases(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*.db")):
        try:
            with path.open("rb") as handle:
                header = handle.read(16)
            if header != SQLITE_HEADER:
                result.append(path)
        except OSError:
            continue
    return result


def load_profiles() -> dict:
    path = Path(__file__).with_name("profiles.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultError(f"invalid compatibility profile file: {path}") from exc


def capture(db_root: Path, key_file: Path, duration: int, pid: int | None = None) -> dict:
    try:
        import frida
    except ImportError as exc:
        raise VaultError("frida is required; install requirements.txt first") from exc
    device = frida.get_local_device()
    if pid is None:
        matches = [item for item in device.enumerate_processes() if item.name.casefold() == "weixin.exe"]
        if not matches:
            raise VaultError("Weixin.exe is not running")
        if len(matches) != 1:
            raise VaultError("multiple Weixin.exe processes found; pass the PID that loads Weixin.dll")
        pid = matches[0].pid
    session = device.attach(pid)
    script = session.create_script(AGENT)
    candidates: set[bytes] = set()

    def on_message(message, data) -> None:
        payload = message.get("payload", {})
        if message.get("type") == "send" and payload.get("kind") == "derived-key":
            if data is not None and len(data) == 32:
                candidates.add(bytes(data))

    script.on("message", on_message)
    script.load()
    try:
        info = script.exports_sync.inspectmodule("Weixin.dll")
        dll_path = Path(info["path"])
        digest = sha256_file(dll_path)
        profile = load_profiles().get(digest)
        if profile is None:
            raise VaultError(f"unsupported Weixin.dll SHA-256: {digest}")
        script.exports_sync.install(
            profile["module"], int(profile["rva"]), profile["prologue"]
        )
        deadline = time.monotonic() + max(1, min(int(duration), 120))
        while time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        try:
            script.exports_sync.uninstall()
        except Exception:
            pass
        script.unload()
        session.detach()

    databases = encrypted_databases(db_root)
    keys = load_keys(key_file)
    matched_paths: set[str] = set()
    for candidate in candidates:
        for database in databases:
            if verify_database(database, candidate):
                relative = database.relative_to(db_root).as_posix()
                keys[relative] = candidate
                matched_paths.add(relative)
    if matched_paths:
        save_keys(key_file, keys)
    return {
        "capture_seconds": max(1, min(int(duration), 120)),
        "candidate_count": len(candidates),
        "verified_database_count": len(matched_paths),
        "stored_database_key_count": len(keys),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-root", required=True, help="Explicit WeChat db_storage root")
    parser.add_argument("--vault-home")
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    try:
        root = require_explicit_dir(args.db_root, "--db-root")
        result = capture(root, vault_home(args.vault_home) / "keys.dpapi", args.duration, args.pid)
        print(json.dumps(result, ensure_ascii=False))
    except VaultError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
