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

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
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


def _safe_kvcomm_dirs(attach_dir: Path | None = None, extra_kvcomm_dirs: tuple[Path, ...] = ()) -> list[Path]:
    """Return bounded, non-symlink kvcomm directories on Windows or macOS."""
    candidates: list[Path] = [Path(d) for d in extra_kvcomm_dirs if d]
    if sys.platform == "win32":
        for env_name in ("APPDATA", "LOCALAPPDATA"):
            base_val = os.environ.get(env_name, "").strip()
            if not base_val:
                continue
            xw = Path(base_val) / "Tencent" / "xwechat"
            try:
                if xw.is_symlink() or not xw.is_dir():
                    continue
                for child in sorted(xw.iterdir()):
                    if child.is_symlink() or not child.is_dir():
                        continue
                    kv = child / "kvcomm"
                    if not kv.is_symlink() and kv.is_dir():
                        candidates.append(kv)
                radium_ilink = xw / "radium" / "ilink"
                if not radium_ilink.is_symlink() and radium_ilink.is_dir():
                    for child in sorted(radium_ilink.iterdir()):
                        if child.is_symlink() or not child.is_dir():
                            continue
                        kv = child / "kvcomm"
                        if not kv.is_symlink() and kv.is_dir():
                            candidates.append(kv)
            except OSError:
                continue
    elif sys.platform == "darwin":
        if attach_dir is not None:
            parts = attach_dir.parts
            if "xwechat_files" in parts:
                index = parts.index("xwechat_files")
                documents = Path(*parts[:index])
                candidates.extend((documents / "app_data/net/kvcomm", documents / "xwechat/net/kvcomm"))
                if index > 1:
                    container = Path(*parts[: index - 1])
                    candidates.extend((
                        container / "Library/Application Support/com.tencent.xinWeChat/xwechat/net/kvcomm",
                        container / "Library/Application Support/com.tencent.xinWeChat/net/kvcomm",
                    ))
        candidates.append(Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/net/kvcomm")

    seen: set[str] = set()
    unique: list[Path] = []
    for directory in candidates:
        try:
            if directory.is_symlink() or not directory.is_dir():
                continue
            key = os.path.normcase(str(directory.resolve()))
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique


def kvcomm_image_key_candidates(
    account_hint: str = "",
    *,
    attach_dir: Path | None = None,
    extra_kvcomm_dirs: tuple[Path, ...] = (),
) -> list[dict]:
    """Derive WeChat 4.x V2 image AES/XOR key candidates from local kvcomm key_<code_int>_* filenames."""
    raw_names: list[str] = []
    if account_hint.strip():
        raw_names.append(account_hint.strip())
    if attach_dir is not None:
        # Standard WeChat 4.x layout: <account_dir>/msg/attach
        try:
            if attach_dir.name.casefold() == "attach" and attach_dir.parent.name.casefold() == "msg":
                acct_name = attach_dir.parent.parent.name.strip()
                if acct_name:
                    raw_names.append(acct_name)
        except OSError:
            pass

    names: list[str] = []
    for raw_name in raw_names:
        # WeChat 4.x account folders append a 4-hex suffix: <account>_<4hex> (for both wxid_* and custom IDs).
        stripped = re.sub(r"_[0-9a-fA-F]{4}$", "", raw_name)
        if stripped and stripped != raw_name and stripped not in names:
            names.append(stripped)
        if raw_name.startswith("wxid_") and raw_name.count("_") > 1:
            base_wxid = "_".join(raw_name.split("_", 2)[:2])
            if base_wxid and base_wxid not in names:
                names.append(base_wxid)
        if raw_name and raw_name not in names:
            names.append(raw_name)
    if not names:
        return []

    codes: set[int] = set()
    for directory in _safe_kvcomm_dirs(attach_dir=attach_dir, extra_kvcomm_dirs=extra_kvcomm_dirs):
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            match = re.fullmatch(r"key_(\d+)(?:_.*)?", entry.name)
            if match:
                codes.add(int(match.group(1)))

    # Try non-zero account codes before key_0 (which is usually a generic pre-login counter).
    ordered_codes = sorted(codes, key=lambda c: (c == 0, c))
    results: list[dict] = []
    seen_keys: set[tuple[bytes, int]] = set()
    for code in ordered_codes:
        xor_key = code & 255
        for name in names:
            aes_key = hashlib.md5(f"{code}{name}".encode("utf-8")).hexdigest()[:16].encode("ascii")
            pair = (aes_key, xor_key)
            if pair not in seen_keys:
                seen_keys.add(pair)
                results.append({"aesKey": aes_key, "xorKey": xor_key, "source": "kvcomm"})
    return results


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


_WINDOWS_WINRT_OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

$ImgPath = [System.Environment]::GetEnvironmentVariable('WECHAT_OCR_IMAGE_PATH')
if (-not $ImgPath -or -not (Test-Path -LiteralPath $ImgPath)) {
    @{ ok = $false; error = 'file_not_found'; languages = @() } | ConvertTo-Json -Compress
    exit 0
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await-WinRT($op, $resultType) {
    $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait()
    return $task.Result
}

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$avail = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
$availTags = @($avail | ForEach-Object { $_.LanguageTag })
$chosen = $null
foreach ($pref in @('zh-Hans-CN', 'zh-CN', 'zh-Hans', 'zh-Hant-TW', 'zh-Hant-HK')) {
    $m = $avail | Where-Object { $_.LanguageTag -ieq $pref } | Select-Object -First 1
    if ($m) { $chosen = $m; break }
}
if ($chosen) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($chosen)
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if (-not $engine -and $avail.Count -gt 0) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($avail[0])
}
if (-not $engine) {
    @{ ok = $false; error = 'no_ocr_language'; available_languages = $availTags } | ConvertTo-Json -Compress
    exit 0
}

$file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImgPath)) ([Windows.Storage.StorageFile])
$stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softBmp = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocrResult = Await-WinRT ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @($ocrResult.Lines | ForEach-Object { $_.Text })
    @{
        ok = $true
        language = $engine.RecognizerLanguage.LanguageTag
        available_languages = $availTags
        text = ($lines -join "`n")
    } | ConvertTo-Json -Compress
} finally {
    $stream.Dispose()
}
"""


def ocr_with_windows_winrt(path: Path) -> dict:
    """Recognize image text via Windows 10/11 built-in Windows.Media.Ocr (zero third-party deps)."""
    if sys.platform != "win32":
        return {"engine": "WinRT", "text": "", "error": "windows_only"}
    try:
        encoded = base64.b64encode(_WINDOWS_WINRT_OCR_SCRIPT.encode("utf-16le")).decode("ascii")
        env = os.environ.copy()
        env["WECHAT_OCR_IMAGE_PATH"] = str(path.resolve())
        kwargs: dict = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=30,
            check=False,
            **kwargs,
        )
        raw = (proc.stdout or "").strip()
        if proc.returncode != 0 or not raw:
            return {"engine": "WinRT", "text": "", "error": f"exit-{proc.returncode}"}
        payload = json.loads(raw.splitlines()[-1])
        langs = payload.get("available_languages") or []
        if not payload.get("ok"):
            return {
                "engine": "WinRT",
                "text": "",
                "error": str(payload.get("error") or "winrt_failed"),
                "available_languages": langs,
            }
        lang = str(payload.get("language") or "")
        out: dict = {
            "engine": "WinRT",
            "language": lang,
            "available_languages": langs,
            "text": _normalize_ocr_text(str(payload.get("text") or "")),
        }
        if not any(tag.lower().startswith("zh") for tag in langs):
            out["note"] = "系统未安装中文 OCR 语言包（当前仅 " + (", ".join(langs) or "无") + "），识别中文建议安装 Windows 简体中文语言包或 Tesseract"
        return out
    except Exception as error:
        return {"engine": "WinRT", "text": "", "error": type(error).__name__}


def ocr_with_tesseract(path: Path) -> dict:
    try:
        kwargs: dict = {}
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "chi_sim+eng", "--psm", "11"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            **kwargs,
        )
        return {"engine": "Tesseract",
                "text": _normalize_ocr_text(result.stdout) if result.returncode == 0 else "",
                "error": "" if result.returncode == 0 else f"exit-{result.returncode}"}
    except Exception as error:
        return {"engine": "Tesseract", "text": "", "error": type(error).__name__}


def ocr_image_with_local_engine(path: Path) -> dict:
    if sys.platform == "darwin":
        result = ocr_with_macos_vision(path)
        return result if result.get("text") else ocr_with_tesseract(path)
    if sys.platform == "win32":
        result = ocr_with_windows_winrt(path)
        if result.get("text"):
            return result
        tess = ocr_with_tesseract(path)
        return tess if tess.get("text") else result
    return ocr_with_tesseract(path)
