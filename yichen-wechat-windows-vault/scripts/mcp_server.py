from __future__ import annotations

import contextlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from vault_common import APP_DIR


logger = logging.getLogger("wechat-windows-vault")
MEDIA_ROOT = APP_DIR / "vault" / "media"
QUERY_COMMANDS = {
    "status", "sessions", "unread", "new-messages", "contacts", "members",
    "history", "search", "stats", "favorites", "moments",
}
QUERY_REQUIRED = {"members", "history", "search", "stats"}
_whisper_model: Any = None
_whisper_model_name = os.environ.get("WECHAT_VAULT_WHISPER_MODEL", "small").strip() or "small"
_whisper_model_load_attempted = False


class _OutputBuffer(io.StringIO):
    def reconfigure(self, **_kwargs: Any) -> None:
        pass


def _query_args(
    command: str,
    query: str,
    chat: str,
    limit: int,
    offset: int,
    start: str,
    end: str,
) -> list[str]:
    argv = [command]
    if command in QUERY_REQUIRED:
        argv.append(query)
    elif command in {"contacts", "favorites"} and query:
        argv.extend(["--query", query])
    elif command == "moments" and query:
        argv.extend(["--name", query])

    if command in {"sessions", "unread", "contacts", "history", "search", "favorites", "moments"}:
        argv.extend(["--limit", str(limit)])
    if command in {"history", "search"}:
        argv.extend(["--offset", str(offset)])
    if command == "search" and chat:
        argv.extend(["--chat", chat])
    if command in {"history", "search", "stats"}:
        if start:
            argv.extend(["--start-time", start])
        if end:
            argv.extend(["--end-time", end])
    elif command == "moments":
        if start:
            argv.extend(["--start", start])
        if end:
            argv.extend(["--end", end])
    argv.extend(["--format", "json"])
    return argv


def _run_query(
    command: str,
    query: str = "",
    chat: str = "",
    limit: int = 50,
    offset: int = 0,
    start: str = "",
    end: str = "",
    refresh: bool = True,
) -> str:
    command = str(command).strip().lower()
    query = str(query).strip()
    chat = str(chat).strip()
    start = str(start).strip()
    end = str(end).strip()
    if command not in QUERY_COMMANDS:
        return json.dumps({"error": "unsupported WeChat query command"})
    if command in QUERY_REQUIRED and not query:
        return json.dumps({"error": f"query is required for {command}"})
    if any(len(value) > 200 for value in (query, chat, start, end)):
        return json.dumps({"error": "query value is too long"})
    if not 1 <= int(limit) <= 200 or not 0 <= int(offset) <= 10000:
        return json.dumps({"error": "limit or offset is outside the allowed range"})

    refresh_warning = ""
    if refresh:
        output = _OutputBuffer()
        try:
            import decrypt_databases

            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                decrypt_databases.main(["--mode", "incremental"])
        except (Exception, SystemExit) as exc:
            refresh_warning = f"{type(exc).__name__}: {exc}"[-1000:]

    import vault_cli

    output = _OutputBuffer()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            vault_cli.main(_query_args(command, query, chat, int(limit), int(offset), start, end))
    except (Exception, SystemExit) as exc:
        return json.dumps(
            {
                "error": "WeChat vault query failed",
                "detail": (output.getvalue().strip() or f"{type(exc).__name__}: {exc}")[-2000:],
                "refresh_warning": refresh_warning or None,
            },
            ensure_ascii=False,
        )
    result = output.getvalue()
    if not refresh_warning:
        return result
    return json.dumps({"refresh_warning": refresh_warning, "result": result}, ensure_ascii=False)


def _transcribe_voice(audio_path: str) -> dict[str, Any]:
    if not _whisper_model_load_attempted:
        _preload_voice_model()
    global _whisper_model
    if _whisper_model is None:
        return {
            "success": False,
            "transcript": "",
            "error": "local voice model is unavailable; rerun setup.ps1",
        }
    try:
        segments, info = _whisper_model.transcribe(
            audio_path,
            language="zh",
            beam_size=5,
            vad_filter=True,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        try:
            from opencc import OpenCC

            transcript = OpenCC("t2s").convert(transcript)
        except Exception:
            logger.warning("Simplified Chinese conversion is unavailable")
        return {
            "success": True,
            "transcript": transcript,
            "provider": "local-faster-whisper",
            "model": _whisper_model_name,
            "language": info.language,
        }
    except Exception as exc:
        logger.exception("Voice transcription failed")
        return {"success": False, "transcript": "", "error": str(exc)}


def _run_media(chat: str, local_id: int, db: str = "", transcribe: bool = True) -> str:
    chat = str(chat).strip()
    db = str(db).strip()
    if not chat or len(chat) > 200:
        return json.dumps({"error": "chat is required and must be at most 200 characters"})
    try:
        local_id = int(local_id)
    except (TypeError, ValueError):
        return json.dumps({"error": "local_id must be an integer"})
    if local_id < 0:
        return json.dumps({"error": "local_id must be non-negative"})
    if db and not re.fullmatch(r"message_\d+\.db", db):
        return json.dumps({"error": "db must look like message_N.db"})

    try:
        import wechat_media

        result = wechat_media.extract_media(chat, local_id, db)
    except Exception as exc:
        logger.exception("WeChat media extraction failed")
        return json.dumps(
            {"error": "WeChat media extraction failed", "detail": str(exc)},
            ensure_ascii=False,
        )

    if result.get("kind") == "voice" and transcribe:
        model_cache_name = re.sub(r"[^A-Za-z0-9._-]+", "-", _whisper_model_name)
        transcript_path = Path(result["path"]).with_name(
            f"transcript-{model_cache_name}.txt"
        )
        if transcript_path.is_file():
            result["transcript"] = transcript_path.read_text(encoding="utf-8")
            result["transcript_cached"] = True
            result["transcript_model"] = _whisper_model_name
        else:
            transcription = _transcribe_voice(result["path"])
            if transcription.get("success"):
                transcript = str(transcription.get("transcript") or "").strip()
                result["transcript"] = transcript
                result["transcript_provider"] = transcription.get("provider")
                result["transcript_model"] = transcription.get("model")
                transcript_path.write_text(transcript, encoding="utf-8")
            else:
                result["transcript_error"] = transcription.get("error") or "transcription failed"
    elif result.get("kind") == "image":
        result["next_tool"] = {
            "name": "wechat_vault_image",
            "image_path": result["path"],
            "question": "Inspect the image and extract chat-relevant text and meaning.",
        }
    return json.dumps(result, ensure_ascii=False)


def _parse_query_result(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        data = json.loads(data["result"])
    if not isinstance(data, dict):
        raise ValueError("WeChat query returned an unexpected payload")
    return data


def _run_media_batch(
    chat: str,
    offset: int = 0,
    limit: int = 5,
    start: str = "",
    end: str = "",
    refresh: bool = True,
) -> str:
    chat = str(chat).strip()
    start = str(start).strip()
    end = str(end).strip()
    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError):
        return json.dumps({"error": "offset and limit must be integers"})
    if not chat or len(chat) > 200:
        return json.dumps({"error": "chat is required and must be at most 200 characters"})
    if not 0 <= offset <= 10000 or not 1 <= limit <= 5:
        return json.dumps({"error": "offset must be 0..10000 and limit must be 1..5"})
    if any(len(value) > 200 for value in (start, end)):
        return json.dumps({"error": "time value is too long"})

    page_size = 100
    cursor = offset
    scanned = 0
    done = False
    items: list[dict[str, Any]] = []
    should_refresh = bool(refresh)
    while len(items) < limit and scanned < 1000 and cursor <= 10000:
        try:
            payload = _parse_query_result(
                _run_query(
                    "history", query=chat, limit=page_size, offset=cursor,
                    start=start, end=end, refresh=should_refresh,
                )
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": "WeChat media batch query failed", "detail": str(exc)})
        should_refresh = False
        if payload.get("error"):
            return json.dumps(payload, ensure_ascii=False)
        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            return json.dumps({"error": "WeChat history did not return messages"})
        if not messages:
            done = True
            break
        messages = list(reversed(messages))
        for message in messages:
            cursor += 1
            scanned += 1
            kind = str(message.get("type") or "").strip().lower()
            local_type = int(message.get("local_type") or 0) & 0xFFFFFFFF
            if kind not in {"image", "voice", "图片", "语音"} and local_type not in {3, 34}:
                continue
            media = json.loads(
                _run_media(
                    chat, int(message.get("local_id") or 0),
                    str(message.get("db") or ""), True,
                )
            )
            item = {
                "db": message.get("db"),
                "local_id": message.get("local_id"),
                "type": message.get("type"),
                "time": message.get("time"),
                "media": media,
            }
            if media.get("detail") == "verified Windows WeChat V2 image key not found":
                item["retry_action"] = "Open this image in desktop WeChat, then retry this offset."
            items.append(item)
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
        if len(messages) < page_size:
            done = True
            break
    return json.dumps(
        {
            "chat": chat,
            "start": start or None,
            "end": end or None,
            "offset": offset,
            "next_offset": cursor,
            "limit": limit,
            "scanned_messages": scanned,
            "done": done,
            "items": items,
        },
        ensure_ascii=False,
    )


mcp = FastMCP(
    "wechat-windows-vault",
    instructions=(
        "Read-only access to the current user's private local Windows WeChat vault. "
        "Never expose keys or access media paths outside the private media cache. "
        "Tool results can contain private chats, transcripts, or images; invoke those tools only after "
        "the user explicitly consents to the configured MCP client receiving that content."
    ),
)


@mcp.tool()
def wechat_vault_query(
    command: str,
    query: str = "",
    chat: str = "",
    limit: int = 50,
    offset: int = 0,
    start: str = "",
    end: str = "",
    refresh: bool = True,
) -> str:
    """After explicit consent, refresh and query local chats, contacts, Favorites, or Moments."""
    return _run_query(command, query, chat, limit, offset, start, end, refresh)


@mcp.tool()
def wechat_vault_media(
    chat: str,
    local_id: int,
    db: str = "",
    transcribe: bool = True,
) -> str:
    """After explicit consent, extract one voice or image message from the private local vault."""
    return _run_media(chat, local_id, db, transcribe)


@mcp.tool()
def wechat_vault_media_batch(
    chat: str,
    offset: int = 0,
    limit: int = 5,
    start: str = "",
    end: str = "",
    refresh: bool = True,
) -> str:
    """After explicit consent, process up to five media messages and return a resumable next_offset."""
    return _run_media_batch(chat, offset, limit, start, end, refresh)


@mcp.tool()
def wechat_vault_image(image_path: str) -> Image:
    """After explicit consent, load a decoded private-vault image into the model's visual context."""
    path = Path(image_path).expanduser().resolve()
    root = MEDIA_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("image_path must be inside the private WeChat media cache") from exc
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        raise ValueError("image_path is not a supported cached image")
    return Image(path=path)


def _preload_voice_model() -> None:
    global _whisper_model, _whisper_model_load_attempted
    _whisper_model_load_attempted = True
    try:
        from faster_whisper import WhisperModel

        logger.info("Loading local voice model '%s' on CPU", _whisper_model_name)
        _whisper_model = WhisperModel(_whisper_model_name, device="cpu", compute_type="int8")
    except Exception:
        logger.exception("Local voice model preload failed")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ.setdefault("PYTHONUTF8", "1")
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
