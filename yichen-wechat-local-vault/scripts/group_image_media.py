"""Local Mac WeChat chat-image attachment lookup, preview decoding, and OCR.

Private and group chats share one layout: msg/attach/<md5(chat username)>/<YYYY-MM>/Img/
<hash>[_t|_h].dat, where <hash> comes from the message row's packed_info_data (see
extract_image_md5), not from the md5 attribute of the message XML.

This module reads already authorized local files. It does not open WeChat, read
message tables, contact a network service, or depend on a sidecar application.
The caller is responsible for verifying the account binding and filtering the
message scope before calling these helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time


def image_key_candidates(source_config: Path, db_base: Path) -> list[dict]:
    """Derive local image-key candidates from this account's kvcomm filenames."""
    config = json.loads(source_config.read_text())
    raw_name = str(config.get("wxid") or db_base.parent.name).strip()
    names = [raw_name]
    if raw_name.startswith("wxid_") and raw_name.count("_") > 1:
        names.insert(0, "_".join(raw_name.split("_", 2)[:2]))
    names = list(dict.fromkeys(name for name in names if name))

    parts = db_base.parts
    directories: list[Path] = []
    if "xwechat_files" in parts:
        index = parts.index("xwechat_files")
        documents = Path(*parts[:index])
        directories.extend((documents / "app_data/net/kvcomm", documents / "xwechat/net/kvcomm"))
        if index > 1:
            container = Path(*parts[: index - 1])
            directories.extend((
                container / "Library/Application Support/com.tencent.xinWeChat/xwechat/net/kvcomm",
                container / "Library/Application Support/com.tencent.xinWeChat/net/kvcomm",
            ))
    directories.append(Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/net/kvcomm")

    codes: set[int] = set()
    for directory in directories:
        try:
            if not directory.is_dir():
                continue
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            match = re.fullmatch(r"key_(\d+)(?:_.*)?", entry.name)
            if match:
                codes.add(int(match.group(1)))
    return [
        {"aesKey": hashlib.md5(f"{code}{name}".encode()).hexdigest()[:16].encode(),
         "xorKey": code & 255}
        for code in sorted(codes) for name in names
    ]


def extract_image_md5(data: bytes) -> str | None:
    """Attachment file hash from an image message's packed_info_data bytes."""
    match = re.search(rb"(?i)(?:^|[^0-9a-f])([0-9a-f]{32})(?:$|[^0-9a-f])", data)
    return match.group(1).decode("ascii").lower() if match else None


def dat_file_priority(path: Path) -> tuple[bool, str]:
    name = path.name.lower()
    return ("thumb" in name or "_t" in name, str(path))


class AttachmentFinder:
    """Index only the hash directory of each authorized chat (private or group), once per chat."""

    def __init__(self, root: Path, *, max_seconds_per_chat: float = 15, max_files_per_chat: int = 300_000):
        self.root = root
        self.max_seconds_per_chat = max_seconds_per_chat
        self.max_files_per_chat = max_files_per_chat
        self._indexes: dict[str, dict[str, list[Path]]] = {}
        self.gaps: list[dict[str, str]] = []
        self._failed: set[str] = set()

    @property
    def indexed_chats(self) -> int:
        return len(self._indexes)

    def scan_failed(self, chat: str) -> bool:
        return hashlib.md5(chat.encode()).hexdigest() in self._failed

    def find(self, chat: str, md5: str) -> list[Path]:
        if not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
            return []
        chat_hash = hashlib.md5(chat.encode()).hexdigest()
        if chat_hash not in self._indexes:
            self._indexes[chat_hash] = self._index_chat(chat_hash)
        return sorted(self._indexes[chat_hash].get(md5.lower(), []), key=dat_file_priority)

    def _index_chat(self, chat_hash: str) -> dict[str, list[Path]]:
        folder = self.root / chat_hash
        index: dict[str, list[Path]] = {}
        if folder.is_symlink():
            self._record_gap(chat_hash, "symlink-chat-directory")
            return index
        if not folder.is_dir():
            return index
        started = time.monotonic()
        seen = 0

        def onerror(error: OSError) -> None:
            self._record_gap(chat_hash, type(error).__name__)

        try:
            months = sorted(folder.iterdir(), key=lambda p: (p.name != time.strftime("%Y-%m"), p.name))
            for month in months:
                if month.is_symlink() or not month.is_dir():
                    continue
                for current, dirs, files in os.walk(month, followlinks=False, onerror=onerror):
                    dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
                    for name in files:
                        seen += 1
                        if seen > self.max_files_per_chat or time.monotonic() - started > self.max_seconds_per_chat:
                            self._record_gap(chat_hash, "scan-budget-exceeded")
                            return index
                        match = re.match(r"(?i)^([0-9a-f]{32})(?:[_\.]|$)", name)
                        if match and name.lower().endswith(".dat"):
                            path = Path(current) / name
                            if not path.is_symlink():
                                index.setdefault(match.group(1).lower(), []).append(path)
        except OSError as error:
            self._record_gap(chat_hash, type(error).__name__)
        return index

    def _record_gap(self, chat_hash: str, reason: str) -> None:
        self._failed.add(chat_hash)
        self.gaps.append({"chat_hash": chat_hash, "reason": reason})


def _decode_image_bytes(data: bytes, *, aes_key: bytes, xor_key: int) -> bytes:
    if len(data) < 15 or not data.startswith((b"\x07\x08V2\x08\x07", b"\x07\x08V1\x08\x07")):
        raise ValueError("unsupported image dat")
    aes_size = struct.unpack("<I", data[6:10])[0]
    xor_size = struct.unpack("<I", data[10:14])[0]
    aes_end = 15 + aes_size + (16 - aes_size % 16)
    raw_end = len(data) - xor_size
    if aes_end > raw_end:
        raise ValueError("invalid image layout")
    from Crypto.Cipher import AES

    clear = AES.new(aes_key, AES.MODE_ECB).decrypt(data[15:aes_end])
    pad = clear[-1]
    if not 1 <= pad <= 16 or clear[-pad:] != bytes([pad]) * pad:
        raise ValueError("invalid image key")
    return clear[:-pad] + data[aes_end:raw_end] + bytes(value ^ xor_key for value in data[raw_end:])


def _image_format(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"wxgf"):
        return "wxgf"
    raise ValueError("unknown image format")


def decode_image_dat_to_preview(path: Path, key: dict, context: dict, cache_dir: Path) -> dict:
    clear = _decode_image_bytes(path.read_bytes(), aes_key=bytes(key["aesKey"]), xor_key=int(key["xorKey"]))
    image_format = _image_format(clear)
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = hashlib.sha256(
        (str(context.get("chatKey")) + "|" + str(context.get("messageLocalId")) + "|" + path.name).encode()
    ).hexdigest()[:20]
    target = cache_dir / f"{stem}.{image_format}"
    target.write_bytes(clear)
    target.chmod(0o600)
    if image_format == "wxgf":
        output = cache_dir / f"{stem}.jpg"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "hevc", "-i", str(target),
             "-frames:v", "1", "-update", "1", str(output)],
            check=True, timeout=20,
        )
        output.chmod(0o600)
        target = output
    asset = "thumbnail" if path.name.endswith("_t.dat") else (
        "high-resolution" if path.name.endswith("_h.dat") else "original"
    )
    return {"previewPath": str(target), "assetLevel": asset}


def _normalize_ocr_text(value: str) -> str:
    return "\n".join(part.strip() for part in value.splitlines() if part.strip())


def ocr_with_macos_vision(path: Path) -> dict:
    try:
        from Foundation import NSURL
        from Vision import VNImageRequestHandler, VNRecognizeTextRequest

        request = VNRecognizeTextRequest.alloc().init()
        # 0 = VNRequestTextRecognitionLevelAccurate. The fast level (1) only reads
        # Latin scripts and turns Chinese screenshots into garbage.
        request.setRecognitionLevel_(0)
        request.setUsesLanguageCorrection_(True)
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        handler = VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
        succeeded, error = handler.performRequests_error_([request], None)
        if not succeeded:
            return {"engine": "Vision", "text": "", "error": str(error)}
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return {"engine": "Vision", "text": _normalize_ocr_text("\n".join(lines))}
    except Exception as error:
        return {"engine": "Vision", "text": "", "error": type(error).__name__}


def ocr_with_tesseract(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "chi_sim+eng", "--psm", "11"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return {"engine": "Tesseract",
                "text": _normalize_ocr_text(result.stdout) if result.returncode == 0 else "",
                "error": "" if result.returncode == 0 else f"exit-{result.returncode}"}
    except Exception as error:
        return {"engine": "Tesseract", "text": "", "error": type(error).__name__}


def ocr_image_with_local_engine(path: Path) -> dict:
    result = ocr_with_macos_vision(path)
    return result if result.get("text") else ocr_with_tesseract(path)
