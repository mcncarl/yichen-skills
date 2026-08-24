"""Read-only Windows process-memory capture for SQLCipher keys.

The implementation uses only PROCESS_QUERY_INFORMATION and PROCESS_VM_READ.
It never injects code, hooks functions, starts, suspends, or terminates Weixin.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sqlcipher_codec import CipherProfile, DEFAULT_PROFILE, key_matches_page


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE_MASK = 0x02 | 0x04 | 0x08 | 0x20 | 0x40 | 0x80
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
SCAN_CHUNK_SIZE = 16 * 1024 * 1024
SCAN_OVERLAP = 192
MAX_REGION_SIZE = 2 * 1024 * 1024 * 1024


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
if kernel32 is not None:
    kernel32.CreateToolhelp32Snapshot.argtypes = (wt.DWORD, wt.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Process32FirstW.argtypes = (wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32FirstW.restype = wt.BOOL
    kernel32.Process32NextW.argtypes = (wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.restype = wt.BOOL
    kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.VirtualQueryEx.argtypes = (
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    )
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = (
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    kernel32.ReadProcessMemory.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)
    kernel32.CloseHandle.restype = wt.BOOL


@dataclass(frozen=True)
class DatabaseTarget:
    database: str
    path: Path
    page: bytes
    profile: CipherProfile = DEFAULT_PROFILE

    @property
    def salt(self) -> bytes:
        return self.page[:16]

    @classmethod
    def from_path(cls, database: str, path: Path) -> "DatabaseTarget":
        path = Path(path)
        with path.open("rb") as stream:
            page = stream.read(DEFAULT_PROFILE.page_size)
        if len(page) != DEFAULT_PROFILE.page_size:
            raise ValueError(f"database has no complete first page: {database}")
        return cls(database=database, path=path, page=page)


@dataclass(frozen=True)
class Candidate:
    target: DatabaseTarget
    key_address: int


@dataclass(frozen=True)
class Match:
    database: str
    pid: int
    key: bytes
    profile: CipherProfile
    key_kind: str = "sqlcipher-unshield-window"

    def safe_dict(self) -> dict:
        return {
            "database": self.database,
            "pid": self.pid,
            "key_fingerprint": hashlib.sha256(self.key).hexdigest()[:16],
            "page_size": self.profile.page_size,
            "reserve_size": self.profile.reserve_size,
            "key_kind": self.key_kind,
        }


@dataclass(frozen=True)
class CaptureReport:
    pids_checked: int
    codec_contexts: int
    monitored_buffers: int
    matches: tuple[Match, ...]

    def safe_dict(self) -> dict:
        return {
            "pids_checked": self.pids_checked,
            "codec_contexts": self.codec_contexts,
            "monitored_buffers": self.monitored_buffers,
            "matched_databases": sorted(match.database for match in self.matches),
            "matched_count": len(self.matches),
        }


def _require_windows() -> None:
    if kernel32 is None:
        raise RuntimeError("Weixin process capture is available only on Windows")


def find_process_ids(executable: str = "Weixin.exe") -> list[int]:
    _require_windows()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    result: list[int] = []
    try:
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == executable.casefold():
                result.append(int(entry.th32ProcessID))
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _read_region(handle: int, address: int, size: int) -> bytes:
    if not address or size <= 0:
        return b""
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(read),
    ):
        return b""
    return buffer.raw[: read.value]


def _readable_regions(handle: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    address = 0
    info = MEMORY_BASIC_INFORMATION()
    while kernel32.VirtualQueryEx(
        handle,
        ctypes.c_void_p(address),
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        base = int(info.BaseAddress or 0)
        size = int(info.RegionSize)
        if (
            info.State == MEM_COMMIT
            and info.Protect & READABLE_MASK
            and not info.Protect & (PAGE_GUARD | PAGE_NOACCESS)
            and 0 < size <= MAX_REGION_SIZE
        ):
            result.append((base, size))
        next_address = base + max(size, 0x1000)
        if next_address <= address:
            break
        address = next_address
    return result


def _address_is_readable(address: int, regions: list[tuple[int, int]], size: int) -> bool:
    return any(base <= address and address + size <= base + length for base, length in regions)


def _iter_region_data(handle: int, base: int, size: int):
    offset = 0
    carry = b""
    while offset < size:
        requested = min(SCAN_CHUNK_SIZE, size - offset)
        current = _read_region(handle, base + offset, requested)
        if not current:
            offset += requested
            carry = b""
            continue
        combined = carry + current
        yield base + offset - len(carry), combined
        carry = combined[-SCAN_OVERLAP:]
        offset += len(current)


def _codec_patterns(targets: list[DatabaseTarget]) -> tuple[bytes, ...]:
    profiles = {(target.profile.page_size, target.profile.reserve_size) for target in targets}
    patterns: list[bytes] = []
    for page_size, reserve_size in sorted(profiles):
        hmac_size = 64 if reserve_size == 80 else 20
        for keyspec_size in (99, 163):
            patterns.append(
                struct.pack(
                    "<9I",
                    16,
                    32,
                    16,
                    16,
                    page_size,
                    keyspec_size,
                    reserve_size,
                    hmac_size,
                    0,
                )
            )
    return tuple(patterns)


def _find_candidates(
    handle: int,
    regions: list[tuple[int, int]],
    targets: list[DatabaseTarget],
) -> tuple[list[Candidate], int]:
    by_salt = {target.salt: target for target in targets}
    context_bases: set[int] = set()
    for base, size in regions:
        for chunk_base, data in _iter_region_data(handle, base, size):
            for pattern in _codec_patterns(targets):
                cursor = data.find(pattern)
                while cursor >= 0:
                    context_base = chunk_base + cursor - 12
                    if _address_is_readable(context_base, regions, 136):
                        context_bases.add(context_base)
                    cursor = data.find(pattern, cursor + 1)

    candidates: dict[tuple[str, int], Candidate] = {}
    matched_contexts = 0
    for context_base in context_bases:
        codec = _read_region(handle, context_base, 136)
        if len(codec) != 136:
            continue
        salt_address = struct.unpack_from("<Q", codec, 72)[0]
        if not _address_is_readable(salt_address, regions, 16):
            continue
        target = by_salt.get(_read_region(handle, salt_address, 16))
        if target is None:
            continue
        matched_contexts += 1
        for context_offset in (104, 112):
            cipher_address = struct.unpack_from("<Q", codec, context_offset)[0]
            if not _address_is_readable(cipher_address, regions, 24):
                continue
            cipher = _read_region(handle, cipher_address, 24)
            if len(cipher) != 24:
                continue
            derive_key, pass_size = struct.unpack_from("<ii", cipher, 0)
            key_address = struct.unpack_from("<Q", cipher, 8)[0]
            if (
                derive_key in (0, 1)
                and 0 <= pass_size <= 4096
                and _address_is_readable(key_address, regions, 32)
            ):
                candidate = Candidate(target, key_address)
                candidates[(target.database, key_address)] = candidate
    return list(candidates.values()), matched_contexts


def _monitor_candidates(
    handle: int,
    pid: int,
    candidates: list[Candidate],
    duration: float,
) -> tuple[Match, ...]:
    if duration < 0:
        raise ValueError("capture duration cannot be negative")
    matches: dict[str, Match] = {}
    lock = threading.Lock()
    deadline = time.monotonic() + duration
    stop = threading.Event()

    def validate(candidate: Candidate, key: bytes) -> None:
        if len(key) != 32 or not key_matches_page(candidate.target.page, key, candidate.target.profile):
            return
        with lock:
            matches.setdefault(
                candidate.target.database,
                Match(
                    database=candidate.target.database,
                    pid=pid,
                    key=key,
                    profile=candidate.target.profile,
                ),
            )
            if len(matches) == len({item.target.database for item in candidates}):
                stop.set()

    for candidate in candidates:
        validate(candidate, _read_region(handle, candidate.key_address, 32))
    if stop.is_set() or duration == 0:
        return tuple(matches.values())

    def worker(worker_index: int) -> None:
        ordered = candidates[worker_index % len(candidates) :] + candidates[: worker_index % len(candidates)]
        previous: dict[int, bytes] = {}
        while not stop.is_set() and time.monotonic() < deadline:
            for candidate in ordered:
                if candidate.target.database in matches:
                    continue
                key = _read_region(handle, candidate.key_address, 32)
                if len(key) != 32 or previous.get(candidate.key_address) == key:
                    continue
                previous[candidate.key_address] = key
                validate(candidate, key)

    worker_count = min(8, max(2, len(candidates) * 2))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(worker, index) for index in range(worker_count)]
        for future in futures:
            future.result()
    return tuple(matches.values())


def capture_keys(
    targets: list[DatabaseTarget],
    duration: float,
    pids: list[int] | None = None,
) -> CaptureReport:
    """Find target codec contexts and capture only keys that pass strict validation."""
    _require_windows()
    if not targets:
        raise ValueError("at least one database target is required")
    checked = 0
    best: tuple[int, int, list[Candidate], int] | None = None
    for pid in pids or find_process_ids():
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            continue
        checked += 1
        regions = _readable_regions(handle)
        candidates, contexts = _find_candidates(handle, regions, targets)
        if not best or len(candidates) > len(best[2]):
            if best:
                kernel32.CloseHandle(best[1])
            best = (pid, handle, candidates, contexts)
        else:
            kernel32.CloseHandle(handle)
    if not best:
        raise RuntimeError("no readable Weixin.exe process was found")
    pid, handle, candidates, contexts = best
    try:
        if not candidates:
            raise RuntimeError("no matching SQLCipher contexts were found in the running Weixin process")
        matches = _monitor_candidates(handle, pid, candidates, duration)
        return CaptureReport(
            pids_checked=checked,
            codec_contexts=contexts,
            monitored_buffers=len(candidates),
            matches=matches,
        )
    finally:
        kernel32.CloseHandle(handle)
