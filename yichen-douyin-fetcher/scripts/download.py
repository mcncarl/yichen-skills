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
import json
import sys
import os
import re
import subprocess
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional

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


def normalize_url(url: str) -> str:
    """将各种抖音 URL 格式转换为标准的视频详情页 URL"""
    video_id = extract_video_id(url)
    if video_id:
        return f"https://www.douyin.com/video/{video_id}"
    return url


def ensure_playwright_chromium():
    """首次运行时自动安装 Playwright Chromium。"""
    print("检测到 Playwright Chromium 缺失，正在自动安装...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("自动安装 Chromium 失败，请手动运行: python3 -m playwright install chromium") from exc


def get_best_video_url(aweme_data: dict) -> Optional[str]:
    """从 aweme 数据里按优先级提取可下载视频地址。"""
    video = aweme_data.get('video', {}) or {}
    candidates = [
        video.get('play_addr', {}),
        video.get('play_addr_h264', {}),
        video.get('download_addr', {}),
    ]

    for item in candidates:
        url_list = item.get('url_list') or []
        if url_list:
            return url_list[0]
    return None


def fetch_video_info(url: str, timeout: int = 60):
    """
    使用 Playwright 拦截 aweme/detail API 获取视频信息
    返回包含 video_url, title, author 等信息的字典
    """
    try:
        return _fetch_video_info_once(url, timeout=timeout)
    except PlaywrightError as exc:
        if any(hint in str(exc) for hint in MISSING_BROWSER_HINTS):
            ensure_playwright_chromium()
            return _fetch_video_info_once(url, timeout=timeout)
        raise


def _fetch_video_info_once(url: str, timeout: int = 60):
    """单次打开页面并拦截详情接口。"""
    video_url = None
    aweme_data = None
    normalized = normalize_url(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale='zh-CN',
            )
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

            deadline = time.time() + timeout
            while time.time() < deadline and not aweme_data:
                page.wait_for_timeout(1000)
        finally:
            browser.close()

    if not aweme_data:
        raise ValueError("无法获取视频数据，请检查链接是否有效")

    if not video_url:
        video_url = get_best_video_url(aweme_data)

    return {
        'video_url': video_url,
        'title': aweme_data.get('desc', ''),
        'author': aweme_data.get('author', {}).get('nickname', ''),
        'aweme_id': aweme_data.get('aweme_id', ''),
        'aweme_data': aweme_data,
    }


def build_metadata(info: dict, source_url: str) -> dict:
    """生成不包含临时直链的精简元数据。"""
    aweme_data = info.get('aweme_data', {}) or {}
    author = aweme_data.get('author', {}) or {}
    statistics = aweme_data.get('statistics', {}) or {}
    video = aweme_data.get('video', {}) or {}

    return {
        'source_url': source_url,
        'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'aweme_id': info.get('aweme_id') or aweme_data.get('aweme_id', ''),
        'title': info.get('title') or aweme_data.get('desc', ''),
        'author': info.get('author') or author.get('nickname', ''),
        'author_id': author.get('uid', ''),
        'create_time': aweme_data.get('create_time'),
        'duration_ms': video.get('duration'),
        'statistics': statistics,
    }


def write_metadata(info: dict, source_url: str, output_path: str) -> Path:
    metadata_path = Path(f"{output_path}.metadata.json")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(info, source_url)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata_path


def download_video(video_url: str, output_path: str, referer: str = 'https://www.douyin.com/') -> str:
    """下载视频到本地"""
    if not video_url:
        raise ValueError("没有拿到可下载的视频直链")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        'User-Agent': USER_AGENT,
        'Referer': referer,
    }

    response = requests.get(video_url, headers=headers, stream=True, timeout=60)
    response.raise_for_status()

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
                        print(f"下载进度: {percent}% ({downloaded//1024//1024}MB / {total//1024//1024}MB)")
                        next_percent += 10
                else:
                    downloaded_mb = downloaded // 1024 // 1024
                    if downloaded_mb >= next_mb_report:
                        print(f"已下载: {downloaded_mb}MB")
                        next_mb_report += 5

    return str(output)


def main():
    parser = argparse.ArgumentParser(description="抖音视频下载器")
    parser.add_argument("url", help="抖音视频链接")
    parser.add_argument("output_path", nargs="?", help="输出 MP4 路径，默认 ~/Downloads/douyin_<video_id>.mp4")
    parser.add_argument("--metadata-only", action="store_true", help="只抓取并保存元数据，不下载视频")
    parser.add_argument("--timeout", type=int, default=60, help="等待 aweme/detail 响应的秒数，默认 60")
    args = parser.parse_args()

    url = args.url
    output_path = args.output_path

    print("=" * 50)
    print("抖音视频下载器")
    print("=" * 50)

    try:
        info = fetch_video_info(url, timeout=args.timeout)
        video_url = info['video_url']
        title = info['title']
        author = info['author']
        aweme_id = info['aweme_id']

        print(f"\n视频标题: {title or '(无标题)'}")
        print(f"作者: {author}")
        print(f"视频ID: {aweme_id}")

        if not output_path:
            downloads_dir = Path.home() / 'Downloads'
            downloads_dir.mkdir(exist_ok=True)
            output_path = str(downloads_dir / f"douyin_{aweme_id}.mp4")

        metadata_path = write_metadata(info, url, output_path)
        print(f"元数据: {metadata_path}")

        if args.metadata_only:
            print("已按 --metadata-only 跳过视频下载")
            return

        print("\n开始下载视频...")
        result_path = download_video(video_url, output_path)

        file_size = os.path.getsize(result_path) / 1024 / 1024
        print("\n下载完成")
        print(f"   保存路径: {result_path}")
        print(f"   文件大小: {file_size:.2f} MB")

    except Exception as e:
        print(f"\n下载失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
