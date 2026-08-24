"""Validate and merge committed encrypted SQLite WAL frames."""

from __future__ import annotations

import os
import struct
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlcipher_codec import (
    CipherProfile,
    DEFAULT_PROFILE,
    decrypt_database,
    decrypt_page,
    sqlite_integrity_check,
)


WAL_MAGIC_LITTLE_ENDIAN_CHECKSUM = 0x377F0682
WAL_MAGIC_BIG_ENDIAN_CHECKSUM = 0x377F0683
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24


@dataclass(frozen=True)
class WalFrame:
    index: int
    page_number: int
    database_pages_after_commit: int
    encrypted_page: bytes


@dataclass(frozen=True)
class WalReport:
    present: bool
    valid_frames: int = 0
    committed_frames: int = 0
    applied_frames: int = 0
    database_pages: int | None = None
    ignored_trailing_bytes: int = 0
    ignored_invalid_frames: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def wal_checksum(
    data: bytes,
    checksum: tuple[int, int] = (0, 0),
    *,
    byteorder: str,
) -> tuple[int, int]:
    """Implement SQLite's rolling WAL checksum."""
    if len(data) % 8 or byteorder not in ("little", "big"):
        raise ValueError("WAL checksum input must contain 8-byte pairs")
    prefix = "<" if byteorder == "little" else ">"
    words = struct.unpack(f"{prefix}{len(data) // 4}I", data)
    first, second = checksum
    for index in range(0, len(words), 2):
        first = (first + words[index] + second) & 0xFFFFFFFF
        second = (second + words[index + 1] + first) & 0xFFFFFFFF
    return first, second


def parse_wal(path: Path, expected_page_size: int) -> tuple[list[WalFrame], int, int]:
    """Return valid frames, ignored trailing byte count, and invalid frame count."""
    data = Path(path).read_bytes()
    if not data:
        return [], 0, 0
    if len(data) < WAL_HEADER_SIZE:
        raise ValueError("WAL is shorter than its header")
    header = data[:WAL_HEADER_SIZE]
    magic, version, page_size = struct.unpack(">III", header[:12])
    if magic == WAL_MAGIC_LITTLE_ENDIAN_CHECKSUM:
        checksum_order = "little"
    elif magic == WAL_MAGIC_BIG_ENDIAN_CHECKSUM:
        checksum_order = "big"
    else:
        raise ValueError(f"unsupported WAL magic: 0x{magic:08x}")
    if version != 3_007_000:
        raise ValueError(f"unsupported WAL format version: {version}")
    if page_size == 1:
        page_size = 65_536
    if page_size != expected_page_size:
        raise ValueError(f"WAL page size {page_size} does not match database {expected_page_size}")
    checksum = wal_checksum(header[:24], byteorder=checksum_order)
    if checksum != struct.unpack(">II", header[24:32]):
        raise ValueError("WAL header checksum mismatch")

    salt = header[16:24]
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    payload = data[WAL_HEADER_SIZE:]
    complete_frames = len(payload) // frame_size
    trailing = len(payload) % frame_size
    frames: list[WalFrame] = []
    invalid_frames = 0
    for index in range(complete_frames):
        offset = WAL_HEADER_SIZE + index * frame_size
        frame_header = data[offset : offset + WAL_FRAME_HEADER_SIZE]
        encrypted_page = data[offset + WAL_FRAME_HEADER_SIZE : offset + frame_size]
        page_number, commit_pages = struct.unpack(">II", frame_header[:8])
        if page_number < 1 or frame_header[8:16] != salt:
            invalid_frames = complete_frames - index
            break
        candidate = wal_checksum(frame_header[:8] + encrypted_page, checksum, byteorder=checksum_order)
        if candidate != struct.unpack(">II", frame_header[16:24]):
            invalid_frames = complete_frames - index
            break
        checksum = candidate
        frames.append(WalFrame(index + 1, page_number, commit_pages, encrypted_page))
    return frames, trailing, invalid_frames


def committed_prefix(frames: list[WalFrame]) -> tuple[list[WalFrame], int | None]:
    last_commit_index = -1
    database_pages: int | None = None
    for index, frame in enumerate(frames):
        if frame.database_pages_after_commit:
            last_commit_index = index
            database_pages = frame.database_pages_after_commit
    return frames[: last_commit_index + 1], database_pages


def decrypt_database_with_wal(
    database: Path,
    wal: Path | None,
    destination: Path,
    key: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> WalReport:
    """Atomically decrypt a DB and merge only the last valid committed WAL prefix."""
    database = Path(database)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent
    )
    os.close(descriptor)
    staging = Path(staging_name)
    staging.unlink()
    try:
        decrypt_database(database, staging, key, profile, run_integrity_check=False)
        report = WalReport(present=False)
        if wal is not None and Path(wal).is_file() and Path(wal).stat().st_size:
            frames, trailing, invalid = parse_wal(Path(wal), profile.page_size)
            if invalid:
                raise ValueError(f"WAL contains {invalid} invalid complete frame(s)")
            committed, database_pages = committed_prefix(frames)
            with database.open("rb") as source:
                salt = source.read(16)
            with staging.open("r+b") as clear:
                for frame in committed:
                    page = decrypt_page(
                        frame.encrypted_page,
                        frame.page_number,
                        key,
                        salt,
                        profile,
                    )
                    clear.seek((frame.page_number - 1) * profile.page_size)
                    clear.write(page)
                if database_pages is not None:
                    clear.truncate(database_pages * profile.page_size)
                clear.flush()
                os.fsync(clear.fileno())
            report = WalReport(
                present=True,
                valid_frames=len(frames),
                committed_frames=len(committed),
                applied_frames=len(committed),
                database_pages=database_pages,
                ignored_trailing_bytes=trailing,
                ignored_invalid_frames=invalid,
            )
        sqlite_integrity_check(staging)
        os.replace(staging, destination)
        return report
    finally:
        if staging.exists():
            staging.unlink()
