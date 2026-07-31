#!/usr/bin/env python3
"""抖音人类可读产物、1080p 校验与中文口播稿转写。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

STATE_ROOT = Path.home() / ".local" / "share" / "yichen-douyin-fetcher"
VIDEO_FILENAME = "视频.mp4"
TRANSCRIPT_FILENAME = "中文口播稿.txt"


def truncate_utf8(value: str, max_bytes: int = 150) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def readable_title(value: str) -> str:
    translation = str.maketrans(
        {
            "/": "／",
            "\\": "／",
            ":": "：",
            "*": "＊",
            "?": "？",
            '"': "”",
            "<": "＜",
            ">": "＞",
            "|": "｜",
        }
    )
    cleaned = unicodedata.normalize("NFC", value or "").translate(translation)
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return truncate_utf8(cleaned) or "未命名视频"


def published_date(item: dict) -> str:
    raw_timestamp = item.get("create_time")
    if raw_timestamp in (None, ""):
        return "未知日期"
    try:
        timestamp = int(raw_timestamp)
        if timestamp <= 0:
            return "未知日期"
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return "未知日期"


def readable_video_folder(item: dict) -> str:
    aweme_id = str(item.get("aweme_id") or "unknown")
    title = readable_title(str(item.get("desc") or ""))
    return f"{published_date(item)}_{title}_[{aweme_id[-8:]}]"


def readable_creator_root(nickname: str, author_id: str) -> str:
    short_id = str(author_id or "unknown")[-8:]
    return f"抖音_博主_{readable_title(nickname)}_[{short_id}]"


def output_state_key(output_dir: Path) -> str:
    return hashlib.sha256(str(output_dir.expanduser().resolve()).encode("utf-8")).hexdigest()[:12]


def job_state_dir(author_id: str, output_dir: Path) -> Path:
    output_key = output_state_key(output_dir)
    safe_author = re.sub(r"[^0-9A-Za-z_-]+", "_", str(author_id or "unknown"))[-32:]
    return STATE_ROOT / "jobs" / f"{safe_author}_{output_key}"


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_text_private(path: Path, text: str) -> Path:
    ensure_private_dir(path.parent)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            os.chmod(temporary_path, 0o600)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
        return path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json_private(path: Path, data: dict) -> Path:
    return write_text_private(path, json.dumps(data, ensure_ascii=False, indent=2))


def is_at_least_1080p(width: int, height: int) -> bool:
    short_edge, long_edge = sorted((int(width or 0), int(height or 0)))
    return short_edge >= 1080 and long_edge >= 1920


def is_known_below_1080p(width: int, height: int) -> bool:
    width = int(width or 0)
    height = int(height or 0)
    return width > 0 and height > 0 and not is_at_least_1080p(width, height)


def probe_video(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise ValueError(f"视频没有可识别的视频流: {path}")
    return streams[0]


def require_1080p_file(path: Path) -> dict:
    stream = probe_video(path)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if not is_at_least_1080p(width, height):
        raise ValueError(f"视频分辨率只有 {width}x{height}，低于默认 1080p 门槛")
    codec = str(stream.get("codec_name") or "").lower()
    if codec != "h264":
        raise ValueError(f"视频编码为 {codec or '未知'}，不是默认兼容的 H.264")
    return stream


def find_volc_asr_script() -> Optional[Path]:
    configured = os.getenv("YICHEN_VOLC_ASR_SCRIPT")
    skills_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(configured).expanduser() if configured else None,
        skills_root / "yichen-volc-asr" / "scripts" / "transcribe.py",
        Path.home() / ".codex" / "skills" / "yichen-volc-asr" / "scripts" / "transcribe.py",
        Path.home() / ".hermes" / "skills" / "social-media" / "yichen-volc-asr" / "scripts" / "transcribe.py",
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def missing_asr_configuration() -> list[str]:
    missing = [
        name
        for name in ("TOS_ACCESS_KEY", "TOS_SECRET_KEY", "TOS_BUCKET")
        if not os.getenv(name)
    ]
    if not any(os.getenv(name) for name in ("VOLC_ASR_APP_ID", "VOLC_ASR_TRIAL_APP_ID", "VOLC_ASR_PAID_APP_ID")):
        missing.append("VOLC_ASR_TRIAL_APP_ID")
    if not any(os.getenv(name) for name in ("VOLC_ASR_TRIAL_TOKEN", "VOLC_ASR_PAID_TOKEN", "VOLC_ASR_TOKEN")):
        missing.append("VOLC_ASR_TRIAL_TOKEN")
    return missing


def require_asr_backend() -> Path:
    script = find_volc_asr_script()
    if not script:
        raise RuntimeError("缺少 yichen-volc-asr Skill，无法生成中文口播稿")
    missing = missing_asr_configuration()
    if missing:
        raise RuntimeError("中文口播稿转写缺少私有配置: " + ", ".join(missing))
    return script


def clean_chinese_transcript(value: str) -> str:
    text = value.strip()
    if "【完整文字】" in text:
        text = text.split("【完整文字】", 1)[1]
    if "【分段时间戳】" in text:
        text = text.split("【分段时间戳】", 1)[0]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines).strip() + ("\n" if lines else "")


def contains_chinese_text(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))


def extract_audio_for_asr(video_path: Path, state_dir: Path) -> Path:
    ensure_private_dir(state_dir)
    audio_path = state_dir / "转写音频.m4a"
    if audio_path.is_file() and audio_path.stat().st_size > 0:
        return audio_path
    temporary_path = state_dir / ".转写音频.part.m4a"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(temporary_path),
    ]
    subprocess.run(command, timeout=1800, check=True)
    os.replace(temporary_path, audio_path)
    audio_path.chmod(0o600)
    return audio_path


def transcribe_to_chinese(
    video_path: Path,
    transcript_path: Path,
    aweme_id: str,
    asr_script: Path,
) -> Path:
    if transcript_path.is_file() and transcript_path.stat().st_size > 0:
        return transcript_path

    state_dir = ensure_private_dir(STATE_ROOT / "asr" / str(aweme_id))
    audio_path = extract_audio_for_asr(video_path, state_dir)
    raw_transcript = Path(f"{audio_path}.txt")
    if not raw_transcript.is_file() or raw_transcript.stat().st_size == 0:
        subprocess.run(
            [sys.executable, str(asr_script), str(audio_path), "--transcribe-only"],
            timeout=7200,
            check=True,
        )
    if not raw_transcript.is_file():
        raise RuntimeError("ASR 完成后没有生成转写文本")

    clean_text = clean_chinese_transcript(raw_transcript.read_text(encoding="utf-8"))
    if not clean_text:
        raise RuntimeError("ASR 转写结果为空")
    if not contains_chinese_text(clean_text):
        raise RuntimeError("ASR 转写结果不含中文，拒绝写入中文口播稿")
    return write_text_private(transcript_path, clean_text)
