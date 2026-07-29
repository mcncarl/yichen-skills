#!/usr/bin/env python3
"""扫描抖音博主公开作品，并按需批量下载。"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from artifacts import (
    STATE_ROOT,
    TRANSCRIPT_FILENAME,
    VIDEO_FILENAME,
    ensure_private_dir,
    is_at_least_1080p,
    is_known_below_1080p,
    job_state_dir,
    output_state_key,
    readable_creator_root,
    readable_video_folder,
    require_1080p_file,
    write_json_private,
)
from download import (
    MISSING_BROWSER_HINTS,
    USER_AGENT,
    create_chinese_transcript,
    download_native_transcript,
    download_video,
    ensure_playwright_chromium,
    fetch_video_info,
    get_best_video_stream,
    get_best_video_url,
    launch_compatible_browser,
    sanitize_douyin_page_url,
    validate_douyin_page_url,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_POLICY_PATH = Path.home() / ".config" / "yichen-douyin-fetcher" / "policy.json"


def load_persistent_session_policy() -> Optional[dict]:
    """读取本机私有授权策略；策略文件不存在时保持默认不持久化。"""
    if not DEFAULT_POLICY_PATH.is_file():
        return None
    data = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    if data.get("persistent_login_authorized") is not True:
        return None
    state_value = data.get("storage_state_path")
    if not state_value:
        raise ValueError(f"本机策略缺少 storage_state_path: {DEFAULT_POLICY_PATH}")
    return {
        "storage_state_path": str(Path(state_value).expanduser()),
        "policy_path": str(DEFAULT_POLICY_PATH),
    }


def extract_url(text: str) -> str:
    """从纯 URL 或抖音分享文案中提取第一个链接。"""
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        raise ValueError("未找到有效的抖音链接")
    url = match.group(0).rstrip("，。！？,.;!?)）]")
    return validate_douyin_page_url(url)


def extract_sec_uid(url: str) -> Optional[str]:
    match = re.search(r"/user/([^/?#]+)", url)
    return match.group(1) if match else None


def merge_aweme_page(body: dict, awemes: dict, state: dict) -> None:
    """合并一页作品响应，用 aweme_id 去重并记录分页状态。"""
    for item in body.get("aweme_list") or []:
        aweme_id = str(item.get("aweme_id") or "")
        if aweme_id:
            awemes[aweme_id] = item
    state["responses"] += 1
    state["has_more"] = bool(body["has_more"]) if "has_more" in body else None
    state["max_cursor"] = body.get("max_cursor")


def advance_profile_scroll(page) -> dict:
    """推进主页中面积最大的可滚动容器，而不是不可滚动的 window。"""
    result = page.evaluate(
        """
        () => {
          const candidates = Array.from(document.querySelectorAll('*'))
            .map(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return {el, style, rect};
            })
            .filter(item =>
              item.rect.width > 0 && item.rect.height > 0 &&
              item.el.scrollHeight > item.el.clientHeight + 20 &&
              (item.style.overflowY === 'auto' || item.style.overflowY === 'scroll')
            )
            .sort((a, b) =>
              (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height)
            );

          const target = candidates[0]?.el;
          if (!target) {
            window.scrollBy(0, Math.max(500, window.innerHeight * 0.9));
            return {kind: 'window', scrollTop: window.scrollY};
          }

          const before = target.scrollTop;
          const step = Math.max(500, target.clientHeight * 0.9);
          target.scrollBy(0, step);
          target.dispatchEvent(new Event('scroll', {bubbles: true}));
          const rect = target.getBoundingClientRect();
          return {
            kind: 'container',
            before,
            scrollTop: target.scrollTop,
            scrollHeight: target.scrollHeight,
            clientHeight: target.clientHeight,
            centerX: rect.x + rect.width / 2,
            centerY: rect.y + rect.height / 2,
          };
        }
        """
    )
    if result.get("kind") == "container":
        page.mouse.move(result["centerX"], result["centerY"])
        page.mouse.wheel(0, max(500, int(result["clientHeight"] * 0.9)))
    return result


def resolve_author(
    source: str,
    timeout: int,
    headed: bool = False,
    storage_state=None,
) -> dict:
    """从主页链接或任意一条作品解析博主身份。"""
    url = extract_url(source)
    sec_uid = extract_sec_uid(url)
    if sec_uid:
        return {
            "source_url": url,
            "profile_url": f"https://www.douyin.com/user/{sec_uid}",
            "sec_uid": sec_uid,
            "uid": "",
            "nickname": "",
            "session_state": None,
        }

    detail_timeout = timeout if headed else min(timeout, 60)
    if headed:
        print("可见模式已启用。如当前页面要求登录，请登录并刷新当前页面。")
    info = fetch_video_info(
        url,
        timeout=detail_timeout,
        headed=headed,
        storage_state=storage_state,
        capture_storage_state=headed,
    )
    author = info.get("aweme_data", {}).get("author", {}) or {}
    sec_uid = author.get("sec_uid", "")
    if not sec_uid:
        raise ValueError("视频详情中缺少博主 sec_uid，无法进入作品主页")

    return {
        "source_url": url,
        "profile_url": f"https://www.douyin.com/user/{sec_uid}",
        "sec_uid": sec_uid,
        "uid": author.get("uid", ""),
        "nickname": author.get("nickname", ""),
        "session_state": info.get("storage_state"),
    }


def scan_author_awemes(
    profile_url: str,
    timeout: int,
    limit: Optional[int],
    headed: bool = False,
    login_wait: int = 180,
    storage_state=None,
    save_storage_state: Optional[str] = None,
    overwrite_storage_state: bool = False,
    target_ids: Optional[set[str]] = None,
) -> dict:
    """打开博主主页，通过滚动拦截 aweme/post 分页响应。"""
    validate_douyin_page_url(profile_url)
    try:
        return _scan_author_awemes_once(
            profile_url,
            timeout,
            limit,
            headed,
            login_wait,
            storage_state,
            save_storage_state,
            overwrite_storage_state,
            target_ids,
        )
    except PlaywrightError as exc:
        if any(hint in str(exc) for hint in MISSING_BROWSER_HINTS):
            ensure_playwright_chromium()
            return _scan_author_awemes_once(
                profile_url,
                timeout,
                limit,
                headed,
                login_wait,
                storage_state,
                save_storage_state,
                overwrite_storage_state,
                target_ids,
            )
        raise


def _scan_author_awemes_once(
    profile_url: str,
    timeout: int,
    limit: Optional[int],
    headed: bool,
    login_wait: int,
    storage_state,
    save_storage_state: Optional[str],
    overwrite_storage_state: bool,
    target_ids: Optional[set[str]],
) -> dict:
    awemes = {}
    captured_storage_state = None
    state = {
        "responses": 0,
        "empty_responses": 0,
        "has_more": None,
        "max_cursor": None,
    }

    context_options = {"user_agent": USER_AGENT, "locale": "zh-CN"}
    if isinstance(storage_state, (str, Path)):
        storage_path = Path(storage_state).expanduser()
        if not storage_path.is_file():
            raise ValueError(f"登录态文件不存在: {storage_path}")
        context_options["storage_state"] = str(storage_path)
    elif storage_state:
        context_options["storage_state"] = storage_state

    with sync_playwright() as playwright:
        browser = launch_compatible_browser(playwright, headless=not headed)
        try:
            context = browser.new_context(**context_options)
            page = context.new_page()

            def handle_response(response):
                if "aweme/post" not in response.url or "douyin.com" not in response.url:
                    return
                try:
                    body = response.json()
                except Exception:
                    state["empty_responses"] += 1
                    return

                merge_aweme_page(body, awemes, state)

            page.on("response", handle_response)
            print(f"正在扫描主页: {profile_url}")
            try:
                page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                print(f"页面加载提示: {exc}")
            if page.url.startswith(("http://", "https://")):
                validate_douyin_page_url(page.url)

            deadline = time.time() + timeout
            idle_scrolls = 0
            previous_count = 0
            login_attempted = False

            while time.time() < deadline:
                if target_ids and target_ids.issubset(awemes):
                    stopped_reason = "targets"
                    break
                if limit and len(awemes) >= limit:
                    stopped_reason = "limit"
                    break
                if state["responses"] and state["has_more"] is False:
                    stopped_reason = "complete"
                    break

                try:
                    advance_profile_scroll(page)
                except PlaywrightError as exc:
                    if "Execution context was destroyed" in str(exc):
                        page.wait_for_timeout(1000)
                        continue
                    raise
                page.wait_for_timeout(1500)

                current_count = len(awemes)
                if current_count == previous_count:
                    idle_scrolls += 1
                else:
                    print(f"已发现 {current_count} 条公开作品")
                    idle_scrolls = 0
                    previous_count = current_count

                if idle_scrolls >= 8:
                    if headed and login_wait > 0 and not login_attempted:
                        login_attempted = True
                        count_before_login = len(awemes)
                        responses_before_login = state["responses"]
                        print(
                            f"当前取得 {count_before_login} 条作品。"
                            "请在打开的浏览器中登录抖音并刷新博主主页；"
                            f"最多等待 {login_wait} 秒。"
                        )
                        login_deadline = time.time() + login_wait
                        while time.time() < login_deadline:
                            page.wait_for_timeout(1000)
                            if (
                                len(awemes) > count_before_login
                                or state["responses"] > responses_before_login
                                or state["has_more"] is False
                            ):
                                break
                        if (
                            len(awemes) == count_before_login
                            and state["responses"] == responses_before_login
                            and state["has_more"] is not False
                        ):
                            stopped_reason = "login-timeout"
                            break
                        print(f"登录后已发现 {len(awemes)} 条公开作品，继续扫描")
                        deadline = time.time() + timeout
                        idle_scrolls = 0
                        previous_count = len(awemes)
                        continue
                    stopped_reason = "idle"
                    break
            else:
                stopped_reason = "timeout"

            if headed and awemes:
                captured_storage_state = context.storage_state(indexed_db=True)

            if awemes and save_storage_state:
                state_path = Path(save_storage_state).expanduser()
                skill_root = Path(__file__).resolve().parent.parent
                resolved_state_path = state_path.resolve()
                if resolved_state_path == skill_root or skill_root in resolved_state_path.parents:
                    raise ValueError("登录态不得保存到 Skill 目录，请选择私有数据目录")
                if state_path.exists() and not overwrite_storage_state:
                    raise ValueError(f"登录态文件已存在，拒绝覆盖: {state_path}")
                state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(state_path), indexed_db=True)
                state_path.chmod(0o600)
                print(f"已保存登录态: {state_path}")
        finally:
            browser.close()

    if not awemes:
        detail = "接口返回了空正文" if state["empty_responses"] else "未触发作品接口"
        raise ValueError(
            f"未获取公开作品列表（{detail}）。请改用 --headed 进行一次性登录，"
            "或在明确授权后加载 --storage-state 登录态文件"
        )

    items = sorted(
        awemes.values(),
        key=lambda item: int(item.get("create_time") or 0),
        reverse=True,
    )
    if limit:
        items = items[:limit]

    return {
        "awemes": items,
        "has_more": state["has_more"],
        "max_cursor": state["max_cursor"],
        "responses": state["responses"],
        "empty_responses": state["empty_responses"],
        "stopped_reason": stopped_reason,
        "session_state": captured_storage_state,
    }


def compact_aweme(item: dict) -> dict:
    author = item.get("author", {}) or {}
    video = item.get("video", {}) or {}
    stream = get_best_video_stream(item) or {}
    return {
        "aweme_id": str(item.get("aweme_id") or ""),
        "source_url": f"https://www.douyin.com/video/{item.get('aweme_id', '')}",
        "title": item.get("desc", ""),
        "author": author.get("nickname", ""),
        "author_id": author.get("uid", ""),
        "create_time": item.get("create_time"),
        "duration_ms": video.get("duration"),
        "selected_width": stream.get("width"),
        "selected_height": stream.get("height"),
        "selected_bit_rate": stream.get("bit_rate"),
        "estimated_bytes": stream.get("data_size"),
        "statistics": item.get("statistics", {}) or {},
    }


def scan_result_is_partial(stopped_reason: str) -> bool:
    """显式条数限制是预期停止；超时、空转或登录超时属于部分枚举。"""
    return stopped_reason not in {"complete", "limit", "targets"}


def default_output_dir(author: dict, awemes: list[dict]) -> Path:
    first_author = (awemes[0].get("author", {}) or {}) if awemes else {}
    nickname = author.get("nickname") or first_author.get("nickname") or "author"
    uid = author.get("uid") or first_author.get("uid") or author.get("sec_uid", "")[-10:]
    return Path.home() / "Downloads" / readable_creator_root(nickname, uid)


def resolve_output_dir(requested: Optional[str], author: dict, awemes: list[dict]) -> Path:
    creator_dir = default_output_dir(author, awemes)
    if not requested:
        return creator_dir
    root = Path(requested).expanduser()
    if root.name.startswith("抖音_博主_"):
        return root
    return root / creator_dir.name


def write_manifest(author: dict, scan: dict, state_dir: Path) -> Path:
    videos = [compact_aweme(item) for item in scan["awemes"]]
    manifest = {
        "source_url": sanitize_douyin_page_url(author["source_url"]),
        "profile_url": sanitize_douyin_page_url(author["profile_url"]),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "author": author.get("nickname") or videos[0].get("author", ""),
        "author_id": author.get("uid") or videos[0].get("author_id", ""),
        "public_video_count": len(videos),
        "scan_complete": scan["stopped_reason"] == "complete",
        "stopped_reason": scan["stopped_reason"],
        "has_more": scan.get("has_more"),
        "page_responses": scan.get("responses", 0),
        "empty_page_responses": scan.get("empty_responses", 0),
        "max_cursor": scan.get("max_cursor"),
        "videos": videos,
    }
    return write_json_private(ensure_private_dir(state_dir) / "抓取清单.json", manifest)


def load_resume_manifest(output_dir: Path) -> tuple[Path, dict, list[dict]]:
    """按用户输出目录定位并严格读取唯一的私有抓取清单。"""
    jobs_root = STATE_ROOT / "jobs"
    output_key = output_state_key(output_dir)
    matches = sorted(jobs_root.glob(f"*_{output_key}/抓取清单.json")) if jobs_root.is_dir() else []
    if not matches:
        raise RuntimeError(f"没有找到该输出目录对应的私有抓取清单: {output_dir}")
    if len(matches) > 1:
        raise RuntimeError(f"该输出目录匹配到多个抓取清单，拒绝猜测: {output_dir}")
    manifest_path = matches[0]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"私有抓取清单损坏，拒绝覆盖: {manifest_path}") from exc
    videos = manifest.get("videos") if isinstance(manifest, dict) else None
    if not isinstance(videos, list) or not videos:
        raise RuntimeError(f"私有抓取清单没有可续跑的视频: {manifest_path}")

    items = []
    for video in videos:
        aweme_id = str(video.get("aweme_id") or "") if isinstance(video, dict) else ""
        if not aweme_id:
            raise RuntimeError(f"私有抓取清单包含缺少 aweme_id 的记录: {manifest_path}")
        items.append(
            {
                "aweme_id": aweme_id,
                "create_time": video.get("create_time"),
                "desc": video.get("title", ""),
                "author": {
                    "nickname": video.get("author") or manifest.get("author", ""),
                    "uid": video.get("author_id") or manifest.get("author_id", ""),
                },
                "video": {},
            }
        )
    return manifest_path, manifest, items


def order_confirmed_items(confirmed: list[dict], discovered: list[dict]) -> list[dict]:
    discovered_by_id = {
        str(item.get("aweme_id") or ""): item
        for item in discovered
        if str(item.get("aweme_id") or "")
    }
    confirmed_ids = [str(item.get("aweme_id") or "") for item in confirmed]
    missing = [aweme_id for aweme_id in confirmed_ids if aweme_id not in discovered_by_id]
    if missing:
        raise RuntimeError(f"重新获取临时媒体数据时缺少 {len(missing)} 条确认作品")
    ordered = []
    for confirmed_item, aweme_id in zip(confirmed, confirmed_ids, strict=True):
        hydrated = dict(discovered_by_id[aweme_id])
        hydrated["desc"] = confirmed_item.get("desc") or hydrated.get("desc", "")
        hydrated["create_time"] = (
            confirmed_item.get("create_time") or hydrated.get("create_time")
        )
        ordered.append(hydrated)
    return ordered


def video_output_path(output_dir: Path, item: dict) -> Path:
    return output_dir / readable_video_folder(item) / VIDEO_FILENAME


def download_batch(
    items: list[dict],
    output_dir: Path,
    profile_url: str,
    delay: float,
    asr_script: Optional[Path] = None,
    storage_state=None,
) -> dict:
    completed = 0
    skipped = 0
    failed = []
    pending_transcript = []

    for index, item in enumerate(items, start=1):
        aweme_id = str(item.get("aweme_id") or "")
        source_url = f"https://www.douyin.com/video/{aweme_id}"
        output = video_output_path(output_dir, item)
        video_dir = output.parent
        transcript_path = video_dir / TRANSCRIPT_FILENAME
        print(f"\n[{index}/{len(items)}] {item.get('desc') or aweme_id}")

        stream = get_best_video_stream(item) or {}
        info = {
            "video_url": stream.get("url") or get_best_video_url(item),
            "video_stream": stream,
            "title": item.get("desc", ""),
            "author": (item.get("author", {}) or {}).get("nickname", ""),
            "aweme_id": aweme_id,
            "aweme_data": item,
        }

        part = video_dir / ".视频.mp4.part"
        detail_fetched = False
        try:
            if (
                output.is_file()
                and output.stat().st_size > 0
                and transcript_path.is_file()
                and transcript_path.stat().st_size > 0
            ):
                require_1080p_file(output)
                print(f"视频和中文口播稿已存在，跳过: {video_dir}")
                skipped += 1
                continue

            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if not info["video_url"] or not is_at_least_1080p(width, height):
                info = fetch_video_info(source_url, timeout=60, storage_state=storage_state)
                detail_fetched = True
                stream = info.get("video_stream") or {}
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
            if is_known_below_1080p(width, height):
                raise ValueError(f"最高兼容码流只有 {width}x{height}，低于默认 1080p 门槛")

            ensure_private_dir(video_dir)
            if output.is_file() and output.stat().st_size > 0:
                require_1080p_file(output)
                print(f"视频已存在，继续生成口播稿: {output}")
            else:
                video_urls = stream.get("urls") or [stream.get("url") or info["video_url"]]
                download_video(
                    video_urls,
                    str(part),
                    referer=profile_url,
                    validator=require_1080p_file,
                )
                part.replace(output)
                output.chmod(0o600)

            transcript_aweme = info.get("aweme_data") or item
            native_transcript = None
            if not transcript_path.is_file() or transcript_path.stat().st_size == 0:
                native_transcript = download_native_transcript(
                    transcript_aweme,
                    transcript_path,
                    aweme_id,
                    source_url,
                )
            if not native_transcript and not detail_fetched and asr_script is None:
                try:
                    detail_info = fetch_video_info(
                        source_url,
                        timeout=20,
                        storage_state=storage_state,
                    )
                    transcript_aweme = detail_info.get("aweme_data") or transcript_aweme
                except Exception:
                    print("未能补取当前作品的详情字幕，将按 ASR 回退策略处理")

            if native_transcript:
                transcript_source = "平台字幕"
            else:
                transcript_source, _ = create_chinese_transcript(
                    transcript_aweme,
                    output,
                    transcript_path,
                    aweme_id,
                    source_url,
                    asr_script,
                )
            completed += 1
            print(f"已保存: {video_dir}（口播稿来源: {transcript_source}）")
        except Exception as exc:
            part.unlink(missing_ok=True)
            if video_dir.is_dir() and not any(video_dir.iterdir()):
                video_dir.rmdir()
            entry = {"aweme_id": aweme_id, "error": str(exc)}
            if "待转写" in str(exc):
                pending_transcript.append(entry)
                print(f"视频已保存，中文口播稿待转写: {exc}")
            else:
                failed.append(entry)
                print(f"处理失败: {exc}")

        if delay > 0 and index < len(items):
            time.sleep(delay)

    return {
        "completed": completed,
        "skipped": skipped,
        "pending_transcript": pending_transcript,
        "failed": failed,
    }


def run_batch_download(
    items: list[dict],
    output_dir: Path,
    profile_url: str,
    delay: float,
    state_dir: Path,
    storage_state,
    scan_partial: bool,
) -> int:
    ensure_private_dir(output_dir)
    result = download_batch(
        items,
        output_dir,
        profile_url,
        delay,
        storage_state=storage_state,
    )
    result_path = write_json_private(state_dir / "抓取状态.json", result)
    print("\n批量下载结束")
    print(
        f"成功: {result['completed']}，跳过: {result['skipped']}，"
        f"待转写: {len(result['pending_transcript'])}，失败: {len(result['failed'])}"
    )
    print(f"结果记录: {result_path}")
    return 2 if result["failed"] or result["pending_transcript"] or scan_partial else 0


def main():
    parser = argparse.ArgumentParser(description="扫描抖音博主公开作品并按需批量下载")
    parser.add_argument("source", help="博主主页、任意一条作品 URL，或包含 URL 的分享文案")
    parser.add_argument(
        "--output-dir",
        help="保存根目录；正常扫描时在其下创建抖音_博主_<昵称>_[短UID]，续跑时传入该创作者目录",
    )
    parser.add_argument("--download", action="store_true", help="扫描后下载 1080p+ 视频并生成中文口播稿")
    parser.add_argument("--limit", type=int, help="最多扫描/下载多少条，用于小规模验证")
    parser.add_argument("--delay", type=float, default=2.0, help="相邻下载间隔秒数，默认 2")
    parser.add_argument("--timeout", type=int, default=120, help="主页扫描最长秒数，默认 120")
    parser.add_argument("--headed", action="store_true", help="打开可见浏览器，供匿名扫描失败时一次性登录")
    parser.add_argument("--login-wait", type=int, default=180, help="可见模式等待人工登录的秒数，默认 180")
    parser.add_argument("--storage-state", help="加载 Playwright 登录态 JSON；文件包含敏感凭据")
    parser.add_argument("--save-storage-state", help="保存登录态 JSON；执行前必须取得用户明确授权")
    parser.add_argument("--no-persistent-session", action="store_true", help="本次忽略本机持久登录授权策略")
    parser.add_argument(
        "--resume-only",
        action="store_true",
        help="固定已确认清单的作品 ID，仅补取这些作品的临时媒体数据；必须同时指定 --download 和创作者输出目录",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须大于 0")
    if args.delay < 0:
        parser.error("--delay 不能小于 0")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.login_wait < 0:
        parser.error("--login-wait 不能小于 0")
    if args.save_storage_state and not args.headed:
        parser.error("--save-storage-state 必须与 --headed 一起使用")
    if args.resume_only and (not args.download or not args.output_dir):
        parser.error("--resume-only 必须同时指定 --download 和 --output-dir")

    try:
        policy = None if args.no_persistent_session else load_persistent_session_policy()
        policy_state = policy["storage_state_path"] if policy else None
        explicit_state = str(Path(args.storage_state).expanduser()) if args.storage_state else None
        storage_state = explicit_state
        if not storage_state and policy_state and Path(policy_state).is_file():
            storage_state = policy_state
            print(f"已按本机策略加载可复用登录态: {policy_state}")

        save_storage_state = args.save_storage_state
        overwrite_storage_state = False
        if policy_state and args.headed and not save_storage_state:
            save_storage_state = policy_state
            overwrite_storage_state = True
            print(f"本次登录成功后将按本机策略更新登录态: {policy_state}")
        elif save_storage_state and policy_state:
            overwrite_storage_state = (
                Path(save_storage_state).expanduser().resolve() == Path(policy_state).resolve()
            )

        if args.resume_only:
            output_dir = Path(args.output_dir).expanduser()
            manifest_path, manifest, items = load_resume_manifest(output_dir)
            profile_url = str(manifest.get("profile_url") or "")
            validate_douyin_page_url(profile_url)
            stopped_reason = str(manifest.get("stopped_reason") or "unknown")
            scan_partial = scan_result_is_partial(stopped_reason)
            print(f"已加载确认清单: {manifest_path}")
            print(f"用户输出目录: {output_dir}")
            print(f"本次固定处理: {len(items)} 条")
            if scan_partial:
                print("警告: 原清单属于部分枚举，本次只处理清单中已有作品")
            target_ids = {str(item["aweme_id"]) for item in items}
            hydrated_scan = scan_author_awemes(
                profile_url,
                args.timeout,
                None,
                headed=args.headed,
                login_wait=args.login_wait,
                storage_state=storage_state,
                save_storage_state=save_storage_state,
                overwrite_storage_state=overwrite_storage_state,
                target_ids=target_ids,
            )
            items = order_confirmed_items(items, hydrated_scan["awemes"])
            if hydrated_scan.get("session_state"):
                storage_state = hydrated_scan["session_state"]
            elif save_storage_state and Path(save_storage_state).expanduser().is_file():
                storage_state = str(Path(save_storage_state).expanduser())
            exit_code = run_batch_download(
                items,
                output_dir,
                profile_url,
                args.delay,
                manifest_path.parent,
                storage_state,
                scan_partial,
            )
            if exit_code:
                sys.exit(exit_code)
            return

        resolve_timeout = max(args.timeout, args.login_wait) if args.headed else args.timeout
        author = resolve_author(
            args.source,
            resolve_timeout,
            headed=args.headed,
            storage_state=storage_state,
        )
        print(f"博主: {author.get('nickname') or '(从主页作品中识别)'}")
        effective_storage_state = storage_state or author.get("session_state")
        scan = scan_author_awemes(
            author["profile_url"],
            args.timeout,
            args.limit,
            headed=args.headed,
            login_wait=args.login_wait,
            storage_state=effective_storage_state,
            save_storage_state=save_storage_state,
            overwrite_storage_state=overwrite_storage_state,
        )
        if scan.get("session_state"):
            effective_storage_state = scan["session_state"]
        elif save_storage_state and Path(save_storage_state).expanduser().is_file():
            effective_storage_state = str(Path(save_storage_state).expanduser())
        items = scan["awemes"]
        output_dir = resolve_output_dir(args.output_dir, author, items)
        first_author = (items[0].get("author", {}) or {}) if items else {}
        author_id = author.get("uid") or first_author.get("uid") or author.get("sec_uid", "unknown")
        state_dir = job_state_dir(str(author_id), output_dir)
        manifest_path = write_manifest(author, scan, state_dir)

        print(f"\n用户输出目录: {output_dir}")
        print(f"机器清单: {manifest_path}")
        print(f"本次记录: {len(items)} 条")
        print(f"扫描状态: {scan['stopped_reason']}")
        scan_partial = scan_result_is_partial(scan["stopped_reason"])
        if scan_partial:
            print("警告: 主页枚举未完整结束，本次结果只能视为部分清单")

        if not args.download:
            print("未指定 --download，不生成视频和中文口播稿")
            if scan_partial:
                sys.exit(2)
            return

        exit_code = run_batch_download(
            items,
            output_dir,
            author["profile_url"],
            args.delay,
            state_dir,
            effective_storage_state,
            scan_partial,
        )
        if exit_code:
            sys.exit(exit_code)
    except Exception as exc:
        print(f"\n执行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
