from __future__ import annotations

import argparse
import threading
import time

import frida

from vault_common import (
    KEYS_FILE,
    choose_db_root,
    choose_profile,
    collect_databases,
    keys_for_db_root,
    load_keys,
    save_keys,
    verify_key,
    weixin_pids,
)


def hook_source(rva: int, prologue: str) -> str:
    return f"""
let attempts = 0;
function installHook() {{
  const module = Process.findModuleByName('Weixin.dll');
  if (module === null) {{
    attempts += 1;
    if (attempts < 600) setTimeout(installHook, 50);
    else send({{type: 'no-module'}});
    return;
  }}
  const target = module.base.add({rva});
  const actual = Array.from(new Uint8Array(target.readByteArray({len(prologue) // 2})))
    .map(x => x.toString(16).padStart(2, '0')).join('');
  if (!actual.startsWith('{prologue.lower()}')) {{
    send({{type: 'prologue-mismatch', actual: actual}});
  }} else {{
    send({{type: 'ready'}});
    Interceptor.attach(target, {{
      onEnter(args) {{
        this.salt = args[2];
        this.saltLen = args[3].toInt32();
        this.iterations = args[4].toInt32();
        this.keyLen = args[6].toInt32();
        this.output = args[7];
      }},
      onLeave(retval) {{
        if (retval.toInt32() !== 1 || this.saltLen !== 16 || this.keyLen !== 32) return;
        if (this.iterations < 2 || this.iterations > 1000000) return;
        try {{
          const hex = b => Array.from(new Uint8Array(b))
            .map(x => x.toString(16).padStart(2, '0')).join('');
          send({{
            type: 'candidate',
            iterations: this.iterations,
            salt: hex(this.salt.readByteArray(16)),
            key: hex(this.output.readByteArray(32))
          }});
        }} catch (_) {{}}
      }}
    }});
  }}
}}
installHook();
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and verify WeChat database keys without printing them")
    parser.add_argument("--db-root")
    parser.add_argument("--dll")
    parser.add_argument("--pid", type=int, action="append")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--launch", action="store_true", help="Launch WeChat suspended, install hooks, then resume")
    args = parser.parse_args()

    root = choose_db_root(args.db_root)
    dll, fingerprint, profile = choose_profile(args.dll)
    databases = collect_databases(root)
    pids = args.pid or weixin_pids()
    if not pids and not args.launch:
        raise RuntimeError("Weixin.exe is not running")

    existing = load_keys()
    verified = keys_for_db_root(existing, root)
    lock = threading.Lock()
    calls = 0
    ready = 0
    sessions = []
    attach_lock = threading.Lock()

    def on_message(message, _data):
        nonlocal calls, ready
        if message.get("type") != "send":
            return
        payload = message.get("payload", {})
        kind = payload.get("type")
        if kind == "ready":
            ready += 1
            print("hook_ready: yes", flush=True)
            return
        if kind in {"no-module", "prologue-mismatch"}:
            print(f"hook_status: {kind}", flush=True)
            return
        if kind != "candidate":
            return
        try:
            key = bytes.fromhex(payload["key"])
            candidate_salt = bytes.fromhex(payload["salt"])
        except (KeyError, ValueError):
            return
        with lock:
            calls += 1
            salt_matches = sum(page[:16] == candidate_salt for _, _, page in databases)
            for relative, path, page in databases:
                if relative in verified:
                    continue
                if verify_key(key, page):
                    verified[relative] = {
                        "enc_key": key.hex(),
                        "salt": page[:16].hex(),
                        "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
                    }
            print(
                f"candidate_calls: {calls}; iterations: {payload.get('iterations')}; "
                f"salt_matches: {salt_matches}; verified_databases: {len(verified)}",
                flush=True,
            )

    device = frida.get_local_device()
    source = hook_source(profile["pbkdf2_rva"], profile["prologue"])
    attached = set()

    def attach_pid(pid):
        with attach_lock:
            if pid in attached:
                return None
            attached.add(pid)
            try:
                session = device.attach(pid)
                script = session.create_script(source)
                script.on("message", on_message)
                script.load()
                sessions.append(session)
                return session
            except frida.ProcessNotFoundError:
                return None
            except frida.PermissionDeniedError as exc:
                print(f"pid {pid}: permission denied: {exc}")
            except frida.InvalidOperationError:
                return None

    def on_spawn(spawn):
        try:
            identifier = (spawn.identifier or "").lower()
            if identifier.endswith("weixin.exe") or identifier == "weixin.exe":
                attach_pid(spawn.pid)
        finally:
            try:
                device.resume(spawn.pid)
            except frida.InvalidOperationError:
                pass

    device.on("spawn-added", on_spawn)
    spawn_gating = False
    try:
        device.enable_spawn_gating()
        spawn_gating = True
    except frida.NotSupportedError:
        pass

    for pid in pids:
        attach_pid(pid)

    if args.launch:
        executable = dll.parent.parent / "Weixin.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"Weixin.exe not found: {executable}")
        launched_pid = device.spawn([str(executable)])
        attach_pid(launched_pid)
        device.resume(launched_pid)
        print(f"wechat_launched: pid={launched_pid}", flush=True)

    if not sessions:
        raise RuntimeError("no attachable Weixin process")
    print(f"capture_seconds: {args.duration}")
    try:
        deadline = time.monotonic() + max(1, args.duration)
        while time.monotonic() < deadline:
            for pid in weixin_pids():
                if pid not in attached:
                    attach_pid(pid)
            time.sleep(0.25)
    finally:
        if spawn_gating:
            try:
                device.disable_spawn_gating()
            except frida.InvalidOperationError:
                pass
        device.off("spawn-added", on_spawn)
        for session in sessions:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass

    result = dict(sorted(verified.items()))
    result["_db_dir"] = str(root)
    result["_capture_profile"] = {
        "version": profile["version"],
        "dll": str(dll),
        "sha256": fingerprint,
        "pbkdf2_rva": hex(profile["pbkdf2_rva"]),
    }
    if verified:
        save_keys(result)
    print(f"capture_complete: calls={calls}; verified_databases={len(verified)}; hooks={ready}")
    print(f"key_file: {KEYS_FILE}")
    return 0 if verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
