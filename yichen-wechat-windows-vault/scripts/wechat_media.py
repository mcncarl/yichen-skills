from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import wave

from Crypto.Cipher import AES

from vault_cli import (
    connect,
    find_chat_tables,
    load_contacts,
    message_columns,
    resolve_chat,
    resolve_db_dir,
    resolve_decrypted_dir,
    table_columns,
)
from vault_common import APP_DIR


MEDIA_ROOT = APP_DIR / "vault" / "media"
V2_MAGIC = b"\x07\x08V2\x08\x07"
V1_MAGIC = b"\x07\x08V1\x08\x07"
HEADER_SIZE = 15
_IMAGE_KEY_CACHE: tuple[tuple[int, ...], bytes] | None = None


def _message_record(chat_query: str, local_id: int, db_name: str = "") -> tuple[dict, dict]:
    decrypted_dir = resolve_decrypted_dir(None)
    contacts, _ = load_contacts(decrypted_dir)
    chat = resolve_chat(chat_query, contacts)
    if not chat:
        raise RuntimeError("chat not found")
    if db_name and not re.fullmatch(r"message_\d+\.db", db_name):
        raise ValueError("db must look like message_N.db")

    matches: list[dict] = []
    for db_path, table in find_chat_tables(decrypted_dir, chat):
        if db_name and db_path.name != db_name:
            continue
        with connect(db_path) as con:
            cols = message_columns(con, table)
            all_cols = table_columns(con, table)
            packed = "packed_info_data" if "packed_info_data" in all_cols else "NULL"
            sql = (
                "SELECT "
                f"{cols.get('local_id', 'rowid')} AS local_id, "
                f"{cols.get('server_id', 'NULL')} AS server_id, "
                f"{cols.get('local_type', 'NULL')} AS local_type, "
                f"{cols.get('create_time', 'NULL')} AS create_time, "
                f"{cols.get('message_content', 'NULL')} AS message_content, "
                f"{cols.get('compress_content', 'NULL')} AS compress_content, "
                f"{cols.get('compression_flag', 'NULL')} AS compression_flag, "
                f"{packed} AS packed_info_data "
                f"FROM [{table}] WHERE {cols.get('local_id', 'rowid')} = ?"
            )
            for row in con.execute(sql, (local_id,)):
                item = dict(row)
                item["db"] = db_path.name
                matches.append(item)
    if not matches:
        raise RuntimeError("message not found")
    matches.sort(key=lambda item: int(item.get("create_time") or 0), reverse=True)
    return chat, matches[0]


def _resource_md5(chat_username: str, row: dict) -> str:
    packed = bytes(row.get("packed_info_data") or b"")
    match = re.search(rb"[0-9a-fA-F]{32}", packed)
    if match:
        return match.group().decode("ascii").lower()

    resource_db = resolve_decrypted_dir(None) / "message" / "message_resource.db"
    with connect(resource_db) as con:
        chat_row = con.execute(
            "SELECT rowid FROM ChatName2Id WHERE user_name = ?", (chat_username,)
        ).fetchone()
        if not chat_row:
            raise RuntimeError("chat is missing from message_resource.db")
        packed_row = con.execute(
            "SELECT packed_info FROM MessageResourceInfo "
            "WHERE chat_id = ? AND message_local_id = ? "
            "AND (message_local_type = 3 OR message_local_type % 4294967296 = 3) "
            "AND message_create_time = ? ORDER BY rowid DESC LIMIT 1",
            (chat_row[0], row["local_id"], row["create_time"]),
        ).fetchone()
        if not packed_row:
            raise RuntimeError("image is missing from message_resource.db")
        match = re.search(rb"[0-9a-fA-F]{32}", bytes(packed_row[0] or b""))
        if not match:
            raise RuntimeError("image resource id is missing")
        return match.group().decode("ascii").lower()


def _find_image_dat(chat_username: str, resource_md5: str) -> Path:
    attach_root = resolve_db_dir().parent / "msg" / "attach"
    chat_hash = hashlib.md5(chat_username.encode()).hexdigest()
    chat_dir = attach_root / chat_hash
    if not chat_dir.is_dir():
        raise RuntimeError("chat attachment directory is missing")
    candidates: list[Path] = []
    for suffix in (".dat", "_h.dat", "_t.dat"):
        candidates.extend(chat_dir.glob(f"*/Img/{resource_md5}{suffix}"))
    if not candidates:
        raise RuntimeError("image file is not cached locally; open it in WeChat and retry")
    def rank(path: Path) -> int:
        if path.name == f"{resource_md5}.dat":
            return 0
        if path.name == f"{resource_md5}_h.dat":
            return 1
        return 2

    return sorted(candidates, key=rank)[0]


def _detect_image_format(data: bytes) -> str:
    if data.startswith(b"wxgf"):
        return "hevc"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"GIF"):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"II*\x00"):
        return "tif"
    if data.startswith(b"BM"):
        return "bmp"
    return "bin"


def _v2_templates(attach_root: Path, limit: int = 3) -> list[bytes]:
    templates: list[bytes] = []
    for path in attach_root.rglob("*_t.dat"):
        try:
            with path.open("rb") as handle:
                head = handle.read(HEADER_SIZE + 16)
        except OSError:
            continue
        block = head[HEADER_SIZE : HEADER_SIZE + 16]
        if head.startswith(V2_MAGIC) and len(block) == 16 and block not in templates:
            templates.append(block)
            if len(templates) >= limit:
                break
    return templates


def _verify_image_key(key: bytes, templates: list[bytes]) -> bool:
    if len(key) != 16 or not templates:
        return False
    cipher = AES.new(key, AES.MODE_ECB)
    return all(_detect_image_format(cipher.decrypt(block)) != "bin" for block in templates)


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _weixin_pids() -> list[int]:
    result = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids = []
    for row in csv.reader(result.splitlines()):
        if len(row) >= 2 and row[0].lower() == "weixin.exe":
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return sorted(set(pids))


def _scan_image_key(attach_root: Path) -> bytes:
    global _IMAGE_KEY_CACHE
    pids = tuple(_weixin_pids())
    if not pids:
        raise RuntimeError("WeChat is not running")
    if _IMAGE_KEY_CACHE and _IMAGE_KEY_CACHE[0] == pids:
        return _IMAGE_KEY_CACHE[1]
    templates = _v2_templates(attach_root)
    if not templates:
        raise RuntimeError("no V2 image templates found")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    allowed_pages = {0x04, 0x08, 0x40, 0x80}
    candidate_pattern = re.compile(rb"(?<![A-Za-z0-9])([A-Za-z0-9]{32}|[A-Za-z0-9]{16})(?![A-Za-z0-9])")

    for pid in pids:
        process = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not process:
            continue
        try:
            address = 0
            seen: set[bytes] = set()
            while True:
                mbi = _MemoryBasicInformation()
                if not kernel32.VirtualQueryEx(
                    process, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
                ):
                    break
                base = int(mbi.BaseAddress or 0)
                size = int(mbi.RegionSize)
                protection = int(mbi.Protect) & ~(0x100 | 0x200 | 0x400)
                if mbi.State == 0x1000 and protection in allowed_pages and size <= 50 * 1024 * 1024:
                    offset = 0
                    while offset < size:
                        count = min(2 * 1024 * 1024, size - offset)
                        buffer = ctypes.create_string_buffer(count)
                        read = ctypes.c_size_t()
                        ok = kernel32.ReadProcessMemory(
                            process,
                            ctypes.c_void_p(base + offset),
                            buffer,
                            count,
                            ctypes.byref(read),
                        )
                        if ok and read.value:
                            for match in candidate_pattern.finditer(buffer.raw[: read.value]):
                                key = match.group(1)[:16]
                                if key not in seen:
                                    seen.add(key)
                                    if _verify_image_key(key, templates):
                                        _IMAGE_KEY_CACHE = (pids, key)
                                        return key
                        offset += count - 31 if count > 31 else count
                next_address = base + size
                if next_address <= address:
                    break
                address = next_address
        finally:
            kernel32.CloseHandle(process)
    raise RuntimeError("verified Windows WeChat V2 image key not found")


def _derive_xor_key(attach_root: Path) -> int:
    votes: list[int] = []
    for path in attach_root.rglob("*.dat"):
        try:
            with path.open("rb") as handle:
                head = handle.read(6)
                handle.seek(-1, os.SEEK_END)
                last = handle.read(1)
        except OSError:
            continue
        if head == V2_MAGIC and last:
            votes.append(last[0] ^ 0xD9)
            if len(votes) >= 10:
                break
    if len(votes) < 3:
        return 0x88
    return max(set(votes), key=votes.count)


def _decode_image(dat_path: Path) -> tuple[bytes, str, str]:
    data = dat_path.read_bytes()
    if data.startswith(V2_MAGIC) or data.startswith(V1_MAGIC):
        aes_size, xor_size = struct.unpack("<II", data[6:14])
        aligned = aes_size + (16 - aes_size % 16)
        aes_end = HEADER_SIZE + aligned
        raw_end = len(data) - xor_size
        if aes_end > raw_end or raw_end < HEADER_SIZE:
            raise RuntimeError("invalid WeChat V2 image lengths")
        if data.startswith(V1_MAGIC):
            key = b"cfcd208495d565ef"
            decoder = "v1_aes"
        else:
            attach_root = resolve_db_dir().parent / "msg" / "attach"
            key = _scan_image_key(attach_root)
            decoder = "v2"
        decrypted = AES.new(key, AES.MODE_ECB).decrypt(data[HEADER_SIZE:aes_end])
        pad = decrypted[-1]
        if not 1 <= pad <= 16 or decrypted[-pad:] != bytes([pad]) * pad:
            raise RuntimeError("invalid WeChat image AES padding")
        decrypted = decrypted[:-pad]
        xor_key = _derive_xor_key(resolve_db_dir().parent / "msg" / "attach")
        output = decrypted + data[aes_end:raw_end] + bytes(value ^ xor_key for value in data[raw_end:])
    else:
        output = data
        for signature in (b"\xff\xd8\xff", b"\x89PNG", b"GIF"):
            key = data[0] ^ signature[0]
            candidate = bytes(value ^ key for value in data)
            if candidate.startswith(signature):
                output = candidate
                break
        decoder = "legacy_xor"
    image_format = _detect_image_format(output)
    if image_format == "bin":
        raise RuntimeError("decoded image format is not recognized")
    return output, image_format, decoder


def _decode_hevc_to_jpeg(data: bytes) -> bytes:
    import av

    stream_start = None
    for match in re.finditer(rb"\x00\x00\x00\x01|\x00\x00\x01", data):
        if match.end() < len(data) and ((data[match.end()] >> 1) & 0x3F) == 32:
            stream_start = match.start()
            break
    if stream_start is None:
        raise RuntimeError("WeChat HEVC VPS frame is missing")
    with av.open(io.BytesIO(data[stream_start:]), format="hevc", mode="r") as container:
        frame = next(container.decode(video=0), None)
    if frame is None:
        raise RuntimeError("WeChat HEVC image produced no frame")
    codec = av.CodecContext.create("mjpeg", "w")
    codec.width = frame.width
    codec.height = frame.height
    codec.pix_fmt = "yuvj420p"
    image = b"".join(
        bytes(packet) for packet in [*codec.encode(frame), *codec.encode()]
    )
    if not image.startswith(b"\xff\xd8\xff"):
        raise RuntimeError("WeChat HEVC JPEG conversion failed")
    return image


def _private_output_dir(chat_username: str, row: dict) -> Path:
    chat_hash = hashlib.sha256(chat_username.encode()).hexdigest()[:16]
    path = MEDIA_ROOT / chat_hash / f"{Path(row['db']).stem}-{int(row['local_id'])}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_atomic(path: Path, data: bytes) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def extract_image(chat_query: str, local_id: int, db_name: str = "") -> dict:
    chat, row = _message_record(chat_query, local_id, db_name)
    if int(row.get("local_type") or 0) & 0xFFFFFFFF != 3:
        raise RuntimeError("message is not an image")
    output_dir = _private_output_dir(chat["username"], row)
    full_cached = output_dir / "image-full.jpg"
    if full_cached.is_file():
        return {
            "kind": "image",
            "chat": chat["display_name"],
            "db": row["db"],
            "local_id": row["local_id"],
            "time": row["create_time"],
            "path": str(full_cached),
            "format": "jpg",
            "source_format": "hevc",
            "decoder": "cached_hevc",
        }
    for image_format in ("jpg", "png", "gif", "webp", "tif", "bmp", "hevc"):
        cached = output_dir / f"image.{image_format}"
        if cached.is_file():
            return {
                "kind": "image",
                "chat": chat["display_name"],
                "db": row["db"],
                "local_id": row["local_id"],
                "time": row["create_time"],
                "path": str(cached),
                "format": image_format,
                "source_format": image_format,
                "decoder": "cached",
            }
    resource_md5 = _resource_md5(chat["username"], row)
    dat_path = _find_image_dat(chat["username"], resource_md5)
    image, image_format, decoder = _decode_image(dat_path)
    source_format = image_format
    if image_format == "hevc":
        try:
            image = _decode_hevc_to_jpeg(image)
            image_format = "jpg"
            decoder = f"{decoder}+pyav_hevc"
        except Exception:
            preview = dat_path.parent / f"{resource_md5}_t.dat"
            if preview.is_file() and preview != dat_path:
                preview_image, preview_format, preview_decoder = _decode_image(preview)
                if preview_format != "hevc":
                    image, image_format, decoder = preview_image, preview_format, preview_decoder
    output_name = "image-full.jpg" if source_format == "hevc" and image_format == "jpg" else f"image.{image_format}"
    output_path = output_dir / output_name
    _write_atomic(output_path, image)
    return {
        "kind": "image",
        "chat": chat["display_name"],
        "db": row["db"],
        "local_id": row["local_id"],
        "time": row["create_time"],
        "path": str(output_path),
        "format": image_format,
        "source_format": source_format,
        "decoder": decoder,
    }


def _find_voice_data(row: dict) -> bytes:
    decrypted_dir = resolve_decrypted_dir(None)
    for media_db in sorted((decrypted_dir / "message").glob("media_*.db")):
        with connect(media_db) as con:
            if "VoiceInfo" not in {
                item[0] for item in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }:
                continue
            voice = con.execute(
                "SELECT voice_data FROM VoiceInfo WHERE svr_id = ? "
                "AND local_id = ? AND create_time = ? LIMIT 1",
                (row.get("server_id"), row.get("local_id"), row.get("create_time")),
            ).fetchone()
            if voice and voice[0]:
                return bytes(voice[0])
    raise RuntimeError("voice data is not available in media databases")


def _find_node() -> str:
    candidates = [
        shutil.which("node"),
        os.environ.get("WECHAT_VAULT_NODE"),
        str(APP_DIR / "node-runtime" / "node.exe"),
        str(Path(os.environ.get("HERMES_HOME", "")) / "node" / "node.exe"),
        str(
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        ),
    ]
    runtime_root = Path.home() / ".cache" / "codex-runtimes"
    if runtime_root.is_dir():
        candidates.extend(
            str(path)
            for path in sorted(
                runtime_root.glob("*/dependencies/node/bin/node.exe"),
                reverse=True,
            )
        )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Node.js runtime is missing")


def _decode_voice_to_wav(voice_data: bytes, output_dir: Path) -> tuple[Path, int]:
    silk_path = output_dir / "voice.silk"
    pcm_path = output_dir / "voice.pcm"
    wav_path = output_dir / "voice.wav"
    _write_atomic(silk_path, voice_data)
    decoder = Path(__file__).with_name("decode_silk.cjs")
    result = subprocess.run(
        [_find_node(), str(decoder), str(silk_path), str(pcm_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SILK decode failed: {(result.stderr or result.stdout)[-1000:]}")
    metadata = json.loads(result.stdout or "{}")
    pcm = pcm_path.read_bytes()
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm)
    pcm_path.unlink(missing_ok=True)
    return wav_path, int(metadata.get("duration_ms") or 0)


def extract_voice(chat_query: str, local_id: int, db_name: str = "") -> dict:
    chat, row = _message_record(chat_query, local_id, db_name)
    if int(row.get("local_type") or 0) & 0xFFFFFFFF != 34:
        raise RuntimeError("message is not a voice message")
    output_dir = _private_output_dir(chat["username"], row)
    wav_path, duration_ms = _decode_voice_to_wav(_find_voice_data(row), output_dir)
    return {
        "kind": "voice",
        "chat": chat["display_name"],
        "db": row["db"],
        "local_id": row["local_id"],
        "time": row["create_time"],
        "path": str(wav_path),
        "duration_ms": duration_ms,
    }


def extract_media(chat_query: str, local_id: int, db_name: str = "") -> dict:
    _, row = _message_record(chat_query, local_id, db_name)
    media_type = int(row.get("local_type") or 0) & 0xFFFFFFFF
    if media_type == 3:
        return extract_image(chat_query, local_id, db_name)
    if media_type == 34:
        return extract_voice(chat_query, local_id, db_name)
    raise RuntimeError("message is not a supported image or voice message")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract one WeChat image or voice message.")
    parser.add_argument("chat")
    parser.add_argument("local_id", type=int)
    parser.add_argument("--db", default="")
    args = parser.parse_args(argv)
    print(json.dumps(extract_media(args.chat, args.local_id, args.db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
