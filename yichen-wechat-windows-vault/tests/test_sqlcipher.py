from __future__ import annotations

import hashlib
import hmac
import os
import struct
from pathlib import Path

import pytest
from Crypto.Cipher import AES

from sqlcipher import PROFILE, SQLITE_HEADER, _hmac_key, decrypt_database, verify_database
from vault_common import VaultError


def make_encrypted(path: Path, key: bytes, pages: int = 2) -> list[bytes]:
    salt = bytes(range(16))
    expected = []
    encrypted = []
    for number in range(1, pages + 1):
        prefix = SQLITE_HEADER if number == 1 else b""
        clear = bytes(((index + number) % 251 for index in range(PROFILE.page_size - PROFILE.reserve_size - len(prefix))))
        iv = bytes((number + index) % 256 for index in range(16))
        cipher = AES.new(key, AES.MODE_CBC, iv).encrypt(clear)
        page = (salt if number == 1 else b"") + cipher + iv
        tag = hmac.new(_hmac_key(key, salt), page[(16 if number == 1 else 0):] + struct.pack("<I", number), hashlib.sha512).digest()
        encrypted.append((salt if number == 1 else b"") + cipher + iv + tag)
        expected.append(prefix + clear + iv + tag)
    path.write_bytes(b"".join(encrypted))
    return expected


def test_verify_and_decrypt(tmp_path: Path) -> None:
    key = bytes(range(32))
    source = tmp_path / "encrypted.db"
    expected = make_encrypted(source, key)
    assert verify_database(source, key)
    output = tmp_path / "clear.db"
    assert decrypt_database(source, output, key) == 2
    assert output.read_bytes() == b"".join(expected)


def test_hmac_tamper_fails_closed(tmp_path: Path) -> None:
    key = bytes(range(32))
    source = tmp_path / "encrypted.db"
    make_encrypted(source, key, 1)
    data = bytearray(source.read_bytes())
    data[100] ^= 1
    source.write_bytes(data)
    assert not verify_database(source, key)
    with pytest.raises(VaultError, match="HMAC verification failed"):
        decrypt_database(source, tmp_path / "clear.db", key)
