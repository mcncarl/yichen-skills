#!/usr/bin/env python3
"""Read-only Mach VM scanner for WeCom DbKeyManager on macOS.

This scanner does not inject code.  It searches the live process memory for the
DbKeyManager vtable observed in the 5.x macOS binary, then reads the
std::string at object+0x68 where the current raw wxSQLite3 key is stored.
The key is never printed; validated keys are saved through wecom_common.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from wecom_common import (
    choose_dataset,
    discover_datasets,
    dataset_id,
    inspect_dataset,
    iter_databases,
    save_validated_key,
    validate_candidate,
    vault_root,
)


UNSLID_IMAGE_BASE = 0x100000000
UNSLID_DBKEY_MANAGER_VTABLE = 0x10C3550C8
DBKEY_VERSION_OFFSET = 0x60
DBKEY_STRING_OFFSET = 0x68
STD_STRING_SIZE = 24

KERN_SUCCESS = 0
VM_REGION_BASIC_INFO_64 = 9
VM_REGION_BASIC_INFO_COUNT_64 = 9
VM_PROT_READ = 1
VM_PROT_WRITE = 2
CHUNK_SIZE = 8 * 1024 * 1024


class VmRegionBasicInfo64(ctypes.Structure):
    _fields_ = [
        ("protection", ctypes.c_uint32),
        ("max_protection", ctypes.c_uint32),
        ("inheritance", ctypes.c_uint32),
        ("shared", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("offset", ctypes.c_uint64),
        ("behavior", ctypes.c_uint32),
        ("user_wired_count", ctypes.c_uint16),
    ]


def _libc():
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.task_for_pid.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
    libc.task_for_pid.restype = ctypes.c_int
    libc.mach_vm_region.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    libc.mach_vm_region.restype = ctypes.c_int
    libc.mach_vm_read_overwrite.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
    ]
    libc.mach_vm_read_overwrite.restype = ctypes.c_int
    return libc


def _mach_task_self(libc) -> int:
    return ctypes.c_uint32.in_dll(libc, "mach_task_self_").value


def wecom_pids() -> list[int]:
    out = subprocess.check_output(["/bin/ps", "-axo", "pid=,command="], text=True)
    pids = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        if "/Applications/企业微信.app/Contents/MacOS/企业微信" in command:
            try:
                pids.append(int(pid_text))
            except ValueError:
                pass
    return pids


def choose_pid(explicit: int | None = None) -> int:
    if explicit:
        return explicit
    pids = wecom_pids()
    if not pids:
        raise SystemExit("未发现正在运行的企业微信主进程")
    return pids[0]


def load_address(pid: int) -> int:
    out = subprocess.check_output(["/usr/bin/vmmap", str(pid)], text=True, stderr=subprocess.STDOUT)
    match = re.search(r"Load Address:\s+(0x[0-9a-fA-F]+)", out)
    if not match:
        raise SystemExit("无法从 vmmap 输出解析企业微信 Load Address")
    return int(match.group(1), 16)


def candidate_path() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    path = vault_root() / "private" / f"dbkey-manager-candidates-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    return path


def choose_scan_dataset(explicit: str | None = None) -> Path:
    if explicit:
        return choose_dataset(explicit)
    datasets = discover_datasets()
    if not datasets:
        return choose_dataset(None)
    if len(datasets) == 1:
        return datasets[0]
    return sorted(
        datasets,
        key=lambda path: (inspect_dataset(path)["wal_count"], inspect_dataset(path)["database_count"]),
    )[-1]


def read_memory(libc, task: int, address: int, size: int) -> bytes | None:
    if size <= 0:
        return b""
    buf = ctypes.create_string_buffer(size)
    out_size = ctypes.c_uint64(0)
    kr = libc.mach_vm_read_overwrite(
        task,
        ctypes.c_uint64(address),
        ctypes.c_uint64(size),
        ctypes.cast(buf, ctypes.c_void_p).value,
        ctypes.byref(out_size),
    )
    if kr != KERN_SUCCESS or out_size.value == 0:
        return None
    return buf.raw[: out_size.value]


def parse_libcpp_string(libc, task: int, object_address: int, raw: bytes) -> bytes | None:
    if len(raw) != STD_STRING_SIZE:
        return None
    # Apple libc++ alternate layout:
    # short string: bytes[0:23] data, bytes[23] size.
    short_size = raw[23]
    if 0 < short_size <= 23:
        return raw[:short_size]
    # long string: pointer, size, capacity/high-bit marker.
    pointer, size, _capacity = struct.unpack("<QQQ", raw)
    if not (0 < size <= 4096 and pointer > 0):
        return None
    data = read_memory(libc, task, pointer, int(size))
    return data if data and len(data) == size else None


def scan_root(args: argparse.Namespace) -> int:
    libc = _libc()
    self_task = _mach_task_self(libc)
    task = ctypes.c_uint32(0)
    kr = libc.task_for_pid(self_task, args.pid, ctypes.byref(task))
    if kr != KERN_SUCCESS:
        print(f"task_for_pid failed: kern_return={kr}", file=sys.stderr)
        return 73

    needle = struct.pack("<Q", args.vtable)
    candidates: list[dict] = []
    regions = 0
    scanned = 0
    matches = 0
    address = ctypes.c_uint64(0)

    while True:
        size = ctypes.c_uint64(0)
        info = VmRegionBasicInfo64()
        count = ctypes.c_uint32(VM_REGION_BASIC_INFO_COUNT_64)
        object_name = ctypes.c_uint32(0)
        kr = libc.mach_vm_region(
            task.value,
            ctypes.byref(address),
            ctypes.byref(size),
            VM_REGION_BASIC_INFO_64,
            ctypes.byref(info),
            ctypes.byref(count),
            ctypes.byref(object_name),
        )
        if kr != KERN_SUCCESS:
            break

        start = int(address.value)
        region_size = int(size.value)
        next_address = start + region_size
        protection = int(info.protection)
        if protection & VM_PROT_READ and protection & VM_PROT_WRITE:
            regions += 1
            offset = 0
            overlap = b""
            while offset < region_size:
                to_read = min(CHUNK_SIZE, region_size - offset)
                chunk = read_memory(libc, task.value, start + offset, to_read)
                if not chunk:
                    offset += to_read
                    overlap = b""
                    continue
                data = overlap + chunk
                base = start + offset - len(overlap)
                pos = data.find(needle)
                while pos != -1:
                    object_addr = base + pos
                    raw_object = read_memory(
                        libc,
                        task.value,
                        object_addr + DBKEY_VERSION_OFFSET,
                        DBKEY_STRING_OFFSET - DBKEY_VERSION_OFFSET + STD_STRING_SIZE,
                    )
                    if raw_object and len(raw_object) >= 8 + STD_STRING_SIZE:
                        version = struct.unpack_from("<I", raw_object, 0)[0]
                        string_raw = raw_object[DBKEY_STRING_OFFSET - DBKEY_VERSION_OFFSET :][:STD_STRING_SIZE]
                        key = parse_libcpp_string(libc, task.value, object_addr + DBKEY_STRING_OFFSET, string_raw)
                        if key and len(key) == 16 and len(set(key)) >= 6:
                            matches += 1
                            candidates.append(
                                {
                                    "object_address": hex(object_addr),
                                    "dbkey_version": version,
                                    "candidate_hex": key.hex(),
                                }
                            )
                    pos = data.find(needle, pos + 1)
                scanned += len(chunk)
                overlap = data[-(len(needle) - 1) :]
                offset += to_read
        address.value = next_address

    payload = {
        "version": 1,
        "pid": args.pid,
        "vtable": hex(args.vtable),
        "scanned_regions": regions,
        "scanned_bytes": scanned,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    out = Path(args.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if sudo_uid and sudo_gid:
        os.chown(tmp, int(sudo_uid), int(sudo_gid))
    os.replace(tmp, out)
    print(f"read-only scan complete: regions={regions} scanned_mb={scanned // 1024 // 1024} candidates={len(candidates)}")
    return 0 if candidates else 2


def validate_candidate_file(path: Path, dataset: Path) -> Path | None:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    for item in payload.get("candidates", []):
        try:
            candidate = bytes.fromhex(str(item.get("candidate_hex", "")))
        except ValueError:
            continue
        validated = validate_candidate(candidate, dataset)
        if validated:
            return save_validated_key(candidate, dataset, validated)
    return None


def run_scan(args: argparse.Namespace) -> int:
    dataset = choose_scan_dataset(args.data_dir)
    info = inspect_dataset(dataset)
    pid = choose_pid(args.pid)
    load = load_address(pid)
    vtable = load + (UNSLID_DBKEY_MANAGER_VTABLE - UNSLID_IMAGE_BASE)
    out = candidate_path()
    print(
        json.dumps(
            {
                "pid": pid,
                "dataset_id": dataset_id(dataset),
                "encrypted_databases": info["formats"].get("wecom-wxsqlite3-aes128", 0),
                "load_address": hex(load),
                "dbkey_manager_vtable": hex(vtable),
                "candidate_file": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if os.geteuid() == 0:
        root_args = argparse.Namespace(pid=pid, vtable=vtable, out=str(out))
        rc = scan_root(root_args)
    else:
        if not args.confirm_sudo:
            print("需要管理员权限只读扫描企业微信内存；如确认，重新运行并加 --confirm-sudo。")
            return 64
        command = [
            "sudo",
            sys.executable,
            str(Path(__file__).resolve()),
            "root-scan",
            "--pid",
            str(pid),
            "--vtable",
            hex(vtable),
            "--out",
            str(out),
        ]
        print("即将请求 macOS 管理员密码；请只在本机终端输入，不要发到聊天里。")
        rc = subprocess.call(command)

    if rc not in (0, 2) or not out.exists():
        print("未能读取企业微信内存；没有写入密钥。")
        return rc if rc else 1
    saved = validate_candidate_file(out, dataset)
    if not saved:
        print("内存中未找到可验证的 DbKeyManager raw key；没有写入密钥。")
        return 2
    print(f"VALIDATED_AND_SAVED {saved}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan live WeCom DbKeyManager memory without injection")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--pid", type=int)
    scan.add_argument("--data-dir")
    scan.add_argument("--confirm-sudo", action="store_true")
    root = sub.add_parser("root-scan")
    root.add_argument("--pid", type=int, required=True)
    root.add_argument("--vtable", type=lambda value: int(value, 0), required=True)
    root.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "root-scan":
        return scan_root(args)
    return run_scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
