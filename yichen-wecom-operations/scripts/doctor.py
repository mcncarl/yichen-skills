#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


CONFIG_DIR = Path.home() / ".config/wecom"
CONFIG_FILES = [".encryption_key", "bot.enc", "mcp_config.enc"]
UPLOAD_HELPER_VALUE = os.environ.get("WECOM_UPLOAD_HELPER")
UPLOAD_HELPER = (
    Path(UPLOAD_HELPER_VALUE).expanduser().resolve()
    if UPLOAD_HELPER_VALUE
    else None
)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查企业微信 CLI 能力")
    parser.add_argument(
        "--category",
        choices=["doc", "meeting", "schedule", "todo", "contact"],
    )
    args = parser.parse_args()

    cli = os.environ.get("WECOM_CLI") or shutil.which("wecom-cli")
    result = {
        "cli_found": bool(cli),
        "version": None,
        "config_ready": True,
        "config_permissions_0600": True,
        "upload_helper_configured": bool(UPLOAD_HELPER),
        "upload_helper_ready": bool(
            UPLOAD_HELPER
            and UPLOAD_HELPER.is_file()
            and os.access(UPLOAD_HELPER, os.X_OK)
        ),
    }

    if cli:
        completed = subprocess.run(
            [cli, "--version"], capture_output=True, text=True, check=False
        )
        result["version"] = completed.stdout.strip() or completed.stderr.strip()
    else:
        result["config_ready"] = False

    for name in CONFIG_FILES:
        path = CONFIG_DIR / name
        if not path.is_file():
            result["config_ready"] = False
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            result["config_permissions_0600"] = False

    if args.category and cli:
        completed = subprocess.run(
            [cli, args.category, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        result["category"] = args.category
        result["category_available"] = completed.returncode == 0
        if completed.returncode != 0:
            result["category_error"] = output[:500]

    print(json.dumps(result, ensure_ascii=False, indent=2))
    hard_failure = not cli or not result["config_ready"]
    return 1 if hard_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
