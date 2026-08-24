"""Small, auditable SQLCipher page codec for local Weixin snapshots.

Only documented SQLCipher page formats are implemented. The module never
loads Weixin binaries and never writes to a source database.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


SQLITE_HEADER = b"SQLite format 3\x00"
HMAC_SALT_MASK = 0x3A


@dataclass(frozen=True)
class CipherProfile:
    """SQLCipher page geometry and digest algorithms."""

    page_size: int = 4096
    reserve_size: int = 80
    iv_size: int = 16
    hmac_size: int = 64
    hmac_algorithm: str = "sha512"
    kdf_algorithm: str = "sha512"
    kdf_iterations: int = 256_000
    hmac_kdf_iterations: int = 2

    @property
    def reserve_offset(self) -> int:
        return self.page_size - self.reserve_size

    @property
    def hmac_offset(self) -> int:
        return self.reserve_offset + self.iv_size

    def encrypted_offset(self, page_number: int) -> int:
        return 16 if page_number == 1 else 0


DEFAULT_PROFILE = CipherProfile()
COMPATIBLE_PROFILES = (
    DEFAULT_PROFILE,
    CipherProfile(
        page_size=4096,
        reserve_size=48,
        hmac_size=20,
        hmac_algorithm="sha1",
        kdf_algorithm="sha1",
        kdf_iterations=64_000,
    ),
    CipherProfile(
        page_size=1024,
        reserve_size=48,
        hmac_size=20,
        hmac_algorithm="sha1",
        kdf_algorithm="sha1",
        kdf_iterations=64_000,
    ),
)


def _aes_cbc_decrypt(key: bytes, iv: bytes, payload: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("AES-256 key must contain exactly 32 bytes")
    if len(iv) != 16 or not payload or len(payload) % 16:
        raise ValueError("invalid AES-CBC page geometry")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(payload) + decryptor.finalize()


def derive_hmac_key(key: bytes, salt: bytes, profile: CipherProfile = DEFAULT_PROFILE) -> bytes:
    if len(key) != 32 or len(salt) != 16:
        raise ValueError("SQLCipher key/salt length is invalid")
    hmac_salt = bytes(value ^ HMAC_SALT_MASK for value in salt)
    return hashlib.pbkdf2_hmac(
        profile.kdf_algorithm,
        key,
        hmac_salt,
        profile.hmac_kdf_iterations,
        32,
    )


def page_hmac(
    page: bytes,
    page_number: int,
    key: bytes,
    salt: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> bytes:
    """Calculate SQLCipher's HMAC over ciphertext, IV, and LE page number."""
    if len(page) != profile.page_size or page_number < 1:
        raise ValueError("invalid encrypted page")
    start = profile.encrypted_offset(page_number)
    hmac_key = derive_hmac_key(key, salt, profile)
    authenticated = page[start : profile.hmac_offset] + page_number.to_bytes(4, "little")
    return hmac.new(hmac_key, authenticated, profile.hmac_algorithm).digest()


def verify_page_hmac(
    page: bytes,
    page_number: int,
    key: bytes,
    salt: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> bool:
    expected = page[profile.hmac_offset : profile.hmac_offset + profile.hmac_size]
    actual = page_hmac(page, page_number, key, salt, profile)[: profile.hmac_size]
    return len(expected) == profile.hmac_size and hmac.compare_digest(actual, expected)


def decrypt_first_block(
    page: bytes,
    key: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> bytes:
    """Decrypt SQLite header bytes 16..31 from encrypted page one."""
    if len(page) < profile.page_size:
        raise ValueError("database does not contain a complete first page")
    iv = page[profile.reserve_offset : profile.reserve_offset + profile.iv_size]
    return _aes_cbc_decrypt(key, iv, page[16:32])


def looks_like_sqlite_header_tail(
    block: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> bool:
    """Strictly validate SQLite header bytes 16..31."""
    if len(block) < 16:
        return False
    encoded_page_size = int.from_bytes(block[0:2], "big")
    if encoded_page_size == 1:
        encoded_page_size = 65_536
    return (
        encoded_page_size == profile.page_size
        and block[2] in (1, 2)
        and block[3] in (1, 2)
        and block[4] == profile.reserve_size
        and block[5:8] == b"\x40\x20\x20"
    )


def key_matches_page(
    page: bytes,
    key: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
) -> bool:
    try:
        page = page[: profile.page_size]
        salt = page[:16]
        return (
            len(page) == profile.page_size
            and verify_page_hmac(page, 1, key, salt, profile)
            and looks_like_sqlite_header_tail(decrypt_first_block(page, key, profile), profile)
        )
    except (ValueError, TypeError):
        return False


def match_key_material(page: bytes, material: bytes) -> tuple[bytes, CipherProfile, str] | None:
    """Try raw AES material and documented SQLCipher KDF profiles."""
    salt = page[:16]
    for profile in COMPATIBLE_PROFILES:
        candidate_page = page[: profile.page_size]
        if len(candidate_page) == profile.page_size and key_matches_page(candidate_page, material, profile):
            return material, profile, "raw"
        derived = hashlib.pbkdf2_hmac(
            profile.kdf_algorithm,
            material,
            salt,
            profile.kdf_iterations,
            32,
        )
        if len(candidate_page) == profile.page_size and key_matches_page(candidate_page, derived, profile):
            return derived, profile, f"sqlcipher-kdf/{profile.kdf_algorithm}"
    return None


def decrypt_page(
    page: bytes,
    page_number: int,
    key: bytes,
    salt: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
    *,
    verify_hmac: bool = True,
) -> bytes:
    if len(page) != profile.page_size or page_number < 1:
        raise ValueError(f"page {page_number} has invalid size")
    if verify_hmac and not verify_page_hmac(page, page_number, key, salt, profile):
        raise ValueError(f"page {page_number} SQLCipher HMAC mismatch")
    prefix = profile.encrypted_offset(page_number)
    iv = page[profile.reserve_offset : profile.reserve_offset + profile.iv_size]
    clear = bytearray(_aes_cbc_decrypt(key, iv, page[prefix : profile.reserve_offset]))
    if page_number == 1:
        if not looks_like_sqlite_header_tail(clear[:16], profile):
            raise ValueError("key/profile did not produce a valid SQLite header")
        clear = bytearray(SQLITE_HEADER) + clear
    clear.extend(b"\x00" * profile.reserve_size)
    if len(clear) != profile.page_size:
        raise AssertionError("decrypted page geometry is inconsistent")
    return bytes(clear)


def sqlite_integrity_check(path: Path) -> None:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        quick = connection.execute("PRAGMA quick_check").fetchone()
        full = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not quick or quick[0] != "ok" or not full or full[0] != "ok":
        raise ValueError(f"SQLite integrity checks failed: quick={quick!r}, full={full!r}")


def decrypt_database(
    source: Path,
    destination: Path,
    key: bytes,
    profile: CipherProfile = DEFAULT_PROFILE,
    *,
    run_integrity_check: bool = True,
) -> None:
    """Decrypt a base database atomically, verifying every encrypted page."""
    source = Path(source)
    destination = Path(destination)
    size = source.stat().st_size
    if size == 0 or size % profile.page_size:
        raise ValueError(f"encrypted database size is not a page multiple: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as encrypted, os.fdopen(descriptor, "wb") as clear:
            first_page = encrypted.read(profile.page_size)
            salt = first_page[:16]
            clear.write(decrypt_page(first_page, 1, key, salt, profile))
            for page_number in range(2, size // profile.page_size + 1):
                page = encrypted.read(profile.page_size)
                clear.write(decrypt_page(page, page_number, key, salt, profile))
            clear.flush()
            os.fsync(clear.fileno())
        if run_integrity_check:
            sqlite_integrity_check(temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
