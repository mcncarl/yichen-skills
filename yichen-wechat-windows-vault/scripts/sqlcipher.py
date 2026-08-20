"""SQLCipher 4 page verification and decryption for authorized local copies."""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from Crypto.Cipher import AES

from vault_common import VaultError


SQLITE_HEADER = b"SQLite format 3\x00"


@dataclass(frozen=True)
class CipherProfile:
    page_size: int = 4096
    reserve_size: int = 80
    hmac_size: int = 64
    hmac_salt_mask: int = 0x3A
    hmac_kdf_iter: int = 2


PROFILE = CipherProfile()


def _hmac_key(raw_key: bytes, salt: bytes, profile: CipherProfile = PROFILE) -> bytes:
    hmac_salt = bytes(byte ^ profile.hmac_salt_mask for byte in salt)
    return hashlib.pbkdf2_hmac(
        "sha512", raw_key, hmac_salt, profile.hmac_kdf_iter, dklen=32
    )


def verify_page(
    page: bytes,
    page_number: int,
    raw_key: bytes,
    salt: bytes,
    profile: CipherProfile = PROFILE,
) -> bool:
    if len(raw_key) != 32 or len(salt) != 16 or len(page) != profile.page_size:
        return False
    offset = 16 if page_number == 1 else 0
    payload_end = profile.page_size - profile.reserve_size + 16
    stored = page[-profile.hmac_size :]
    calculated = hmac.new(
        _hmac_key(raw_key, salt, profile),
        page[offset:payload_end] + struct.pack("<I", page_number),
        hashlib.sha512,
    ).digest()
    return hmac.compare_digest(stored, calculated)


def verify_database(path: Path, raw_key: bytes, profile: CipherProfile = PROFILE) -> bool:
    with path.open("rb") as handle:
        page = handle.read(profile.page_size)
    if len(page) != profile.page_size or page.startswith(SQLITE_HEADER):
        return False
    return verify_page(page, 1, raw_key, page[:16], profile)


def decrypt_database(
    source: Path,
    destination: Path,
    raw_key: bytes,
    profile: CipherProfile = PROFILE,
) -> int:
    if not source.is_file():
        raise VaultError(f"encrypted database not found: {source}")
    if len(raw_key) != 32:
        raise VaultError("database key must contain exactly 32 bytes")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    os.close(fd)
    pages = 0
    try:
        with source.open("rb") as src, open(temp_name, "wb") as dst:
            salt = src.read(16)
            src.seek(0)
            if len(salt) != 16:
                raise VaultError(f"database is too short: {source}")
            while True:
                page = src.read(profile.page_size)
                if not page:
                    break
                pages += 1
                if len(page) != profile.page_size:
                    raise VaultError(f"truncated page {pages}: {source}")
                if not verify_page(page, pages, raw_key, salt, profile):
                    raise VaultError(f"page HMAC verification failed at page {pages}: {source.name}")
                offset = 16 if pages == 1 else 0
                usable_end = profile.page_size - profile.reserve_size
                iv = page[usable_end : usable_end + 16]
                clear = AES.new(raw_key, AES.MODE_CBC, iv).decrypt(page[offset:usable_end])
                if pages == 1:
                    dst.write(SQLITE_HEADER)
                dst.write(clear)
                dst.write(page[usable_end:])
            dst.flush()
            os.fsync(dst.fileno())
        if pages == 0:
            raise VaultError(f"empty database: {source}")
        os.replace(temp_name, destination)
        return pages
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def copy_plain_database(source: Path, destination: Path) -> None:
    with source.open("rb") as handle:
        if handle.read(16) != SQLITE_HEADER:
            raise VaultError(f"not a plaintext SQLite database: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
