#!/usr/bin/env python3
"""Environment check for the WeChat MP batch exporter skill.

This script is intentionally read-only. It does not start WeChat, change proxy
settings, install certificates, or inspect credential values.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_EXPORTER = Path(os.environ.get("WECHAT_ARTICLE_EXPORTER_DIR", "~/src/wechat-article-exporter")).expanduser()
DEFAULT_WXDOWN = Path(os.environ.get("WXDOWN_SERVICE_DIR", "~/src/wxdown-service")).expanduser()


def which(name: str) -> str:
    return shutil.which(name) or ""


def read_json_safe(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def package_version(path: Path) -> str:
    data = read_json_safe(path / "package.json")
    if isinstance(data, dict):
        return str(data.get("version") or "")
    return ""


def venv_bin(path: Path, name: str) -> str:
    candidate = path / ".venv" / "bin" / name
    return str(candidate) if candidate.exists() else ""


def run_text(cmd: list[str], timeout: int = 5) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        text = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, text
    except Exception as exc:
        return False, str(exc)


def proxy_state() -> dict[str, Any]:
    if platform.system() != "Darwin" or not which("networksetup"):
        return {"supported": False}
    ok, services_text = run_text(["networksetup", "-listallnetworkservices"])
    services = []
    if ok:
        for line in services_text.splitlines():
            line = line.strip()
            if line and not line.startswith("An asterisk") and not line.startswith("*"):
                services.append(line)
    service = "Wi-Fi" if "Wi-Fi" in services else (services[0] if services else "")
    if not service:
        return {"supported": True, "error": "no network service found"}
    ok_web, web = run_text(["networksetup", "-getwebproxy", service])
    ok_secure, secure = run_text(["networksetup", "-getsecurewebproxy", service])
    return {
        "supported": True,
        "service": service,
        "web_proxy": web if ok_web else "",
        "secure_web_proxy": secure if ok_secure else "",
    }


def network_check(base_url: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/"
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "wechat-mp-batch-exporter-doctor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "url": url, "status": resp.status}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only environment check for wechat-mp-batch-exporter")
    parser.add_argument("--exporter-path", default=str(DEFAULT_EXPORTER))
    parser.add_argument("--wxdown-path", default=str(DEFAULT_WXDOWN))
    parser.add_argument("--api-base", default="https://down.mptext.top")
    parser.add_argument("--check-network", action="store_true")
    args = parser.parse_args()

    exporter = Path(args.exporter_path).expanduser()
    wxdown = Path(args.wxdown_path).expanduser()

    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "commands": {
            "python3": which("python3"),
            "node": which("node"),
            "corepack": which("corepack"),
            "yarn": which("yarn"),
            "mitmdump": which("mitmdump") or venv_bin(wxdown, "mitmdump"),
            "security": which("security"),
            "networksetup": which("networksetup"),
        },
        "paths": {
            "exporter": {
                "path": str(exporter),
                "exists": exporter.exists(),
                "package_json": (exporter / "package.json").exists(),
                "version": package_version(exporter),
            },
            "wxdown_service": {
                "path": str(wxdown),
                "exists": wxdown.exists(),
                "main_py": (wxdown / "main.py").exists(),
                "requirements": (wxdown / "requirements.txt").exists(),
            },
        },
        "proxy_state": proxy_state(),
        "manual_required": [
            "User scans exporter QR code and chooses the correct Official Account/service account.",
            "User opens WeChat desktop article/history pages when credential capture is needed.",
            "User confirms before any mitmproxy certificate trust or system proxy change.",
            "Fresh credentials are required for read counts, likes, shares, comments, and replies.",
        ],
        "hard_limits": [
            "Cannot operate WeChat UI.",
            "Cannot bypass login, paywalls, private/deleted content, or platform permissions.",
            "Cannot guarantee comments or metrics when credentials expire or comments are hidden.",
        ],
    }
    if args.check_network:
        checks["network"] = network_check(args.api_base)

    ok = checks["paths"]["exporter"]["exists"] or bool(checks["commands"]["node"]) or bool(args.api_base)
    checks["ok"] = bool(ok)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
