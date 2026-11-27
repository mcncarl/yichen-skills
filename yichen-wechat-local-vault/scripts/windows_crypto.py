"""Authenticated WeChat 4.x pages; native Windows CNG AES (no injected code).

Page format follows SQLCipher v4. Windows CNG usage adapted from wcdb-key-tool,
MIT license, pinned provenance under references/windows-live/.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import hmac
import struct
import sys

PAGE = 4096
RESERVE = 80
LOCK_BYTE_OFFSET = 0x40000000
LOCK_BYTE_PAGE = LOCK_BYTE_OFFSET // PAGE + 1  # SQLite 1 GiB lock-byte page (262145)
ZERO_PAGE = bytes(PAGE)


def is_sqlite_lock_byte_page(page: bytes, number: int) -> bool:
    """SQLite/SQLCipher leaves the 4 KiB page at 0x40000000 (page 262145) untouched and all-zero."""
    return number == LOCK_BYTE_PAGE and len(page) == PAGE and page == ZERO_PAGE


def mac_key(key: bytes, salt: bytes) -> bytes:
    if len(key) != 32 or len(salt) != 16:
        raise ValueError("Expected a 32-byte encryption key and 16-byte salt")
    return hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3A for x in salt), 2, 32)


def authenticate(page: bytes, number: int, authentication_key: bytes) -> bool:
    if len(page) != PAGE or not 1 <= number <= 0xFFFFFFFE:
        return False
    start = 16 if number == 1 else 0
    expected = hmac.new(authentication_key, page[start:PAGE - 64] + struct.pack("<I", number), hashlib.sha512).digest()
    return hmac.compare_digest(expected, page[PAGE - 64:])


def verify_enc_key(key: bytes, page: bytes) -> bool:
    return len(page) == PAGE and authenticate(page, 1, mac_key(key, page[:16]))


class CngAES:
    """One algorithm/key handle, independent IV for CBC or None for ECB."""
    def __init__(self, key: bytes, *, chaining_mode: str = "ChainingModeCBC"):
        if sys.platform != "win32":
            raise RuntimeError("Windows CNG requires Windows")
        if chaining_mode not in ("ChainingModeCBC", "ChainingModeECB"):
            raise ValueError("Unsupported AES chaining mode")
        from ctypes import wintypes as w
        self.chaining_mode = chaining_mode
        self.api = c.WinDLL("bcrypt", use_last_error=True)
        declarations = {
            "BCryptOpenAlgorithmProvider": [c.POINTER(w.HANDLE), w.LPCWSTR, w.LPCWSTR, w.ULONG],
            "BCryptSetProperty": [w.HANDLE, w.LPCWSTR, c.c_void_p, w.ULONG, w.ULONG],
            "BCryptGenerateSymmetricKey": [w.HANDLE, c.POINTER(w.HANDLE), c.c_void_p, w.ULONG, c.c_void_p, w.ULONG, w.ULONG],
            "BCryptDecrypt": [w.HANDLE, c.c_void_p, w.ULONG, c.c_void_p, c.c_void_p, w.ULONG, c.c_void_p, w.ULONG, c.POINTER(w.ULONG), w.ULONG],
            "BCryptDestroyKey": [w.HANDLE],
            "BCryptCloseAlgorithmProvider": [w.HANDLE, w.ULONG],
        }
        for name, args in declarations.items():
            method = getattr(self.api, name)
            method.argtypes = args
            method.restype = w.LONG
        self.algorithm, self.key = w.HANDLE(), w.HANDLE()
        self._check(self.api.BCryptOpenAlgorithmProvider(c.byref(self.algorithm), "AES", None, 0))
        try:
            mode = c.create_unicode_buffer(chaining_mode)
            self._check(self.api.BCryptSetProperty(self.algorithm, "ChainingMode", mode, c.sizeof(mode), 0))
            secret = c.create_string_buffer(key, len(key))
            self._check(self.api.BCryptGenerateSymmetricKey(self.algorithm, c.byref(self.key), None, 0, secret, len(key), 0))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(status: int) -> None:
        if status != 0:
            raise RuntimeError("Windows CNG operation failed")

    def decrypt(self, iv: bytes | None, data: bytes) -> bytes:
        from ctypes import wintypes as w
        if len(data) % 16:
            raise ValueError("Invalid AES block length")
        if self.chaining_mode == "ChainingModeCBC":
            if iv is None or len(iv) != 16:
                raise ValueError("Invalid CBC IV length")
            vector = c.create_string_buffer(bytes(iv), len(iv))
            vector_len = len(iv)
        else:
            vector = None
            vector_len = 0
        source = c.create_string_buffer(bytes(data), len(data))
        output = c.create_string_buffer(len(data))
        written = w.ULONG()
        self._check(self.api.BCryptDecrypt(self.key, source, len(data), None, vector, vector_len, output, len(output), c.byref(written), 0))
        if written.value != len(data):
            raise ValueError("Windows CNG returned a partial page")
        return output.raw

    def close(self) -> None:
        if self.key:
            self.api.BCryptDestroyKey(self.key)
            self.key.value = None
        if self.algorithm:
            self.api.BCryptCloseAlgorithmProvider(self.algorithm, 0)
            self.algorithm.value = None


def decrypt_pages(data: bytes, key: bytes, *, aes_factory=None) -> bytes:
    if not data or len(data) % PAGE:
        raise ValueError("Incomplete encrypted database")
    authentication_key = mac_key(key, data[:16])
    aes = (aes_factory or CngAES)(key)
    output = bytearray()
    try:
        for index in range(len(data) // PAGE):
            page = data[index * PAGE:(index + 1) * PAGE]
            number = index + 1
            if is_sqlite_lock_byte_page(page, number):
                output.extend(ZERO_PAGE)
                continue
            if not authenticate(page, number, authentication_key):
                raise ValueError("Database page authentication failed")
            start = 16 if index == 0 else 0
            decoded = aes.decrypt(page[PAGE - RESERVE:PAGE - 64], page[start:PAGE - RESERVE])
            if index == 0:
                # Keep SQLite's reserve byte (80): b-tree offsets depend on it.
                if decoded[:2] != b"\x10\x00" or decoded[4:8] != b"\x50\x40\x20\x20":
                    raise ValueError("Unsupported decrypted SQLite header")
                output.extend(b"SQLite format 3\x00")
            output.extend(decoded)
            output.extend(bytes(RESERVE))
    finally:
        aes.close()
    return bytes(output)
