#!/usr/bin/env python3
"""
抖音视频下载器 - 使用 Playwright 拦截 Network 响应获取无水印直链

依赖安装:
    pip install playwright requests
    # Chromium 首次缺失时脚本会自动执行: python3 -m playwright install chromium

用法:
    python3 download.py "<抖音链接>" [输出路径]
    python3 download.py "https://www.douyin.com/video/7611845735025364265"
    python3 download.py "<抖音链接>" "/tmp/my_video.mp4"
    python3 download.py "<抖音链接>" --metadata-only
"""

import argparse
import html as html_lib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

import requests
from artifacts import (
    STATE_ROOT,
    TRANSCRIPT_FILENAME,
    VIDEO_FILENAME,
    contains_chinese_text,
    ensure_private_dir,
    is_at_least_1080p,
    is_known_below_1080p,
    readable_video_folder,
    require_1080p_file,
    require_asr_backend,
    transcribe_to_chinese,
    write_json_private,
    write_text_private,
)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("错误: 请先安装 playwright")
    print("运行: pip install playwright && playwright install chromium")
    sys.exit(1)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MISSING_BROWSER_HINTS = (
    "Executable doesn't exist",
    "playwright install",
    "Looks like Playwright was just installed",
)

CAPTION_CONTAINER_KEYS = {
    "captiondownloadaddr",
    "captioninfo",
    "captioninfos",
    "captions",
    "subtitleinfo",
    "subtitleinfos",
    "subtitles",
}
CAPTION_URL_KEYS = {
    "backupurllist",
    "backupurls",
    "captiondownloadaddr",
    "captionurl",
    "downloadaddr",
    "downloadurl",
    "url",
    "urllist",
    "urls",
}
DOUYIN_PAGE_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")


def extract_video_id(url: str):
    """从 URL 中提取抖音视频 ID"""
    patterns = [
        r'/video/(\d+)',
        r'modal_id=(\d+)',
        r'resource_id=(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def validate_douyin_page_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    trusted_host = any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in DOUYIN_PAGE_HOST_SUFFIXES
    )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("抖音页面地址端口无效") from exc
    if (
        parsed.scheme.lower() != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not trusted_host
    ):
        raise ValueError(f"拒绝不受信任的抖音页面地址: {hostname or '(空)'}")
    return url


def normalize_url(url: str) -> str:
    """将各种抖音 URL 格式转换为标准的视频详情页 URL"""
    validate_douyin_page_url(url)
    video_id = extract_video_id(url)
    if video_id:
        return f"https://www.douyin.com/video/{video_id}"
    return url


def sanitize_douyin_page_url(url: str) -> str:
    validate_douyin_page_url(url)
    parsed = urlsplit(url)
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", "", ""))


def safe_douyin_referer(referer: str) -> str:
    """只向媒体 CDN 发送不含查询参数或片段的抖音页面来源。"""
    validate_douyin_page_url(referer)
    video_id = extract_video_id(referer)
    if video_id:
        return f"https://www.douyin.com/video/{video_id}"
    return sanitize_douyin_page_url(referer)


def ensure_playwright_chromium():
    """首次运行时自动安装 Playwright Chromium。"""
    print("检测到 Playwright Chromium 缺失，正在自动安装...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("自动安装 Chromium 失败，请手动运行: python3 -m playwright install chromium") from exc


@contextmanager
def isolated_sync_playwright():
    """Keep Playwright's ephemeral profiles inside one self-cleaning directory."""
    temp_keys = ("TMPDIR", "TMP", "TEMP")
    previous = {key: os.environ.get(key) for key in temp_keys}
    with tempfile.TemporaryDirectory(prefix="yichen-douyin-playwright-") as runtime_dir:
        for key in temp_keys:
            os.environ[key] = runtime_dir
        try:
            with sync_playwright() as playwright:
                yield playwright
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def launch_compatible_browser(playwright, *, headless: bool, direct: bool = False):
    """Launch bundled Chromium, falling back to an installed Google Chrome."""
    launch_options = {"headless": headless}
    if direct:
        launch_options["args"] = ["--no-proxy-server"]
    try:
        return playwright.chromium.launch(**launch_options)
    except PlaywrightError as bundled_error:
        if not any(hint in str(bundled_error) for hint in MISSING_BROWSER_HINTS):
            raise
        try:
            return playwright.chromium.launch(channel="chrome", **launch_options)
        except PlaywrightError as chrome_error:
            raise bundled_error from chrome_error


@contextmanager
def http_response(url: str, *, direct: bool = False, **kwargs):
    """Open one HTTP response, optionally ignoring proxy settings from the environment."""
    session = None
    response = None
    try:
        if direct:
            session = requests.Session()
            session.trust_env = False
            response = session.get(url, **kwargs)
        else:
            response = requests.get(url, **kwargs)
        yield response
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if session is not None:
            session.close()


def normalize_url_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(url) for url in value if url]


def get_best_video_stream(aweme_data: dict) -> Optional[dict]:
    """选择分辨率、码率最高的兼容 H.264 码流。"""
    video = aweme_data.get('video', {}) or {}
    variants = []
    for item in video.get('bit_rate') or []:
        if item.get('is_h265') or item.get('is_bytevc1'):
            continue
        play_addr = item.get('play_addr', {}) or {}
        url_list = normalize_url_list(play_addr.get('url_list'))
        if not url_list:
            continue
        width = int(play_addr.get('width') or 0)
        height = int(play_addr.get('height') or 0)
        bit_rate = int(item.get('bit_rate') or 0)
        variants.append({
            'url': url_list[0],
            'urls': list(dict.fromkeys(url_list)),
            'width': width,
            'height': height,
            'bit_rate': bit_rate,
            'data_size': int(play_addr.get('data_size') or 0),
            'score': (width * height, bit_rate),
        })

    if variants:
        ordered = sorted(variants, key=lambda item: item['score'], reverse=True)
        selected = dict(ordered[0])
        compatible_fallbacks = [
            variant
            for variant in ordered
            if not is_known_below_1080p(variant['width'], variant['height'])
        ] or ordered[:1]
        selected['urls'] = list(
            dict.fromkeys(url for variant in compatible_fallbacks for url in variant['urls'])
        )
        selected.pop('score', None)
        return selected

    candidates = [
        (video.get('play_addr_h264') or {}, True),
        (video.get('play_addr') or {}, False),
        (video.get('download_addr') or {}, False),
    ]

    fallback_variants = []
    for item, explicit_h264 in candidates:
        url_list = normalize_url_list(item.get('url_list'))
        if url_list:
            width = int(item.get('width') or video.get('width') or 0)
            height = int(item.get('height') or video.get('height') or 0)
            fallback_variants.append({
                'url': url_list[0],
                'urls': list(dict.fromkeys(url_list)),
                'width': width,
                'height': height,
                'bit_rate': 0,
                'data_size': int(item.get('data_size') or 0),
                'score': (
                    is_at_least_1080p(width, height),
                    explicit_h264,
                    width * height,
                ),
            })
    if not fallback_variants:
        return None
    ordered = sorted(fallback_variants, key=lambda item: item['score'], reverse=True)
    selected = dict(ordered[0])
    compatible_fallbacks = [
        variant
        for variant in ordered
        if not is_known_below_1080p(variant['width'], variant['height'])
    ] or ordered[:1]
    selected['urls'] = list(
        dict.fromkeys(url for variant in compatible_fallbacks for url in variant['urls'])
    )
    selected.pop('score', None)
    return selected


def get_best_video_url(aweme_data: dict) -> Optional[str]:
    stream = get_best_video_stream(aweme_data)
    return stream['url'] if stream else None


def _caption_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _caption_urls(value: Any) -> List[str]:
    urls: List[str] = []

    def visit(node: Any, url_field: bool = False) -> None:
        if isinstance(node, str):
            if url_field and node.startswith(("http://", "https://")) and node not in urls:
                urls.append(node)
            return
        if isinstance(node, list):
            for item in node:
                visit(item, url_field=url_field)
            return
        if not isinstance(node, dict):
            return
        for key, child in node.items():
            if _caption_key(key) in CAPTION_URL_KEYS:
                visit(child, url_field=True)

    visit(value, url_field=isinstance(value, str))
    return urls


def collect_native_caption_candidates(aweme_data: dict) -> List[dict]:
    """收集平台字幕地址，优先中文，其次原始语言。"""
    containers: List[Tuple[str, Any]] = []

    def find_containers(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized = _caption_key(key)
                if normalized in CAPTION_CONTAINER_KEYS:
                    containers.append((normalized, child))
                find_containers(child)
        elif isinstance(node, list):
            for child in node:
                find_containers(child)

    find_containers(aweme_data)
    candidates: List[dict] = []
    seen_urls = set()

    def add_candidate(entry: Any, label: str) -> None:
        urls = _caption_urls(entry)
        if not urls or urls[0] in seen_urls:
            return
        seen_urls.update(urls)
        language = label
        source = label.lower() in {"source", "original", "origin"}
        if isinstance(entry, dict):
            language = str(
                entry.get("language_code")
                or entry.get("languageCode")
                or entry.get("language")
                or entry.get("lang")
                or entry.get("locale")
                or entry.get("code")
                or label
            )
            source = source or bool(
                entry.get("is_source")
                or entry.get("isSource")
                or entry.get("is_original")
                or entry.get("isOriginal")
                or entry.get("source") == "source"
            )
        candidates.append({"urls": urls, "language": language, "source": source})

    for label, container in containers:
        if isinstance(container, list):
            for entry in container:
                add_candidate(entry, label)
        elif isinstance(container, dict):
            if _caption_urls(container):
                add_candidate(container, label)
            else:
                for child_label, entries in container.items():
                    if isinstance(entries, list):
                        for entry in entries:
                            add_candidate(entry, str(child_label))
                    else:
                        add_candidate(entries, str(child_label))
        else:
            add_candidate(container, label)

    def priority(candidate: dict) -> int:
        language = str(candidate.get("language") or "").lower()
        if re.search(r"(^|[-_])(zh|cmn)([-_]|$)|chinese|中文", language):
            return 0
        if candidate.get("source"):
            return 1
        return 2

    return sorted(candidates, key=priority)


def _plain_transcript_lines(lines: Iterable[str]) -> str:
    cleaned: List[str] = []
    for raw_line in lines:
        line = html_lib.unescape(str(raw_line)).replace("\ufeff", "").strip()
        if not line:
            continue
        upper = line.upper()
        if (
            line.isdigit()
            or "-->" in line
            or upper == "WEBVTT"
            or upper.startswith(("NOTE ", "STYLE", "REGION", "KIND:", "LANGUAGE:"))
        ):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not cleaned or cleaned[-1] != line):
            cleaned.append(line)
    return "\n".join(cleaned) + ("\n" if cleaned else "")


def caption_body_to_transcript(body: str) -> str:
    """兼容 SRT、WebVTT 与常见 JSON 字幕，输出无时间戳纯文本。"""
    source = body.strip()
    if not source:
        return ""
    try:
        payload = json.loads(source)
    except (json.JSONDecodeError, TypeError):
        return _plain_transcript_lines(source.replace("\r\n", "\n").splitlines())

    direct_objects = [payload]
    if isinstance(payload, dict):
        for key in ("result", "data"):
            value = payload.get(key)
            if isinstance(value, dict):
                direct_objects.append(value)
    for node in direct_objects:
        if not isinstance(node, dict):
            continue
        for key in ("full_text", "fullText", "transcript", "text"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return _plain_transcript_lines([value])

    texts: List[str] = []
    text_keys = {"content", "sentence", "text", "transcript", "word", "words"}

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key) in text_keys and isinstance(value, str) and value.strip():
                    texts.append(value)
                elif isinstance(value, (dict, list)):
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(payload)
    return _plain_transcript_lines(texts)


def download_native_transcript(
    aweme_data: dict,
    transcript_path: Path,
    aweme_id: str,
    referer: str,
    direct: bool = False,
) -> Optional[Path]:
    """尝试使用抖音原生字幕；原始字幕只缓存到私有状态目录。"""
    headers = {"User-Agent": USER_AGENT, "Referer": safe_douyin_referer(referer)}
    for candidate in collect_native_caption_candidates(aweme_data):
        for url in candidate["urls"]:
            try:
                with http_response(url, direct=direct, headers=headers, timeout=60) as response:
                    response.raise_for_status()
                    content_type = str(response.headers.get("Content-Type", "")).lower()
                    if "text/html" in content_type or "application/xhtml+xml" in content_type:
                        continue
                    transcript = caption_body_to_transcript(response.text)
                    if not transcript or not contains_chinese_text(transcript):
                        continue
                    state_dir = ensure_private_dir(STATE_ROOT / "captions" / str(aweme_id))
                    write_text_private(state_dir / "平台字幕.txt", response.text)
                    return write_text_private(transcript_path, transcript)
            except Exception:
                continue
    return None


def create_chinese_transcript(
    aweme_data: dict,
    video_path: Path,
    transcript_path: Path,
    aweme_id: str,
    referer: str,
    asr_script: Optional[Path] = None,
    direct: bool = False,
) -> Tuple[str, Path]:
    """优先平台字幕，无字幕时再调用独立 ASR Skill。"""
    if transcript_path.is_file() and transcript_path.stat().st_size > 0:
        return "已有口播稿", transcript_path

    native = download_native_transcript(
        aweme_data,
        transcript_path,
        aweme_id,
        referer,
        direct=direct,
    )
    if native:
        return "平台字幕", native

    try:
        backend = asr_script or require_asr_backend()
    except RuntimeError as exc:
        raise RuntimeError(f"未发现可用平台字幕，中文口播稿待转写：{exc}") from exc
    return "火山 ASR", transcribe_to_chinese(video_path, transcript_path, aweme_id, backend)


def fetch_video_info(
    url: str,
    timeout: int = 60,
    headed: bool = False,
    storage_state=None,
    capture_storage_state: bool = False,
    direct: bool = False,
):
    """
    使用 Playwright 拦截 aweme/detail API 获取视频信息
    返回包含 video_url, title, author 等信息的字典
    """
    try:
        return _fetch_video_info_once(
            url,
            timeout=timeout,
            headed=headed,
            storage_state=storage_state,
            capture_storage_state=capture_storage_state,
            direct=direct,
        )
    except PlaywrightError as exc:
        if any(hint in str(exc) for hint in MISSING_BROWSER_HINTS):
            ensure_playwright_chromium()
            return _fetch_video_info_once(
                url,
                timeout=timeout,
                headed=headed,
                storage_state=storage_state,
                capture_storage_state=capture_storage_state,
                direct=direct,
            )
        raise


def _fetch_video_info_once(
    url: str,
    timeout: int = 60,
    headed: bool = False,
    storage_state=None,
    capture_storage_state: bool = False,
    direct: bool = False,
):
    """单次打开页面并拦截详情接口。"""
    video_url = None
    aweme_data = None
    captured_storage_state = None
    normalized = normalize_url(url)

    with isolated_sync_playwright() as p:
        browser = launch_compatible_browser(p, headless=not headed, direct=direct)
        try:
            context_options = {
                'user_agent': USER_AGENT,
                'locale': 'zh-CN',
            }
            if storage_state:
                context_options['storage_state'] = storage_state
            context = browser.new_context(**context_options)
            page = context.new_page()

            def handle_response(response):
                nonlocal video_url, aweme_data
                if 'aweme/detail' in response.url and 'douyin.com' in response.url:
                    try:
                        body = response.json()
                        aweme_data = body.get('aweme_detail', {})
                        video_url = get_best_video_url(aweme_data)
                    except Exception:
                        pass

            page.on('response', handle_response)

            print(f"正在访问: {normalized}")
            try:
                page.goto(normalized, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                print(f"页面加载提示: {e}")
            if page.url.startswith(("http://", "https://")):
                validate_douyin_page_url(page.url)

            deadline = time.time() + timeout
            while time.time() < deadline and not aweme_data:
                page.wait_for_timeout(1000)
            if capture_storage_state:
                captured_storage_state = context.storage_state(indexed_db=True)
        finally:
            browser.close()

    if not aweme_data:
        message = "无法获取视频数据，请检查链接是否有效"
        if not direct:
            message += "；若系统代理导致页面空白，请在确认允许直连后使用 --direct 重试"
        raise ValueError(message)

    if not video_url:
        video_url = get_best_video_url(aweme_data)

    result = {
        'video_url': video_url,
        'video_stream': get_best_video_stream(aweme_data),
        'title': aweme_data.get('desc', ''),
        'author': aweme_data.get('author', {}).get('nickname', ''),
        'aweme_id': aweme_data.get('aweme_id', ''),
        'aweme_data': aweme_data,
    }
    if capture_storage_state:
        result['storage_state'] = captured_storage_state
    return result


def build_metadata(info: dict, source_url: str) -> dict:
    """生成不包含临时直链的精简元数据。"""
    aweme_data = info.get('aweme_data', {}) or {}
    author = aweme_data.get('author', {}) or {}
    statistics = aweme_data.get('statistics', {}) or {}
    video = aweme_data.get('video', {}) or {}

    aweme_id = info.get('aweme_id') or aweme_data.get('aweme_id', '')
    canonical_source = (
        f"https://www.douyin.com/video/{aweme_id}"
        if aweme_id
        else sanitize_douyin_page_url(source_url)
    )
    return {
        'source_url': canonical_source,
        'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'aweme_id': aweme_id,
        'title': info.get('title') or aweme_data.get('desc', ''),
        'author': info.get('author') or author.get('nickname', ''),
        'author_id': author.get('uid', ''),
        'create_time': aweme_data.get('create_time'),
        'duration_ms': video.get('duration'),
        'statistics': statistics,
    }


def download_video(
    video_url: Union[str, List[str]],
    output_path: str,
    referer: str = 'https://www.douyin.com/',
    validator: Optional[Callable[[Path], Any]] = None,
    direct: bool = False,
) -> str:
    """按顺序尝试主地址和备用地址，下载视频到本地。"""
    candidates = [video_url] if isinstance(video_url, str) else list(video_url or [])
    candidates = [str(url) for url in candidates if url]
    if not candidates:
        raise ValueError("没有拿到可下载的视频直链")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        'User-Agent': USER_AGENT,
        'Referer': safe_douyin_referer(referer),
    }

    last_error: Optional[Exception] = None
    for index, candidate in enumerate(candidates, start=1):
        output.unlink(missing_ok=True)
        try:
            with http_response(
                candidate,
                direct=direct,
                headers=headers,
                stream=True,
                timeout=60,
            ) as response:
                response.raise_for_status()

                content_type = str(response.headers.get('Content-Type', '')).lower()
                if 'text/html' in content_type or 'application/xhtml+xml' in content_type:
                    raise ValueError(f"媒体地址返回了网页内容: {content_type.split(';', 1)[0]}")
                total = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                next_percent = 0
                next_mb_report = 5

                with open(output, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                percent = downloaded * 100 // total
                                if percent >= next_percent or downloaded == total:
                                    print(
                                        f"下载进度: {percent}% "
                                        f"({downloaded//1024//1024}MB / {total//1024//1024}MB)"
                                    )
                                    next_percent += 10
                            else:
                                downloaded_mb = downloaded // 1024 // 1024
                                if downloaded_mb >= next_mb_report:
                                    print(f"已下载: {downloaded_mb}MB")
                                    next_mb_report += 5
                content_encoding = str(response.headers.get('Content-Encoding', '')).lower()
                if total and not content_encoding and downloaded != total:
                    raise ValueError(f"Content-Length 不匹配: 预期 {total}，实际 {downloaded}")
                if validator:
                    validator(output)
                return str(output)
        except Exception as exc:
            last_error = exc
            output.unlink(missing_ok=True)
            if index < len(candidates):
                print("当前视频地址失败，尝试备用地址...")

    raise RuntimeError(f"所有视频地址均下载失败（共 {len(candidates)} 个）") from last_error


def main():
    parser = argparse.ArgumentParser(description="抖音视频下载器")
    parser.add_argument("url", help="抖音视频链接")
    parser.add_argument("output_path", nargs="?", help="输出根目录，默认 ~/Downloads")
    parser.add_argument("--metadata-only", action="store_true", help="只检查元数据，不写入用户目录")
    parser.add_argument("--timeout", type=int, default=60, help="等待 aweme/detail 响应的秒数，默认 60")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="显式绕过系统代理直连抖音；仅在用户允许后使用",
    )
    args = parser.parse_args()

    url = args.url
    output_root = Path(args.output_path).expanduser() if args.output_path else Path.home() / 'Downloads'

    print("=" * 50)
    print("抖音视频下载器")
    print("=" * 50)

    try:
        info = fetch_video_info(url, timeout=args.timeout, direct=args.direct)
        video_stream = info.get('video_stream') or {}
        video_url = video_stream.get('url') or info['video_url']
        video_urls = video_stream.get('urls') or [video_url]
        title = info['title']
        author = info['author']
        aweme_id = info['aweme_id']

        print(f"\n视频标题: {title or '(无标题)'}")
        print(f"作者: {author}")
        print(f"视频ID: {aweme_id}")

        if args.metadata_only:
            state_dir = ensure_private_dir(STATE_ROOT / 'single' / aweme_id)
            metadata_path = write_json_private(state_dir / 'metadata.json', build_metadata(info, url))
            print(f"机器元数据: {metadata_path}")
            print("已按 --metadata-only 跳过用户产物")
            return

        width = int(video_stream.get('width') or 0)
        height = int(video_stream.get('height') or 0)
        if is_known_below_1080p(width, height):
            raise ValueError(f"最高兼容码流只有 {width}x{height}，低于默认 1080p 门槛")
        item = info.get('aweme_data', {}) or {}
        video_dir = ensure_private_dir(output_root / readable_video_folder(item))
        output_path = video_dir / VIDEO_FILENAME
        transcript_path = video_dir / TRANSCRIPT_FILENAME

        print("\n开始下载视频...")
        if output_path.is_file() and output_path.stat().st_size > 0:
            require_1080p_file(output_path)
            result_path = str(output_path)
            print(f"已存在，跳过下载: {output_path}")
        else:
            part_path = video_dir / ".视频.mp4.part"
            result_path = download_video(
                video_urls,
                str(part_path),
                referer=url,
                validator=require_1080p_file,
                direct=args.direct,
            )
            os.replace(part_path, output_path)
            output_path.chmod(0o600)
            result_path = str(output_path)

        print("开始生成中文口播稿...")
        transcript_source, _ = create_chinese_transcript(
            item,
            output_path,
            transcript_path,
            aweme_id,
            url,
            direct=args.direct,
        )

        file_size = os.path.getsize(result_path) / 1024 / 1024
        print("\n下载完成")
        print(f"   保存路径: {result_path}")
        print(f"   中文口播稿: {transcript_path}")
        print(f"   口播稿来源: {transcript_source}")
        print(f"   文件大小: {file_size:.2f} MB")

    except Exception as e:
        if "待转写" in str(e):
            print(f"\n视频已保存，中文口播稿待转写: {e}")
            sys.exit(2)
        print(f"\n下载失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
