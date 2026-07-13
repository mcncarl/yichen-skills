#!/usr/bin/env python3
"""Upload a Markdown file to X Articles as a draft.

This intentionally creates a draft only and never clicks the final publish button.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html as htmlmod
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path


DEFAULT_PARSE_SCRIPTS = [
    Path(__file__).resolve().parent / "parse_markdown.py",
]


def clean_anchor(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)、]\s*", "", text)
    return text.strip().strip("|").strip()


def inspect_leading_cover(markdown_file: Path) -> dict:
    """Check whether the first meaningful Markdown line is an image."""
    lines = markdown_file.read_text().splitlines()
    index = 0

    while index < len(lines) and not lines[index].strip():
        index += 1

    if index < len(lines) and lines[index].strip() == "---":
        index += 1
        while index < len(lines) and lines[index].strip() != "---":
            index += 1
        if index < len(lines):
            index += 1

    while index < len(lines) and not lines[index].strip():
        index += 1

    first_line = lines[index].strip() if index < len(lines) else ""
    starts_with_image = bool(re.match(r"^!\[[^\]]*\]\(.+\)", first_line))
    return {
        "starts_with_image": starts_with_image,
        "first_content_line": index + 1 if first_line else None,
        "first_content_preview": first_line[:160],
    }


def parse_markdown(markdown_file: Path, parse_script: Path | None) -> dict:
    script = parse_script
    if script is None:
        script = next((candidate for candidate in DEFAULT_PARSE_SCRIPTS if candidate.exists()), None)
    if script is None or not script.exists():
        raise FileNotFoundError("No parse_markdown.py found. Pass --parse-script explicitly.")

    env = os.environ.copy()
    env["MARKDOWN_FILE"] = str(markdown_file)
    result = subprocess.run(
        [sys.executable, str(script)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    data = json.loads(result.stdout)
    required = ["title", "html", "cover_image", "content_images", "expected_image_count"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Parser output missing keys: {missing}")
    return data


def find_line_anchor(markdown_lines: list[str], image_path: str) -> tuple[str, int | None]:
    base = Path(image_path).name
    found = None
    for idx, line in enumerate(markdown_lines):
        if base in urllib.parse.unquote(line):
            found = idx
            break
    if found is None:
        return "", None
    cursor = found - 1
    while cursor >= 0:
        stripped = markdown_lines[cursor].strip()
        if stripped and not stripped.startswith("!["):
            if stripped == "---":
                cursor -= 1
                continue
            return clean_anchor(stripped), found + 1
        cursor -= 1
    return "", found + 1


def build_content_images(data: dict, markdown_file: Path, include_cover_as_body: bool = False) -> list[dict]:
    lines = markdown_file.read_text().splitlines()
    images = list(data["content_images"])
    if include_cover_as_body and data.get("cover_image"):
        images.insert(
            0,
            {
                "path": data["cover_image"],
                "original_path": data["cover_image"],
                "exists": Path(data["cover_image"]).exists(),
                "alt": "",
                "block_index": 0,
                "after_text": "",
                "text_before": "",
                "text_after": "",
                "block_type": "paragraph",
            },
        )

    items = []
    for index, image in enumerate(images, 1):
        primary, line = find_line_anchor(lines, image["path"])
        candidates = []
        if primary:
            candidates.append(primary)
        for key in ("text_before", "after_text"):
            for part in (image.get(key) or "").split("\n"):
                candidate = clean_anchor(part)
                if candidate and candidate != "-" and candidate not in candidates:
                    candidates.append(candidate)
        items.append(
            {
                **image,
                "index": index,
                "line": line,
                "expected_anchor": primary or (candidates[0] if candidates else ""),
                "candidates": candidates,
            }
        )
    return items


def plain_text_from_html(rich_html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", rich_html)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text)
    text = htmlmod.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_cookies(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    return raw["cookies"] if isinstance(raw, dict) and "cookies" in raw else raw


async def run_upload(args: argparse.Namespace, data: dict, content_images: list[dict]) -> dict:
    from playwright.async_api import async_playwright

    rich_html = data["html"]
    plain = plain_text_from_html(rich_html)
    cookies = load_cookies(Path(args.cookies_json))
    upload_cover = bool(data.get("cover_image")) and not args.allow_no_cover

    async def count_media(page):
        return await page.evaluate(
            r"""() => [...document.images]
              .map(img=>({src:img.src,x:img.getBoundingClientRect().x,y:img.getBoundingClientRect().y,w:img.getBoundingClientRect().width,h:img.getBoundingClientRect().height}))
              .filter(i=>i.x>700 && i.w>80 && !i.src.includes('profile_images') && !i.src.includes('/emoji/')).length"""
        )

    async def media_items(page):
        return await page.evaluate(
            r"""() => [...document.images]
              .map(img=>({src:img.src,x:img.getBoundingClientRect().x,y:img.getBoundingClientRect().y,w:img.getBoundingClientRect().width,h:img.getBoundingClientRect().height}))
              .filter(i=>i.x>700 && i.w>80 && !i.src.includes('profile_images') && !i.src.includes('/emoji/'))"""
        )

    async def click_apply_if_present(page, timeout_s=25):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            locator = page.locator('[data-testid="applyButton"]')
            try:
                if await locator.count():
                    await locator.last.click(timeout=2500)
                    await page.wait_for_timeout(4500)
                    return True
            except Exception:
                pass
            await page.wait_for_timeout(700)
        return False

    async def find_target(page, candidates):
        return await page.evaluate(
            r"""({candidates}) => {
              function norm(s){
                return (s||'')
                  .replace(/\u00a0/g,' ')
                  .replace(/^#+\s*/,'')
                  .replace(/^[-*+]\s+/,'')
                  .replace(/^\d+[.)、]\s*/,'')
                  .replace(/\s+/g,' ')
                  .split('|').join('')
                  .split('`').join('')
                  .trim();
              }
              const ordered=[];
              for (const raw of candidates || []) {
                const parts=String(raw).split(/\n+/).map(x=>norm(x)).filter(x=>x.length>1 && x !== '-');
                const full=norm(raw);
                const all=[];
                if (full) all.push(full);
                for (const p of parts) all.push(p);
                for (const p of all) if (p && !ordered.includes(p)) ordered.push(p);
              }
              const blocks=[...document.querySelectorAll('[data-testid="composer"] .public-DraftStyleDefault-block')];
              let chosen=null;
              for (const c of ordered) {
                let best=null;
                for (const [bi,b] of blocks.entries()) {
                  const bt=norm(b.innerText);
                  if (!bt) continue;
                  let score=0;
                  if (bt === c) score=10000;
                  else if (c.length >= 8 && bt.includes(c)) score=8000;
                  else if (bt.length >= 8 && c.includes(bt)) score=5000;
                  else if (c.length >= 16 && bt.includes(c.slice(0, Math.min(42,c.length)))) score=3000;
                  if (score && (!best || score>best.score || (score===best.score && bt.length>best.blockText.length))) {
                    best={node:b, score, bi, blockText:bt, candidate:c};
                  }
                }
                if (best) { chosen=best; break; }
              }
              if (!chosen) return null;
              const n=chosen.node;
              n.scrollIntoView({block:'center'});
              function lastTextNode(node){
                const walker=document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                let cur,last=null;
                while(cur=walker.nextNode()) if(cur.nodeValue && cur.nodeValue.trim()) last=cur;
                return last;
              }
              const t=lastTextNode(n);
              let x,y;
              if (t && t.nodeValue.length) {
                const range=document.createRange();
                range.setStart(t, Math.max(0,t.nodeValue.length-1));
                range.setEnd(t, t.nodeValue.length);
                const r=range.getBoundingClientRect();
                x=Math.min(Math.max(r.right+3, 720), 1360);
                y=Math.min(Math.max(r.top+r.height/2, 115), 1040);
              } else {
                const r=n.getBoundingClientRect();
                x=Math.min(r.right-8,1360);
                y=Math.min(Math.max(r.top+r.height/2,115),1040);
              }
              return {x,y,blockText:chosen.blockText,candidate:chosen.candidate,score:chosen.score,blockIndex:chosen.bi};
            }""",
            {"candidates": candidates},
        )

    async def paste_image_at_current_selection(page, image_path):
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        if mime == "image/jpg":
            mime = "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode()
        return await page.evaluate(
            r"""async ({encoded,mime,name}) => {
              const editor=document.querySelector('[data-testid="composer"]');
              editor?.focus();
              const bytes=Uint8Array.from(atob(encoded), c=>c.charCodeAt(0));
              const file=new File([bytes], name, {type:mime});
              const dt=new DataTransfer();
              dt.items.add(file);
              editor.dispatchEvent(new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:dt}));
              await new Promise(r=>setTimeout(r,3000));
              return {allImages:document.images.length};
            }""",
            {"encoded": encoded, "mime": mime, "name": path.name},
        )

    async def wait_media_increment(page, before, timeout_s=75):
        deadline = time.time() + timeout_s
        last = before
        while time.time() < deadline:
            await page.wait_for_timeout(2500)
            last = await count_media(page)
            if last >= before + 1:
                return last
        return last

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)
        context = await browser.new_context(viewport={"width": 1440, "height": 1200}, locale="zh-CN")
        await context.add_cookies(cookies)
        page = await context.new_page()
        page.set_default_timeout(70000)

        print("[1/5] create fresh draft")
        await page.goto("https://x.com/compose/articles", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        if "/login" in page.url:
            raise RuntimeError("X login is stale; export cookies again.")
        await page.locator('button[aria-label="create"]').first.click()
        for _ in range(15):
            await page.wait_for_timeout(2500)
            if "/compose/articles/edit/" in page.url:
                break
        if "/compose/articles/edit/" not in page.url:
            raise RuntimeError(f"Did not enter edit page: {page.url}")
        draft_url = page.url
        Path(args.url_output).write_text(draft_url)
        print("draft_url=" + draft_url)

        print("[2/5] upload cover")
        await page.wait_for_selector('textarea[placeholder="添加标题"]', timeout=70000)
        if upload_cover:
            await page.locator('input[type="file"][accept*="image"]').first.set_input_files(data["cover_image"])
            await page.wait_for_timeout(3000)
            await click_apply_if_present(page, timeout_s=35)
            await page.wait_for_timeout(8000)
            if await count_media(page) < 1:
                raise RuntimeError("Cover upload was not detected.")
        else:
            print("cover=skipped (--allow-no-cover)")

        print("[3/5] fill title and body")
        await page.locator('textarea[placeholder="添加标题"]').first.fill(args.title or data["title"])
        body_state = await page.evaluate(
            r"""async ({richHtml, plain}) => {
              const editor=document.querySelector('[data-testid="composer"]');
              editor.focus();
              const dt=new DataTransfer();
              dt.setData('text/html', richHtml);
              dt.setData('text/plain', plain);
              editor.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));
              await new Promise(r=>setTimeout(r,5000));
              const text=editor.innerText || '';
              return {len:text.length, hasEnd:text.includes('最后，祝你使用的愉快'), marker:text.includes('MPH_MARKER')};
            }""",
            {"richHtml": rich_html, "plain": plain},
        )
        print("body=" + json.dumps(body_state, ensure_ascii=False))
        if body_state["len"] < 1000 or body_state["marker"]:
            raise RuntimeError("Body paste verification failed.")
        await page.wait_for_timeout(8000)

        print("[4/5] insert body images")
        inserted = []
        for item in sorted(content_images, key=lambda value: value["index"], reverse=True):
            before = await count_media(page)
            target = await find_target(page, item["candidates"])
            if not target:
                raise RuntimeError(f"Image {item['index']} anchor not found: {item['candidates'][:3]}")
            print(f"image {item['index']:02d}/{len(content_images)} anchor={target['candidate'][:60]} media={before}")
            await page.mouse.click(target["x"], target["y"])
            await page.keyboard.press("End")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(600)
            await paste_image_at_current_selection(page, item["path"])
            await click_apply_if_present(page, timeout_s=3)
            after = await wait_media_increment(page, before, timeout_s=75)
            if after < before + 1:
                raise RuntimeError(f"Image {item['index']} failed: media {before}->{after}")
            inserted.append(
                {
                    "index": item["index"],
                    "file": Path(item["path"]).name,
                    "anchor_used": target["candidate"],
                    "expected_anchor": item["expected_anchor"],
                    "count_after": after,
                }
            )
            await page.wait_for_timeout(2500)

        print("[5/5] verify autosave")
        await page.wait_for_timeout(35000)
        final_media = await media_items(page)
        final = await page.evaluate(
            r"""() => {
              const editor=document.querySelector('[data-testid="composer"]');
              const text=editor?.innerText||'';
              return {
                title:document.querySelector('textarea[placeholder="添加标题"]')?.value||'',
                textLength:text.length,
                hasStart:text.length > 1000,
                hasEnd:text.includes('最后，祝你使用的愉快'),
                marker:text.includes('MPH_MARKER'),
                saveText:document.body.innerText.includes('刚刚最后保存')?'刚刚最后保存':(document.body.innerText.match(/上一次保存[^\n]*/)?.[0]||'')
              };
            }"""
        )
        final.update(
            {
                "draft_url": draft_url,
                "media_count": len(final_media),
                "expected_total_media": (1 if upload_cover else 0) + data["expected_image_count"],
                "cover_uploaded": upload_cover,
                "inserted": inserted,
            }
        )
        Path(args.result_json).write_text(json.dumps(final, ensure_ascii=False, indent=2))
        await page.screenshot(path=args.screenshot, full_page=True)
        ok = (
            final["title"] == (args.title or data["title"])
            and final["hasStart"]
            and final["hasEnd"]
            and not final["marker"]
            and final["media_count"] >= final["expected_total_media"]
        )
        print("final=" + json.dumps(final, ensure_ascii=False))
        print("RESULT_OK", ok)
        await browser.close()
        if not ok:
            raise RuntimeError("Final verification failed.")
        return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_file")
    parser.add_argument("--cookies-json", default="/tmp/x_current_cookies.json")
    parser.add_argument("--parse-script")
    parser.add_argument("--title")
    parser.add_argument(
        "--allow-no-cover",
        action="store_true",
        help="Continue when the article does not start with an image. Skips cover upload and treats all images as body images.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--result-json", default="/tmp/x_article_upload_result.json")
    parser.add_argument("--url-output", default="/tmp/x_article_upload_url.txt")
    parser.add_argument("--screenshot", default="/tmp/x_article_final_uploaded.png")
    args = parser.parse_args()

    markdown_file = Path(args.markdown_file).expanduser()
    cover_policy = inspect_leading_cover(markdown_file)
    data = parse_markdown(markdown_file, Path(args.parse_script).expanduser() if args.parse_script else None)
    if args.title:
        data["title"] = args.title

    if not cover_policy["starts_with_image"] and not args.allow_no_cover:
        message = (
            "文章第一个有效内容不是图片。建议先在文章最开头加一张封面图，再上传到 X Articles。\n"
            f"当前第一个有效内容在第 {cover_policy['first_content_line']} 行："
            f"{cover_policy['first_content_preview']!r}\n"
            "如果用户明确拒绝添加封面图，并希望继续上传无封面草稿，请重新运行并加上 --allow-no-cover。"
        )
        print(message, file=sys.stderr)
        raise SystemExit(2)

    include_cover_as_body = args.allow_no_cover and bool(data.get("cover_image"))
    content_images = build_content_images(data, markdown_file, include_cover_as_body=include_cover_as_body)
    if args.allow_no_cover:
        data["cover_image"] = None
        data["expected_image_count"] = len(content_images)

    print(
        json.dumps(
            {
                "title": data["title"],
                "cover_image": data["cover_image"],
                "cover_policy": cover_policy,
                "cover_upload": bool(data.get("cover_image")) and not args.allow_no_cover,
                "expected_body_images": data["expected_image_count"],
                "anchors": [
                    {"index": item["index"], "file": Path(item["path"]).name, "anchor": item["expected_anchor"]}
                    for item in content_images
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.dry_run:
        return
    asyncio.run(run_upload(args, data, content_images))


if __name__ == "__main__":
    main()
