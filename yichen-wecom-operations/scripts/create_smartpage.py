#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse


STATE_ROOT = Path(
    os.environ.get(
        "WECOM_OPERATIONS_STATE_ROOT",
        str(Path.home() / "Library/Application Support/wecom-operations"),
    )
)
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((<[^>\n]+>|[^)\n]+)\)")


def parse_business(stdout: str) -> dict:
    payload = json.loads(stdout)
    if "errcode" in payload:
        business = payload
    else:
        text = payload["result"]["content"][0]["text"]
        business = json.loads(text)
    if business.get("errcode") != 0:
        help_message = business.get("help_message")
        if help_message:
            raise RuntimeError(help_message)
        raise RuntimeError(
            f"errcode={business.get('errcode')} errmsg={business.get('errmsg')}"
        )
    return business


def call(command: list[str]) -> dict:
    completed = subprocess.run(
        command, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return parse_business(completed.stdout)


def image_destination(match: re.Match[str]) -> str:
    value = match.group(2).strip()
    if value.startswith("<") and value.endswith(">"):
        return value[1:-1]
    return value


def discover_images(source: Path) -> tuple[str, dict[Path, list[str]], int]:
    text = source.read_text(encoding="utf-8")
    local_images: dict[Path, list[str]] = {}
    remote_count = 0
    for match in IMAGE_PATTERN.finditer(text):
        destination = image_destination(match)
        parsed = urlparse(destination)
        if parsed.scheme in {"http", "https"}:
            remote_count += 1
            continue
        if parsed.scheme == "data":
            raise RuntimeError("不支持 data: 图片；请保留本地图片文件路径")
        if parsed.scheme == "file":
            image_path = Path(unquote(parsed.path))
        else:
            image_path = Path(unquote(destination))
            if not image_path.is_absolute():
                image_path = source.parent / image_path
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        local_images.setdefault(image_path, []).append(match.group(0))
    return text, local_images, remote_count


def safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    except Exception:
        if os.path.exists(temp_name):
            os.chmod(temp_name, 0o600)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="创建企业微信图文智能文档")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--page-title", default="正文")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > 10 * 1024 * 1024:
        raise RuntimeError("Markdown 文件超过 10MB")

    text, local_images, remote_count = discover_images(source)
    preview = {
        "execute": args.execute,
        "source_name": source.name,
        "title": args.title,
        "local_images": len(local_images),
        "remote_images": remote_count,
        "will_create_resource_doc": bool(local_images),
    }
    if not args.execute:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    cli = os.environ.get("WECOM_CLI") or shutil.which("wecom-cli")
    if not cli:
        raise RuntimeError("未找到 wecom-cli")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = STATE_ROOT / "uploads" / timestamp
    receipt_dir = STATE_ROOT / "receipts"
    work_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(work_dir, 0o700)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(receipt_dir, 0o700)

    image_urls: dict[Path, str] = {}
    resource = None
    if local_images:
        helper_value = os.environ.get("WECOM_UPLOAD_HELPER")
        if not helper_value:
            raise RuntimeError(
                "检测到本地图片，但未设置 WECOM_UPLOAD_HELPER；"
                "该变量必须指向带 doc +doc_upload_image 能力的可执行文件"
            )
        helper = Path(helper_value).expanduser().resolve()
        if not helper.is_file() or not os.access(helper, os.X_OK):
            raise RuntimeError(f"企微图片上传 helper 不可用: {helper}")

        resource = call(
            [
                cli,
                "doc",
                "create_doc",
                json.dumps(
                    {"doc_type": 3, "doc_name": f"{args.title}（图片资源）"},
                    ensure_ascii=False,
                ),
            ]
        )
        for image_path in local_images:
            uploaded = call(
                [
                    str(helper),
                    "doc",
                    "+doc_upload_image",
                    "--docid",
                    resource["docid"],
                    "--image-path",
                    str(image_path),
                ]
            )
            image_urls[image_path] = uploaded["url"]

        resource_body = ["# 图片资源", "", "本页由企微操作 Skill 自动维护。", ""]
        for image_path, url in image_urls.items():
            resource_body.extend([f"## {image_path.name}", "", f"![]({url})", ""])
        try:
            call(
                [
                    cli,
                    "doc",
                    "edit_doc_content",
                    json.dumps(
                        {
                            "docid": resource["docid"],
                            "content": "\n".join(resource_body),
                            "content_type": 1,
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            resource["populated"] = True
        except RuntimeError:
            resource["populated"] = False

        def replace_local(match: re.Match[str]) -> str:
            destination = image_destination(match)
            parsed = urlparse(destination)
            if parsed.scheme in {"http", "https"}:
                return match.group(0)
            if parsed.scheme == "file":
                path = Path(unquote(parsed.path)).resolve()
            else:
                path = Path(unquote(destination))
                if not path.is_absolute():
                    path = source.parent / path
                path = path.resolve()
            return f"![{match.group(1)}]({image_urls[path]})"

        text = IMAGE_PATTERN.sub(replace_local, text)

    upload_copy = work_dir / source.name
    safe_write(upload_copy, text)
    final = call(
        [
            cli,
            "doc",
            "+smartpage_create",
            json.dumps(
                {
                    "title": args.title,
                    "pages": [
                        {
                            "page_title": args.page_title,
                            "content_type": 1,
                            "page_filepath": str(upload_copy),
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ]
    )

    receipt = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source),
        "title": args.title,
        "final_docid": final.get("docid"),
        "final_url": final.get("url"),
        "resource_docid": resource.get("docid") if resource else None,
        "resource_url": resource.get("url") if resource else None,
        "resource_populated": resource.get("populated") if resource else None,
        "images_uploaded": len(image_urls),
        "upload_copy": str(upload_copy),
    }
    receipt_path = receipt_dir / f"{timestamp}.json"
    safe_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

    public_result = {
        "status": "ok",
        "title": args.title,
        "url": final.get("url"),
        "resource_url": resource.get("url") if resource else None,
        "images_uploaded": len(image_urls),
        "receipt_saved": True,
    }
    print(json.dumps(public_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
