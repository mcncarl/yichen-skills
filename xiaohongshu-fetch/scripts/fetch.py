#!/usr/bin/env python3
"""
小红书笔记抓取器。

默认从网页的 window.__INITIAL_STATE__ 中提取元数据，并下载视频、字幕或图片。
不写入飞书，不读取或保存 Cookie。
"""

import argparse
import html as html_lib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("错误: 请先安装 requests")
    print("运行: pip install requests")
    sys.exit(1)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def request_headers(referer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def extract_note_id(url: str) -> str:
    patterns = [
        r"/explore/([0-9a-zA-Z]+)",
        r"/discovery/item/([0-9a-zA-Z]+)",
        r"[?&]note_id=([0-9a-zA-Z]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts:
        return parts[-1]
    raise ValueError("无法从链接中识别 note_id")


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=request_headers(), timeout=60)
    response.raise_for_status()
    return response.text


def extract_initial_state(page_html: str) -> Dict[str, Any]:
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", page_html)
    if not match:
        raise ValueError("页面里没有找到 window.__INITIAL_STATE__，可能被风控或需要有效 xsec_token")

    start = match.end()
    end = page_html.find("</script>", start)
    if end == -1:
        raise ValueError("找到了 INITIAL_STATE 开头，但没有找到 script 结束位置")

    raw = page_html[start:end].strip().rstrip(";")
    raw = html_lib.unescape(raw)
    raw = re.sub(r"\bundefined\b", "null", raw)
    return json.loads(raw)


def collect_note_maps(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        note_map = obj.get("noteDetailMap")
        if isinstance(note_map, dict):
            yield note_map
        for value in obj.values():
            yield from collect_note_maps(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from collect_note_maps(value)


def extract_note(state: Dict[str, Any], note_id: str) -> Dict[str, Any]:
    for note_map in collect_note_maps(state):
        detail = note_map.get(note_id)
        if isinstance(detail, dict) and isinstance(detail.get("note"), dict):
            return detail["note"]
        for detail in note_map.values():
            if not isinstance(detail, dict):
                continue
            note = detail.get("note")
            if isinstance(note, dict) and (note.get("noteId") == note_id or note.get("id") == note_id):
                return note

    raise ValueError("INITIAL_STATE 中没有找到目标笔记数据")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    return cleaned.strip("_") or "item"


def first_value(data: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_media_v2(note: Dict[str, Any]) -> Dict[str, Any]:
    video = note.get("video", {}) or {}
    raw = video.get("mediaV2") or video.get("consumer", {}).get("mediaV2")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def stream_items_from(stream: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for codec in ("h264", "h265", "h266", "av1"):
        items = stream.get(codec) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield item


def collect_video_urls(note: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    media_v2 = parse_media_v2(note)
    streams = [
        media_v2.get("video", {}).get("stream", {}),
        note.get("video", {}).get("media", {}).get("stream", {}),
    ]

    for stream in streams:
        for item in stream_items_from(stream):
            master_url = first_value(item, ("masterUrl", "master_url"))
            backup_urls = first_value(item, ("backupUrls", "backup_urls")) or []
            for url in [master_url] + list(backup_urls):
                if url and url not in urls:
                    urls.append(url)
    return urls


def collect_subtitles(note: Dict[str, Any]) -> List[Dict[str, str]]:
    subtitles: List[Dict[str, str]] = []
    media_v2 = parse_media_v2(note)
    subtitle_map = media_v2.get("video", {}).get("subtitles", {}) or {}

    for label, entries in subtitle_map.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if url:
                subtitles.append({
                    "label": str(label),
                    "language": str(entry.get("language") or label),
                    "url": url,
                })

    def subtitle_priority(subtitle: Dict[str, str]) -> int:
        label = subtitle.get("label", "")
        language = subtitle.get("language", "")
        if label == "source":
            return 0
        if language.startswith("zh"):
            return 1
        return 2

    return sorted(subtitles, key=subtitle_priority)


def collect_images(note: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for image in note.get("imageList") or []:
        if not isinstance(image, dict):
            continue
        candidates = [
            image.get("urlDefault"),
            image.get("url"),
            image.get("urlPre"),
        ]
        for info in image.get("infoList") or []:
            if isinstance(info, dict):
                candidates.append(info.get("url"))
        for url in candidates:
            if url and url not in urls:
                urls.append(url)
                break
    return urls


def get_duration_ms(note: Dict[str, Any]) -> Optional[int]:
    media_v2 = parse_media_v2(note)
    for stream in [
        media_v2.get("video", {}).get("stream", {}),
        note.get("video", {}).get("media", {}).get("stream", {}),
    ]:
        for item in stream_items_from(stream):
            duration = first_value(item, ("duration", "videoDuration", "video_duration"))
            if duration:
                return int(duration)

    seconds = note.get("video", {}).get("consumer", {}).get("capa", {}).get("duration")
    if seconds:
        return int(float(seconds) * 1000)
    return None


def build_metadata(note: Dict[str, Any], source_url: str, note_id: str) -> Dict[str, Any]:
    user = note.get("user", {}) or {}
    tags = [item.get("name") for item in note.get("tagList") or [] if isinstance(item, dict) and item.get("name")]
    chapters = note.get("video", {}).get("consumer", {}).get("chapters") or []
    video_urls = collect_video_urls(note)
    subtitles = collect_subtitles(note)
    images = collect_images(note)

    return {
        "source_url": source_url,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note_id": note_id,
        "title": note.get("title", ""),
        "desc": note.get("desc", ""),
        "type": note.get("type", ""),
        "author": user.get("nickname", ""),
        "user_id": user.get("userId", ""),
        "time": note.get("time"),
        "last_update_time": note.get("lastUpdateTime"),
        "ip_location": note.get("ipLocation", ""),
        "interact_info": note.get("interactInfo", {}) or {},
        "tags": tags,
        "duration_ms": get_duration_ms(note),
        "video_url": video_urls[0] if video_urls else "",
        "backup_urls": video_urls[1:],
        "subtitle_urls": subtitles,
        "chapters": chapters,
        "image_count": len(images),
        "image_urls": images,
    }


def download_file(urls: List[str], output_path: Path, label: str, referer: str) -> Optional[Path]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        print(f"{label} 已存在，跳过下载: {output_path}")
        return output_path

    last_error: Optional[Exception] = None

    for index, url in enumerate(urls, start=1):
        try:
            response = requests.get(url, headers=request_headers(referer), stream=True, timeout=90)
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            next_percent = 0
            next_mb_report = 5

            with open(output_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = min(100, downloaded * 100 // total)
                        if percent >= next_percent or downloaded == total:
                            print(f"{label} 下载进度: {percent}% ({downloaded//1024//1024}MB / {total//1024//1024}MB)")
                            next_percent += 10
                    else:
                        downloaded_mb = downloaded // 1024 // 1024
                        if downloaded_mb >= next_mb_report:
                            print(f"{label} 已下载: {downloaded_mb}MB")
                            next_mb_report += 5

            return output_path
        except Exception as exc:
            last_error = exc
            if index < len(urls):
                print(f"{label} 当前地址失败，尝试备用地址...")

    print(f"{label} 下载失败: {last_error}")
    return None


def srt_to_transcript(srt_text: str) -> str:
    lines: List[str] = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_line_index = next((i for i, line in enumerate(block_lines) if "-->" in line), None)
        if time_line_index is None:
            continue
        start_time = block_lines[time_line_index].split("-->", 1)[0].strip()
        text = " ".join(block_lines[time_line_index + 1:]).strip()
        if text:
            lines.append(f"[{start_time}] {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="小红书笔记抓取器")
    parser.add_argument("url", help="小红书笔记链接")
    parser.add_argument("output_dir", nargs="?", help="输出目录，默认 ~/Downloads/xhs_<note_id>")
    parser.add_argument("--skip-media", action="store_true", help="只保存 HTML 和元数据，不下载视频/字幕/图片")
    args = parser.parse_args()

    note_id = extract_note_id(args.url)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else Path.home() / "Downloads" / f"xhs_{note_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("小红书笔记抓取器")
    print("=" * 50)
    print(f"笔记ID: {note_id}")
    print(f"输出目录: {output_dir}")

    try:
        page_html = fetch_html(args.url)
        html_path = output_dir / f"xhs_{note_id}.html"
        write_text(html_path, page_html)
        print(f"网页快照: {html_path}")

        state = extract_initial_state(page_html)
        note = extract_note(state, note_id)
        metadata = build_metadata(note, args.url, note_id)
        metadata_path = output_dir / f"xhs_{note_id}.metadata.json"
        write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
        print(f"元数据: {metadata_path}")
        print(f"标题: {metadata.get('title') or '(无标题)'}")
        print(f"作者: {metadata.get('author') or '(未知)'}")
        print(f"类型: {metadata.get('type') or '(未知)'}")

        if args.skip_media:
            print("已按 --skip-media 跳过媒体下载")
            return

        if metadata["type"] == "video":
            video_urls = collect_video_urls(note)
            if video_urls:
                video_path = output_dir / f"xhs_{note_id}.mp4"
                saved_video = download_file(video_urls, video_path, "视频", args.url)
                if saved_video:
                    size_mb = saved_video.stat().st_size / 1024 / 1024
                    print(f"视频: {saved_video} ({size_mb:.2f} MB)")
            else:
                print("未找到视频直链")

            subtitles = collect_subtitles(note)
            source_transcript_written = False
            fallback_srt: Optional[Path] = None
            for subtitle in subtitles:
                label = safe_name(f"{subtitle['label']}_{subtitle['language']}")
                srt_path = output_dir / f"xhs_{note_id}.{label}.srt"
                saved_srt = download_file([subtitle["url"]], srt_path, f"字幕 {label}", args.url)
                if saved_srt:
                    print(f"字幕 {label}: {saved_srt}")
                    fallback_srt = fallback_srt or saved_srt

                is_preferred_transcript = (
                    subtitle.get("label") == "source"
                    or subtitle.get("language", "").startswith("zh")
                )
                if saved_srt and is_preferred_transcript and not source_transcript_written:
                    transcript = srt_to_transcript(saved_srt.read_text(encoding="utf-8", errors="ignore"))
                    transcript_path = output_dir / f"xhs_{note_id}.transcript.txt"
                    write_text(transcript_path, transcript)
                    print(f"口播文本: {transcript_path}")
                    source_transcript_written = True
            if fallback_srt and not source_transcript_written:
                transcript = srt_to_transcript(fallback_srt.read_text(encoding="utf-8", errors="ignore"))
                transcript_path = output_dir / f"xhs_{note_id}.transcript.txt"
                write_text(transcript_path, transcript)
                print(f"口播文本: {transcript_path}")
        else:
            image_urls = collect_images(note)
            if not image_urls:
                print("未找到图片地址")
                return
            images_dir = output_dir / "images"
            for index, image_url in enumerate(image_urls, start=1):
                suffix = Path(urlparse(image_url).path).suffix or ".jpg"
                image_path = images_dir / f"xhs_{note_id}_{index:02d}{suffix}"
                saved_image = download_file([image_url], image_path, f"图片 {index}", args.url)
                if saved_image:
                    print(f"图片 {index}: {saved_image}")

        print("抓取完成")
    except Exception as exc:
        print(f"抓取失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
