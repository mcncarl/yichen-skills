#!/usr/bin/env python3
"""Opt-in Frida scan of an explicitly authorized local WeCom PID.

Frida injects the scanner below into that process. The scanner installs no
function hooks and does not deliberately write target memory. Attachment itself
is invasive and requires --confirm-attach; this command never resigns the app,
invokes sudo, retries attachment, or falls back to another capture method.

Supported binary: WeCom 5.0.11/70742 arm64, with the exact UUID below. The
DbKeyManager string is a password: apply the wxSQLite3 AES-128 PDF-style KDF
before trying the raw-key fallback. Save only when all three core databases'
first pages validate. Passwords and unsuccessful candidates are never saved.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import queue
import sys
import threading
import time
from pathlib import Path

SUPPORTED_VERSION = "5.0.11"
SUPPORTED_BUILD = "70742"
SUPPORTED_UUID = "BBC8DDE9AC043DF1BF5AD6887B956966"
CORE_DATABASES = frozenset(("message.db", "session.db", "user.db"))
PDF_PASSWORD_PADDING = bytes.fromhex(
    "28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a"
)


def check_installed_version() -> None:
    try:
        info_path = Path("/Applications/企业微信.app/Contents/Info.plist")
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException):
        raise RuntimeError("cannot verify the installed WeCom version") from None
    if (
        info.get("CFBundleShortVersionString") != SUPPORTED_VERSION
        or str(info.get("CFBundleVersion")) != SUPPORTED_BUILD
    ):
        raise RuntimeError("unsupported WeCom version; only 5.0.11/70742 arm64 is supported")


def rc4(key: bytes, data: bytes) -> bytes:
    """RC4 for the legacy wxSQLite3 password derivation, not page encryption."""
    if not key:
        raise ValueError("RC4 requires a nonempty key")
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    output = bytearray()
    for byte in data:
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        output.append(byte ^ state[(state[i] + state[j]) & 255])
    return bytes(output)


def derive_wxaes128_master(password: bytes) -> bytes:
    """GenerateKeyAES128Cipher, SQLite3MultipleCiphers commit 7a7f16a.

    Ported function: Copyright (c) 2006-2024 Ulrich Telle; MIT license:
    ../../licenses/utelle-SQLite3MultipleCiphers-LICENSE.txt

    https://github.com/utelle/SQLite3MultipleCiphers/blob/
    7a7f16a5270e0157db43c8c3cfcf6088e11f72b1/src/cipher_wxaes128.c#L133-L187
    """
    truncated = password[:32]
    user_pad = truncated + PDF_PASSWORD_PADDING[: 32 - len(truncated)]
    digest = hashlib.md5(PDF_PASSWORD_PADDING).digest()
    for _ in range(50):
        digest = hashlib.md5(digest).digest()
    owner_key = user_pad
    for round_number in range(20):
        round_key = bytes(byte ^ round_number for byte in digest)
        owner_key = rc4(round_key, owner_key)
    digest = hashlib.md5(user_pad + owner_key).digest()
    for _ in range(50):
        digest = hashlib.md5(digest).digest()
    return digest


def validate_password(candidate: bytes, dataset: Path, validate_candidate):
    if len(candidate) != 16:
        return None
    for mode, master in (
        ("wxaes128-pdf-kdf", derive_wxaes128_master(candidate)),
        ("raw", candidate),
    ):
        validated = validate_candidate(master, dataset)
        if CORE_DATABASES.issubset(set(validated)):
            return mode, master, validated
    return None


class StageTimeout(TimeoutError):
    """A controlled timeout containing a stage name only."""


def frida_stage(frida, stage: str, seconds: float, action):
    print(f"stage: {stage}", flush=True)
    cancellation = frida.Cancellable()
    expired = threading.Event()

    def cancel():
        expired.set()
        cancellation.cancel()

    timer = threading.Timer(seconds, cancel)
    timer.daemon = True
    timer.start()
    try:
        with cancellation:
            result = action()
        if expired.is_set():
            print(f"stage timeout: {stage}", flush=True)
            raise StageTimeout(stage)
        return result
    except frida.OperationCancelledError:
        if expired.is_set():
            print(f"stage timeout: {stage}", flush=True)
            raise StageTimeout(stage) from None
        raise
    finally:
        timer.cancel()


AGENT = r"""
'use strict';

const SUPPORTED_UUID = 'BBC8DDE9AC043DF1BF5AD6887B956966';
const DBKEY_MANAGER_VTABLE_OFFSET = 0x0cd5fb50;
const DBKEY_VERSION_OFFSET = 0x60;
const DBKEY_STRING_OFFSET = 0x68;

function mainModule() {
  return Process.enumerateModules().find(
    module => module.path.indexOf('/Contents/MacOS/企业微信') !== -1
  );
}

function pointerPattern(pointer) {
  let value = BigInt(pointer.toString());
  const bytes = [];
  for (let index = 0; index < Process.pointerSize; index++) {
    bytes.push(Number(value & 0xffn).toString(16).padStart(2, '0'));
    value >>= 8n;
  }
  return bytes.join(' ');
}

function isReadable(pointer, size) {
  const range = Process.findRangeByAddress(pointer);
  return range !== null && range.protection.indexOf('r') !== -1 &&
    pointer.add(size).compare(range.base.add(range.size)) <= 0;
}

function moduleUuid(module) {
  const header = module.base;
  if (!isReadable(header, 32) || header.readU32() !== 0xfeedfacf ||
      header.add(4).readU32() !== 0x0100000c) return null;
  const count = header.add(16).readU32();
  const size = header.add(20).readU32();
  if (count > 256 || size > 1048576 || !isReadable(header.add(32), size)) return null;
  const end = header.add(32 + size);
  let command = header.add(32);
  for (let index = 0; index < count; index++) {
    if (command.add(8).compare(end) > 0) return null;
    const type = command.readU32();
    const length = command.add(4).readU32();
    if (length < 8 || command.add(length).compare(end) > 0) return null;
    if (type === 0x1b && length >= 24) {
      return toHex(command.add(8).readByteArray(16)).toUpperCase();
    }
    command = command.add(length);
  }
  return null;
}

function readLibcppString(pointer) {
  try {
    const shortSize = pointer.add(23).readU8();
    if ((shortSize & 0x80) === 0 && shortSize > 0 && shortSize <= 22) {
      return pointer.readByteArray(shortSize);
    }
    const longPointer = pointer.readPointer();
    const longSize = Number(pointer.add(Process.pointerSize).readU64());
    if (!longPointer.isNull() && longSize > 0 && longSize <= 4096) {
      return longPointer.readByteArray(longSize);
    }
  } catch (_) {}
  return null;
}

function toHex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map(byte => byte.toString(16).padStart(2, '0'))
    .join('');
}

const main = mainModule();
if (Process.arch !== 'arm64' || Process.pointerSize !== 8 || !main ||
    moduleUuid(main) !== SUPPORTED_UUID) {
  send({type: 'error', description: 'unsupported runtime architecture or Mach-O UUID'});
} else if (!isReadable(main.base.add(DBKEY_MANAGER_VTABLE_OFFSET), 16)) {
  send({type: 'error', description: 'vtable address is not mapped readably'});
} else {
  const vtable = main.base.add(DBKEY_MANAGER_VTABLE_OFFSET);
  const pattern = pointerPattern(vtable);
  const ranges = Process.enumerateRanges({protection: 'rw-', coalesce: true});
  let matches = 0;
  const seen = new Set();
  for (const range of ranges) {
    let hits = [];
    try {
      hits = Memory.scanSync(range.base, range.size, pattern);
    } catch (_) {
      continue;
    }
    for (const hit of hits) {
      matches += 1;
      const key = readLibcppString(hit.address.add(DBKEY_STRING_OFFSET));
      if (key === null || key.byteLength !== 16) continue;
      const hex = toHex(key);
      if (seen.has(hex)) continue;
      seen.add(hex);
      let version = null;
      try {
        version = hit.address.add(DBKEY_VERSION_OFFSET).readU32();
      } catch (_) {}
      send({type: 'candidate', key: hex, version: version});
    }
  }
  send({type: 'done', ranges: ranges.length, matches: matches, candidates: seen.size});
}
"""


def scan_and_save(args, choose_dataset, save_validated_key, validate_candidate, *, frida=None) -> int:
    # Keep the authorization gate here as well as in the CLI: callers must opt in
    # before importing Frida, inspecting the installation, or reading a dataset.
    if (not getattr(args, "confirm_attach", False) or args.pid <= 0
            or not isinstance(args.data_dir, str) or not args.data_dir.strip()):
        raise RuntimeError("explicit attachment consent, PID and data directory are required")
    if frida is None:
        import frida

    print("stage: preflight", flush=True)
    check_installed_version()
    try:
        dataset = choose_dataset(args.data_dir)
    except (Exception, SystemExit):
        # The existing helper can raise SystemExit, sometimes with a local path.
        raise RuntimeError("cannot select the explicit dataset") from None
    events: queue.Queue[dict] = queue.Queue()
    session = None
    script = None

    def on_message(message, _data):
        if message.get("type") == "send" and isinstance(message.get("payload"), dict):
            events.put(message["payload"])
        elif message.get("type") == "error":
            events.put({"type": "error", "description": "instrumentation failed"})

    validated_key: bytes | None = None
    validated_databases: list[str] = []
    validated_mode: str | None = None
    summary: dict | None = None
    cleanup_failed = False
    try:
        device = frida_stage(frida, "get_local_device", 10, frida.get_local_device)

        def attach():
            nonlocal session
            session = device.attach(args.pid)

        def create_script():
            nonlocal script
            script = session.create_script(AGENT)

        # Assign ownership inside each action so even a late timeout cleans up
        # a resource successfully returned just as cancellation fired.
        frida_stage(frida, "attach", 15, attach)
        frida_stage(frida, "create_script", 10, create_script)
        script.on("message", on_message)
        frida_stage(frida, "load", 30, script.load)
        print("stage: events", flush=True)
        deadline = time.monotonic() + 30
        while summary is None:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                payload = events.get(timeout=remaining)
            except queue.Empty:
                print("stage timeout: events", flush=True)
                raise StageTimeout("events") from None
            kind = payload.get("type")
            if kind == "candidate":
                try:
                    candidate = bytes.fromhex(str(payload.get("key", "")))
                except ValueError:
                    continue
                print("stage: validate", flush=True)
                validated = validate_password(candidate, dataset, validate_candidate)
                if validated is not None and validated_key is None:
                    validated_mode, validated_key, validated_databases = validated
            elif kind == "done":
                summary = payload
            elif kind == "error":
                description = payload.get("description")
                allowed = {
                    "unsupported runtime architecture or Mach-O UUID",
                    "vtable address is not mapped readably",
                }
                raise RuntimeError(
                    description if isinstance(description, str) and description in allowed
                    else "instrumentation failed"
                )
    finally:
        try:
            if script is not None:
                try:
                    frida_stage(frida, "unload", 5, script.unload)
                except Exception as error:
                    cleanup_failed = True
                    if not isinstance(error, StageTimeout):
                        print("stage failed: unload", flush=True)
        finally:
            if session is not None:
                try:
                    frida_stage(frida, "detach", 5, session.detach)
                except Exception as error:
                    cleanup_failed = True
                    if not isinstance(error, StageTimeout):
                        print("stage failed: detach", flush=True)

    if cleanup_failed:
        return 1

    def count(name):
        value = summary.get(name, 0)
        return value if isinstance(value, int) and value >= 0 else 0

    print(
        "scan complete: "
        f"ranges={count('ranges')} "
        f"objects={count('matches')} "
        f"candidates={count('candidates')}",
        flush=True,
    )
    if validated_key is None:
        print("no database-page-validated key found", flush=True)
        return 2

    previous_umask = os.umask(0o077)
    try:
        print("stage: save", flush=True)
        save_validated_key(validated_key, dataset, validated_databases)
    finally:
        os.umask(previous_umask)
    print(f"validated mode: {validated_mode}", flush=True)
    print("validated key saved to the vault private directory with mode 0600", flush=True)
    print(f"validated first-page count: {len(validated_databases)} (core databases: 3/3)", flush=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument(
        "--confirm-attach", action="store_true",
        help="consent to Frida injecting the scanner into this authorized local PID",
    )
    args = parser.parse_args(argv)
    if not args.confirm_attach:
        parser.error("--confirm-attach is required before any system access")
    if args.pid <= 0:
        parser.error("--pid must be a positive integer")
    if not args.data_dir.strip():
        parser.error("--data-dir must name an explicit dataset directory")
    try:
        from wecom_common import choose_dataset, save_validated_key, validate_candidate

        return scan_and_save(args, choose_dataset, save_validated_key, validate_candidate)
    except StageTimeout:
        # The stage was already reported without private arguments or values.
        return 1
    except (Exception, SystemExit) as error:
        # Exception strings from Frida/filesystem helpers may contain account paths.
        # Report only controlled preflight errors or an exception class.
        controlled = {
            "explicit attachment consent, PID and data directory are required",
            "cannot select the explicit dataset",
            "cannot verify the installed WeCom version",
            "unsupported WeCom version; only 5.0.11/70742 arm64 is supported",
            "unsupported runtime architecture or Mach-O UUID",
            "vtable address is not mapped readably",
            "instrumentation failed",
        }
        description = str(error) if str(error) in controlled else type(error).__name__
        print(f"scan failed: {description}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
