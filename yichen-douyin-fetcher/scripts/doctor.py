#!/usr/bin/env python3
"""Run a side-effect-free local dependency check for the Douyin Skill."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import urllib.request
from pathlib import Path

MINIMUM_PYTHON = (3, 10)


def main() -> int:
    failures: list[str] = []

    if sys.version_info < MINIMUM_PYTHON:
        failures.append(
            f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+（当前 {sys.version.split()[0]}）"
        )
    else:
        print(f"[通过] Python {sys.version.split()[0]}")

    for module in ("requests", "playwright"):
        if importlib.util.find_spec(module) is None:
            failures.append(f"Python 依赖 {module}")
        else:
            print(f"[通过] Python 依赖 {module}")

    for command in ("ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        if executable is None:
            failures.append(f"系统命令 {command}")
        else:
            print(f"[通过] {command}: {executable}")

    if urllib.request.getproxies():
        print(
            "[提示] 检测到系统代理；抓取默认尊重该代理。"
            "若抖音页面空白，请先取得用户许可，再用 --direct 显式直连。"
        )

    if importlib.util.find_spec("playwright") is not None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path)
                try:
                    if not executable.is_file():
                        raise PlaywrightError(f"Chromium 不存在: {executable}")
                    browser = playwright.chromium.launch(headless=True)
                    browser_runtime = "Playwright Chromium"
                except PlaywrightError as chromium_error:
                    try:
                        browser = playwright.chromium.launch(channel="chrome", headless=True)
                        browser_runtime = "Google Chrome"
                    except PlaywrightError as chrome_error:
                        raise chromium_error from chrome_error
                browser.close()
            print(f"[通过] {browser_runtime} 可由 Playwright 启动")
        except Exception as exc:  # Playwright exposes several runtime-specific errors.
            failures.append(f"Playwright Chromium（{exc}）")

    if not failures:
        print("自检通过：可以开始抓取。")
        return 0

    print("自检未通过：")
    for failure in failures:
        print(f"- 缺少或不可用：{failure}")
    print("安装 Python 依赖：python3 -m pip install -r <SKILL_DIR>/requirements.txt")
    print("安装 Chromium：python3 -m playwright install chromium")
    print("ffmpeg/ffprobe 请使用当前操作系统的软件包管理器安装。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
