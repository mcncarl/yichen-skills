#!/usr/bin/env python3
"""
WeChat Mac 4.x database key extractor.

Personal-use helper for the local WeChat account on this Mac. It hooks
CommonCrypto's CCKeyDerivationPBKDF in an ad-hoc signed WeChat copy, records
SQLCipher PBKDF2 outputs, and matches them to local database salts.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

KEYS_FILE = Path("~/.config/wechat-keys.json").expanduser()
CONFIG_FILE = Path("~/.config/wechat-daily.json").expanduser()
WECHAT_APP = Path("/Applications/WeChat.app")
WECHAT_COPY = Path("~/Desktop/WeChat.app").expanduser()
FRIDA_LOG = Path("/tmp/wechat_frida_keys.log")
WECHAT_BASE = Path(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
).expanduser()

PAGE_SIZE = 4096
RESERVE = 80
IV_SIZE = 16

DB_RELATIVE_PATHS = {
    "message_0": "message/message_0.db",
    "contact": "contact/contact.db",
    "session": "session/session.db",
    "sns": "sns/sns.db",
    "favorite": "favorite/favorite.db",
}


FRIDA_JS = r"""
'use strict';

const LOG_PATH = '___LOG_PATH___';
const TARGET_SALTS = ___TARGET_SALTS___;
const seen = {};
let hookInstalled = false;

function sendStatus(msg) {
  send({ type: 'status', msg: msg });
}

function hexFromPointer(ptr, len, maxLen) {
  if (ptr.isNull() || len <= 0 || len > maxLen) return null;
  try {
    const bytes = new Uint8Array(ptr.readByteArray(len));
    let out = '';
    for (let i = 0; i < bytes.length; i++) {
      out += ('0' + bytes[i].toString(16)).slice(-2);
    }
    return out;
  } catch (e) {
    return null;
  }
}

function appendJsonLine(obj) {
  try {
    const f = new File(LOG_PATH, 'a');
    f.write(JSON.stringify(obj) + '\n');
    f.flush();
    f.close();
  } catch (e) {
    send({ type: 'error', msg: 'log write failed: ' + e });
  }
}

function isInteresting(rounds, saltHex, dkLen) {
  if (!saltHex || dkLen < 32 || dkLen > 128) return false;
  if (TARGET_SALTS.length === 0) return true;
  if (TARGET_SALTS.indexOf(saltHex) >= 0) return true;
  // SQLCipher may perform a short second derivation for HMAC-related material.
  return rounds === 256000 || rounds === 2 || rounds === 1;
}

function installHookAt(address, owner) {
  Interceptor.attach(address, {
    onEnter: function(args) {
      this.password = args[1];
      this.passwordLen = args[2].toInt32();
      this.salt = args[3];
      this.saltLen = args[4].toInt32();
      this.prf = args[5].toInt32();
      this.rounds = args[6].toInt32();
      this.derivedKey = args[7];
      this.derivedKeyLen = args[8].toInt32();
    },
    onLeave: function(retval) {
      const saltHex = hexFromPointer(this.salt, this.saltLen, 128);
      if (!isInteresting(this.rounds, saltHex, this.derivedKeyLen)) return;

      const dkHex = hexFromPointer(this.derivedKey, this.derivedKeyLen, 128);
      if (!dkHex) return;

      const key = [this.rounds, saltHex, dkHex].join(':');
      if (seen[key]) return;
      seen[key] = true;

      const item = {
        type: 'pbkdf2',
        owner: owner,
        rounds: this.rounds,
        prf: this.prf,
        password_len: this.passwordLen,
        salt_len: this.saltLen,
        salt: saltHex,
        dk_len: this.derivedKeyLen,
        dk: dkHex,
        ts: Date.now()
      };
      appendJsonLine(item);
      send({ type: 'pbkdf2', data: item });
    }
  });
}

function tryInstallHook() {
  if (hookInstalled) return true;

  const modules = Process.enumerateModules();
  for (let i = 0; i < modules.length; i++) {
    let exportsList = [];
    try {
      exportsList = modules[i].enumerateExports();
    } catch (e) {
      continue;
    }
    for (let j = 0; j < exportsList.length; j++) {
      const exp = exportsList[j];
      if (exp.name === 'CCKeyDerivationPBKDF') {
        installHookAt(exp.address, modules[i].name);
        hookInstalled = true;
        sendStatus('Hook installed on ' + modules[i].name + '!' + exp.name);
        return true;
      }
    }
  }
  return false;
}

let attempts = 0;
function installLoop() {
  attempts += 1;
  if (tryInstallHook()) return;
  if (attempts === 1 || attempts % 10 === 0) {
    sendStatus('Waiting for CCKeyDerivationPBKDF (' + attempts + ')');
  }
  setTimeout(installLoop, 500);
}

sendStatus('Frida script loaded. Target salts: ' + TARGET_SALTS.join(', '));
installLoop();
"""


FRIDA_HOST = r"""
import frida
import json
import os
import sys
import time

MODE = "___MODE___"
WECHAT_PATH = "___WECHAT_PATH___"
ATTACH_PID = ___ATTACH_PID___
DURATION = ___DURATION___
LOG_FILE = "___LOG_FILE___"
JS_CODE = ___JS_CODE_JSON___

keys = []

def on_message(message, data):
    if message.get("type") == "send":
        payload = message.get("payload", {})
        if payload.get("type") == "pbkdf2":
            item = payload["data"]
            keys.append(item)
            salt = item.get("salt", "")
            dk = item.get("dk", "")
            print(
                f"  [PBKDF2] rounds={item.get('rounds')} salt={salt[:16]}... "
                f"dk={dk[:24]}... len={item.get('dk_len')}"
            )
        elif payload.get("type") == "status":
            print(f"  {payload.get('msg')}")
        elif payload.get("type") == "error":
            print(f"  [FRIDA ERROR] {payload.get('msg')}")
        else:
            print(f"  [FRIDA] {payload}")
    elif message.get("type") == "error":
        print(f"  [FRIDA ERROR] {message.get('description', message)}")

device = frida.get_local_device()

if MODE == "spawn":
    print("  Spawning signed WeChat copy...")
    pid = device.spawn([WECHAT_PATH])
    session = device.attach(pid)
else:
    print("  Attaching to running signed WeChat copy...")
    if ATTACH_PID <= 0:
        raise SystemExit("No running signed WeChat copy found. Start the signed copy first.")
    pid = ATTACH_PID
    session = device.attach(pid)

script = session.create_script(JS_CODE)
script.on("message", on_message)
script.load()

if MODE == "spawn":
    device.resume(pid)

print("")
print("  Keep this process running, then in WeChat:")
print("    1. Confirm you are logged in.")
print("    2. Open Favorites/收藏.")
print("    3. Open Moments/朋友圈 and scroll once.")
print("  Capturing for %d seconds. Log: %s" % (DURATION, LOG_FILE))
print("")

try:
    for remaining in range(DURATION, 0, -1):
        time.sleep(1)
        if remaining % 15 == 0:
            print(f"  Remaining {remaining}s, captured {len(keys)} PBKDF2 calls...")
except KeyboardInterrupt:
    print("\n  Interrupted; keeping captured calls.")
finally:
    session.detach()
    print(f"\n  Captured {len(keys)} PBKDF2 calls.")
"""


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERROR] {' '.join(cmd)}")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        sys.exit(1)
    return result


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def check_env() -> None:
    print("\n[1/5] Checking environment...")
    if sys.platform != "darwin":
        raise SystemExit("This helper only supports macOS.")
    if not WECHAT_APP.exists():
        raise SystemExit(f"WeChat not found: {WECHAT_APP}")
    if sys.version_info < (3, 9):
        raise SystemExit(f"Python 3.9+ is required. Current: {sys.version}")
    try:
        import frida  # noqa: F401
        print(f"  OK frida {frida.__version__}")
    except ImportError:
        print("  Installing frida...")
        run_cmd([sys.executable, "-m", "pip", "install", "frida", "frida-tools"])
    try:
        from Crypto.Cipher import AES  # noqa: F401
        print("  OK pycryptodome")
    except ImportError:
        print("  Installing pycryptodome...")
        run_cmd([sys.executable, "-m", "pip", "install", "pycryptodome"])


def prepare_wechat(copy_path: Path, skip_prepare: bool) -> None:
    print("\n[2/5] Preparing signed WeChat copy...")
    if skip_prepare:
        print(f"  Skipped. Using {copy_path}")
        return
    if not copy_path.exists():
        print(f"  Copying {WECHAT_APP} -> {copy_path}")
        if copy_path.parent:
            copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(WECHAT_APP, copy_path, symlinks=True)
    else:
        print(f"  Existing copy: {copy_path}")
    print("  Ad-hoc signing the copy...")
    run_cmd(["codesign", "--force", "--deep", "--sign", "-", str(copy_path)])
    print("  OK signed copy is ready")


def find_db_base(preferred: str | None = None) -> tuple[str, Path]:
    if preferred:
        db_base = Path(preferred).expanduser()
        wxid = db_base.parts[-2] if db_base.name == "db_storage" else db_base.name
        return wxid, db_base

    config = load_json(CONFIG_FILE)
    if config.get("db_base_path"):
        db_base = Path(config["db_base_path"]).expanduser()
        wxid = config.get("wxid") or db_base.parts[-2]
        return wxid, db_base

    dirs = sorted(glob.glob(str(WECHAT_BASE / "*/db_storage")))
    if not dirs:
        raise SystemExit(f"No WeChat db_storage directory found under {WECHAT_BASE}")
    db_base = Path(dirs[0])
    return db_base.parts[-2], db_base


def collect_db_info(db_base: Path) -> dict[str, dict[str, str]]:
    info = {}
    for name, rel in DB_RELATIVE_PATHS.items():
        path = db_base / rel
        if not path.exists():
            continue
        with path.open("rb") as f:
            salt = f.read(16).hex()
        info[name] = {"path": str(path), "salt": salt, "size": str(path.stat().st_size)}
    return info


def print_db_info(info: dict[str, dict[str, str]]) -> None:
    print("\n[3/5] Local database salts...")
    for name, item in info.items():
        size_mb = int(item["size"]) / 1024 / 1024
        print(f"  {name:10s} salt={item['salt']} size={size_mb:.2f} MB")


def normalize_targets(targets: str, db_info: dict[str, dict[str, str]]) -> list[str]:
    if targets == "all":
        return list(db_info.keys())
    result = []
    for item in targets.split(","):
        name = item.strip()
        if not name:
            continue
        if name not in DB_RELATIVE_PATHS:
            raise SystemExit(f"Unknown target database: {name}")
        result.append(name)
    return result


def run_frida_capture(
    *,
    mode: str,
    duration: int,
    copy_path: Path,
    target_salts: list[str],
    reset_log: bool,
) -> None:
    print("\n[4/5] Capturing PBKDF2 calls with frida...")
    if reset_log and FRIDA_LOG.exists():
        FRIDA_LOG.unlink()

    wechat_binary = copy_path / "Contents/MacOS/WeChat"
    if not wechat_binary.exists():
        raise SystemExit(f"WeChat executable not found: {wechat_binary}")
    attach_pid = find_running_process(str(wechat_binary)) if mode == "attach" else 0

    js_code = (
        FRIDA_JS
        .replace("___LOG_PATH___", str(FRIDA_LOG))
        .replace("___TARGET_SALTS___", json.dumps(target_salts))
    )
    host = (
        FRIDA_HOST
        .replace("___MODE___", mode)
        .replace("___WECHAT_PATH___", str(wechat_binary))
        .replace("___ATTACH_PID___", str(attach_pid))
        .replace("___DURATION___", str(duration))
        .replace("___LOG_FILE___", str(FRIDA_LOG))
        .replace("___JS_CODE_JSON___", json.dumps(js_code))
    )

    with tempfile.NamedTemporaryFile("w", suffix="_wechat_frida_host.py", delete=False) as f:
        f.write(host)
        host_path = f.name

    try:
        subprocess.run([sys.executable, host_path], check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"frida host failed with exit code {exc.returncode}") from exc
    finally:
        try:
            os.unlink(host_path)
        except OSError:
            pass


def find_running_process(executable_path: str) -> int:
    result = run_cmd(["pgrep", "-f", executable_path], check=False)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return 0


def read_captured_pbkdf2() -> list[dict]:
    if not FRIDA_LOG.exists():
        return []
    rows = []
    with FRIDA_LOG.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") == "pbkdf2" and item.get("dk"):
                rows.append(item)
    return rows


def try_decrypt_page(db_path: str, key_hex: str) -> bool:
    import struct
    from Crypto.Cipher import AES

    try:
        key = bytes.fromhex(key_hex)
        if len(key) != 32:
            return False
        with open(db_path, "rb") as f:
            page = f.read(PAGE_SIZE)
        if len(page) < PAGE_SIZE:
            return False

        enc_start = 16
        enc_size = PAGE_SIZE - RESERVE - enc_start
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_SIZE]
        dec = AES.new(key, AES.MODE_CBC, iv).decrypt(page[enc_start:enc_start + enc_size])

        rebuilt = bytearray(PAGE_SIZE)
        rebuilt[:16] = b"SQLite format 3\x00"
        rebuilt[16:16 + len(dec)] = dec

        page_size = struct.unpack(">H", rebuilt[16:18])[0]
        write_version = rebuilt[18]
        read_version = rebuilt[19]
        reserved = rebuilt[20]
        max_payload = rebuilt[21]
        min_payload = rebuilt[22]
        leaf_payload = rebuilt[23]
        return (
            page_size == PAGE_SIZE
            and write_version in (1, 2)
            and read_version in (1, 2)
            and reserved == RESERVE
            and max_payload == 64
            and min_payload == 32
            and leaf_payload == 32
        )
    except Exception:
        return False


def match_keys(
    db_info: dict[str, dict[str, str]],
    captured: list[dict],
    existing: dict[str, str],
    targets: list[str],
) -> dict[str, str]:
    print("\n[5/5] Matching captured keys to databases...")
    result = dict(existing)

    candidates_by_salt: dict[str, list[str]] = {}
    for item in captured:
        dk = item.get("dk", "")
        salt = item.get("salt", "")
        if len(dk) < 64:
            continue
        key_hex = dk[:64]
        candidates_by_salt.setdefault(salt, [])
        if key_hex not in candidates_by_salt[salt]:
            candidates_by_salt[salt].append(key_hex)

    print(f"  Captured {len(captured)} PBKDF2 rows, {sum(len(v) for v in candidates_by_salt.values())} unique candidates")

    for name in targets:
        item = db_info.get(name)
        if not item:
            print(f"  [WARN] {name}: database not found")
            continue
        if result.get(name) and try_decrypt_page(item["path"], result[name]):
            print(f"  OK {name}: existing key still works")
            continue

        matched = None
        salt_candidates = candidates_by_salt.get(item["salt"], [])
        for key_hex in salt_candidates:
            if try_decrypt_page(item["path"], key_hex):
                matched = key_hex
                break

        if matched is None:
            # Last-chance fallback for logs from older scripts that did not preserve salt.
            for keys in candidates_by_salt.values():
                for key_hex in keys:
                    if try_decrypt_page(item["path"], key_hex):
                        matched = key_hex
                        break
                if matched:
                    break

        if matched:
            result[name] = matched
            print(f"  OK {name}: matched key")
        else:
            print(f"  [MISS] {name}: no matching key yet")

    return result


def update_config(wxid: str, db_base: Path) -> None:
    config = load_json(CONFIG_FILE)
    config["wxid"] = wxid
    config["db_base_path"] = str(db_base)
    save_json(CONFIG_FILE, config)
    print(f"  Updated config: {CONFIG_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and match WeChat Mac 4.x SQLCipher database keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Typical runs:
              python3 extract_keys.py --targets sns,favorite --duration 120
              python3 extract_keys.py --mode attach --targets sns,favorite --duration 90 --skip-prepare

            During capture, open Favorites/收藏 and Moments/朋友圈 in the signed WeChat copy.
            """
        ),
    )
    parser.add_argument("--mode", choices=["spawn", "attach"], default="spawn")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--targets", default="sns,favorite")
    parser.add_argument("--db-base", default=None)
    parser.add_argument("--wechat-copy", default=str(WECHAT_COPY))
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--reuse-log", action="store_true", help="Do not delete /tmp/wechat_frida_keys.log before capture.")
    parser.add_argument("--list-dbs", action="store_true", help="Only print detected database salts.")
    parser.add_argument("--match-only", action="store_true", help="Only match keys from the existing frida log.")
    args = parser.parse_args()

    print("=" * 64)
    print("WeChat Mac 4.x database key extractor")
    print("=" * 64)

    check_env()
    wxid, db_base = find_db_base(args.db_base)
    db_info = collect_db_info(db_base)
    print(f"  wxid: {wxid}")
    print(f"  db_base: {db_base}")
    print_db_info(db_info)

    if args.list_dbs:
        return

    targets = normalize_targets(args.targets, db_info)
    target_salts = [db_info[name]["salt"] for name in targets if name in db_info]

    copy_path = Path(args.wechat_copy).expanduser()
    if not args.match_only:
        prepare_wechat(copy_path, args.skip_prepare)
        run_frida_capture(
            mode=args.mode,
            duration=args.duration,
            copy_path=copy_path,
            target_salts=target_salts,
            reset_log=not args.reuse_log,
        )

    captured = read_captured_pbkdf2()
    existing = load_json(KEYS_FILE)
    matched = match_keys(db_info, captured, existing, targets)

    save_json(KEYS_FILE, matched)
    update_config(wxid, db_base)

    missing = [
        name
        for name in targets
        if name not in matched
        or name not in db_info
        or not try_decrypt_page(db_info[name]["path"], matched[name])
    ]
    print("\n" + "=" * 64)
    if missing:
        print("Not all target keys were captured yet:")
        for name in missing:
            salt = db_info.get(name, {}).get("salt", "?")
            print(f"  - {name}: salt={salt}")
        print("\nRun again while opening those WeChat pages in the signed copy:")
        print(f"  python3 {Path(__file__).resolve()} --mode attach --targets {','.join(missing)} --duration 120 --skip-prepare --reuse-log")
    else:
        print(f"Done. Keys saved to {KEYS_FILE}")
    print("=" * 64)


if __name__ == "__main__":
    main()
