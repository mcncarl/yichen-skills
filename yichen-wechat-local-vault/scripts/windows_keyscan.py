"""Read-only Config.Cipher candidate decoding, adapted from wcdb-key-tool (MIT).
No process attachment, injection, debugger, key persistence, or CLI side effects.
See references/windows-live/PROVENANCE.md for pinned source and license.
"""
from __future__ import annotations
import struct
import re
from windows_crypto import verify_enc_key
KEY_SZ = 32
_HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")
WINDOWS_CONFIG_CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
WINDOWS_CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
WINDOWS_MAX_USER_ADDRESS = 0x0000_8000_0000_0000
WINDOWS_CONFIG_BLOB_MAX = 1024
WINDOWS_CONFIG_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")


def _xor_repeat(data: bytes, mask: bytes) -> bytes:
    return bytes(value ^ mask[index % len(mask)] for index, value in enumerate(data))


def _u64_from(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        return 0
    return struct.unpack_from("<Q", data, offset)[0]


def _probable_32_byte_key(data: bytes) -> bool:
    return len(data) == KEY_SZ and len(set(data)) >= 15 and data not in {b"\x00" * KEY_SZ, b"\xff" * KEY_SZ}


def _find_bytes_in_regions(
    regions: list[tuple[int, int]],
    read_region: callable,
    needle: bytes,
) -> set[int]:
    addresses: set[int] = set()
    overlap = max(0, len(needle) - 1)
    for data_base, haystack in _iter_windows_region_chunks(regions, read_region, overlap=overlap):
        pos = haystack.find(needle)
        while pos >= 0:
            addresses.add(data_base + pos)
            pos = haystack.find(needle, pos + 1)
    return addresses


def _iter_windows_region_chunks(
    regions: list[tuple[int, int]],
    read_region: callable,
    *,
    chunk_size: int = 2 * 1024 * 1024,
    overlap: int = 0,
):
    """Yield readable chunks from Windows process regions with optional overlap."""
    for base, size in regions:
        offset = 0
        tail = b""
        tail_base = base
        while offset < size:
            current_size = min(chunk_size, size - offset)
            chunk = read_region(base + offset, current_size) or b""
            data_base = tail_base if tail else base + offset
            data = tail + chunk
            if data:
                yield data_base, data
                if overlap:
                    tail = data[-overlap:]
                    tail_base = data_base + max(0, len(data) - len(tail))
                else:
                    tail = b""
                    tail_base = base + offset + current_size
            else:
                tail = b""
                tail_base = base + offset + current_size
            offset += current_size


def _windows_v411_config_key_candidates(blob: bytes, known_salts=()) -> list[tuple[str, str | None]]:
    """Extract redaction-safe key/salt candidates from a Config.Cipher blob."""
    if not blob or len(blob) > WINDOWS_CONFIG_BLOB_MAX:
        return []
    masks = {WINDOWS_CONFIG_XOR_MASK}
    # A 99-byte x'<key64><salt32>' value contains a whole period of the
    # repeating 32-byte mask in its known salt suffix. Derive alternative
    # masks from database salts, then require a full literal AND page HMAC.
    # This avoids assuming the same machine-code mask on AMD64 and ARM64.
    if len(blob) == 99:
        for salt in known_salts:
            if not re.fullmatch(r"[0-9a-f]{32}", salt):
                continue
            mask = bytearray(32)
            for offset, value in enumerate(salt.encode("ascii"), 66):
                mask[offset % 32] = blob[offset] ^ value
            masks.add(bytes(mask))
    out: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    decoded_blobs = [_xor_repeat(blob, mask) for mask in masks]
    for match in (match for decoded in decoded_blobs for match in WINDOWS_CONFIG_LITERAL_RE.finditer(decoded)):
        run = match.group(1).decode("ascii").lower()
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
            starts.append(len(run) - 64)
        for start in dict.fromkeys(starts):
            if start < 0 or start + 64 > len(run):
                continue
            enc_key_hex = run[start:start + 64]
            try:
                enc_key = bytes.fromhex(enc_key_hex)
            except ValueError:
                continue
            if not _probable_32_byte_key(enc_key):
                continue
            embedded_salt = None
            if start + 96 <= len(run):
                embedded_salt = run[start + 64:start + 96]
            item = (enc_key_hex, embedded_salt)
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _verify_windows_direct_key_candidate(
    enc_key_hex: str,
    embedded_salt: str | None,
    db_files: list,
    salt_to_dbs: dict,
    key_map: dict[str, str],
    remaining_salts: set[str],
) -> int:
    if not remaining_salts:
        return 0
    try:
        enc_key = bytes.fromhex(enc_key_hex)
    except ValueError:
        return 0
    if not _probable_32_byte_key(enc_key):
        return 0
    matched = 0
    target_salts = [embedded_salt] if embedded_salt in remaining_salts else list(remaining_salts)
    for salt_hex in target_salts:
        if salt_hex not in remaining_salts:
            continue
        for _rel, _path, _sz, s, page1 in db_files:
            if s == salt_hex and verify_enc_key(enc_key, page1):
                key_map[salt_hex] = enc_key_hex
                remaining_salts.discard(salt_hex)
                matched += 1
                break
    return matched


def _scan_windows_v411_config_cipher(
    pid: int,
    regions: list[tuple[int, int]],
    read_region: callable,
    read_mem: callable,
    db_files: list,
    salt_to_dbs: dict,
    key_map: dict[str, str],
    remaining_salts: set[str],
    print_fn: callable,
) -> dict:
    """Read-only Windows WeChat 4.1.11 Config.Cipher key scan."""
    stats = {
        "needle_occurrences": 0,
        "string_object_refs": 0,
        "node_candidates": 0,
        "config_ptr_candidates": 0,
        "blob99_count": 0,
        "candidate_count": 0,
        "verified_candidates": 0,
        "matched_salts": 0,
    }
    needle_addresses = _find_bytes_in_regions(regions, read_region, WINDOWS_CONFIG_CIPHER_NAME)
    stats["needle_occurrences"] = len(needle_addresses)
    if not needle_addresses:
        return stats

    pair_patterns = [
        struct.pack("<Q", addr) + struct.pack("<Q", len(WINDOWS_CONFIG_CIPHER_NAME))
        for addr in needle_addresses
    ]
    seen_config_ptrs: set[int] = set()
    seen_candidates: set[tuple[str, str | None]] = set()

    for base, data in _iter_windows_region_chunks(regions, read_region, overlap=0x80):
        if not remaining_salts:
            break
        for pattern in pair_patterns:
            pos = data.find(pattern)
            while pos >= 0:
                stats["string_object_refs"] += 1
                qaddr = base + pos
                node_base = qaddr - 0x10
                node = read_mem(node_base, 0x50)
                if not node or len(node) < 0x40:
                    pos = data.find(pattern, pos + 1)
                    continue
                if _u64_from(node, 0x10) not in needle_addresses or _u64_from(node, 0x18) != len(WINDOWS_CONFIG_CIPHER_NAME):
                    pos = data.find(pattern, pos + 1)
                    continue
                config_ptr = _u64_from(node, 0x28)
                if not (0x10000 <= config_ptr < WINDOWS_MAX_USER_ADDRESS):
                    pos = data.find(pattern, pos + 1)
                    continue
                stats["node_candidates"] += 1
                seen_config_ptrs.add(config_ptr)

                obj = read_mem(config_ptr + 0x88, 0x28)
                if not obj or len(obj) < 0x18:
                    pos = data.find(pattern, pos + 1)
                    continue
                data_ptr = _u64_from(obj, 0x8)
                data_len = _u64_from(obj, 0x10)
                if not (0 < data_len <= WINDOWS_CONFIG_BLOB_MAX and 0x10000 <= data_ptr < WINDOWS_MAX_USER_ADDRESS):
                    pos = data.find(pattern, pos + 1)
                    continue
                blob = read_mem(data_ptr, int(data_len))
                if not blob or len(blob) != data_len:
                    pos = data.find(pattern, pos + 1)
                    continue
                if data_len == 99:
                    stats["blob99_count"] += 1
                for enc_key_hex, embedded_salt in _windows_v411_config_key_candidates(blob, remaining_salts):
                    candidate = (enc_key_hex, embedded_salt)
                    if candidate in seen_candidates:
                        continue
                    seen_candidates.add(candidate)
                    stats["candidate_count"] += 1
                    matched = _verify_windows_direct_key_candidate(
                        enc_key_hex,
                        embedded_salt,
                        db_files,
                        salt_to_dbs,
                        key_map,
                        remaining_salts,
                    )
                    if matched:
                        stats["verified_candidates"] += 1
                        stats["matched_salts"] += matched
                pos = data.find(pattern, pos + 1)

    stats["config_ptr_candidates"] = len(seen_config_ptrs)
    if stats["matched_salts"]:
        print_fn(
            "[+] Windows 4.1 runtime Config.Cipher scan matched "
            f"{stats['matched_salts']}/{len(salt_to_dbs)} salts "
            f"(pid={pid}, candidates={stats['candidate_count']})"
        )
    else:
        print_fn(
            "[INFO] Windows 4.1 runtime Config.Cipher scan found no verified key "
            f"(pid={pid}, nodes={stats['node_candidates']}, candidates={stats['candidate_count']})"
        )
    return stats


_V2_IMG_HEX_RE = re.compile(rb"(?<![0-9a-fA-F])([0-9a-f]{16}|[0-9a-f]{32})(?![0-9a-fA-F])")


def _detect_img_magic(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    return None


def _infer_v2_tail_xor(raw: bytes, fmt: str) -> int | None:
    if len(raw) < 15:
        return None
    xor_size = struct.unpack("<I", raw[10:14])[0]
    if xor_size == 0:
        return 0
    if xor_size > len(raw) - 15:
        return None
    tail = raw[len(raw) - xor_size :]
    if fmt == "jpg" and len(tail) >= 2:
        k = tail[-1] ^ 0xD9
        if (tail[-2] ^ k) == 0xFF:
            return k
    if fmt == "png" and len(tail) >= 2:
        k = tail[-1] ^ 0x82
        if (tail[-2] ^ k) == 0x60:
            return k
    if fmt == "gif" and len(tail) >= 1:
        return tail[-1] ^ 0x3B
    return None


def verify_v2_image_aes_key(raw: bytes, aes_key: bytes, *, aes_factory=None) -> tuple[bool, str | None, int | None]:
    """Cryptographically verify a 16-byte AES-128-ECB image key against a V1/V2 .dat header block."""
    if len(aes_key) != 16 or len(raw) < 31 or not raw.startswith((b"\x07\x08V2\x08\x07", b"\x07\x08V1\x08\x07")):
        return False, None, None
    aes_size = struct.unpack("<I", raw[6:10])[0]
    xor_size = struct.unpack("<I", raw[10:14])[0]
    aes_end = 15 + aes_size + (16 - aes_size % 16)
    raw_end = len(raw) - xor_size
    if aes_end > raw_end or aes_end <= 15:
        return False, None, None
    # Quick first-block filter: image magic lives in the first 16 decrypted bytes.
    first_block = raw[15:31]
    from windows_crypto import CngAES
    cipher = aes_factory(aes_key) if aes_factory is not None else CngAES(aes_key, chaining_mode="ChainingModeECB")
    try:
        plain0 = cipher.decrypt(None, first_block)
        fmt = _detect_img_magic(plain0)
        if not fmt:
            return False, None, None
        full_plain = plain0 if aes_end == 31 else cipher.decrypt(None, raw[15:aes_end])
        pad = full_plain[-1]
        if not 1 <= pad <= 16 or full_plain[-pad:] != bytes([pad]) * pad:
            return False, None, None
        return True, fmt, _infer_v2_tail_xor(raw, fmt)
    except Exception:
        return False, None, None
    finally:
        if hasattr(cipher, "close"):
            cipher.close()


def scan_v2_image_key_in_regions(
    regions: list[tuple[int, int]],
    read_region: callable,
    sample_dat: bytes,
    *,
    aes_factory=None,
    deadline: float | None = None,
) -> dict | None:
    """Read-only scan of process regions for a verified 16-byte ASCII V1/V2 image AES key (RAM-only)."""
    import time
    if len(sample_dat) < 31 or not sample_dat.startswith((b"\x07\x08V2\x08\x07", b"\x07\x08V1\x08\x07")):
        return None
    seen: set[bytes] = set()
    for _base, chunk in _iter_windows_region_chunks(regions, read_region, overlap=64):
        if deadline is not None and time.monotonic() >= deadline:
            break
        for match in _V2_IMG_HEX_RE.finditer(chunk):
            cand = match.group(1)[:16]
            if cand in seen or len(set(cand)) < 6:
                continue
            seen.add(cand)
            ok, _fmt, xor_key = verify_v2_image_aes_key(sample_dat, cand, aes_factory=aes_factory)
            if ok:
                return {"aesKey": cand, "xorKey": xor_key, "source": "memory"}
    return None

