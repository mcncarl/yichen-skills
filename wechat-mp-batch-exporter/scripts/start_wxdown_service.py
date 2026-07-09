#!/usr/bin/env python3
"""Start the local wxdown-service helper from its project virtualenv.

This starts local ports only. It does not change system proxy settings and does
not operate WeChat.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_WXDOWN_DIR = Path(os.environ.get("WXDOWN_SERVICE_DIR", "~/src/wxdown-service")).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start wxdown-service from a local source tree")
    parser.add_argument("--wxdown-dir", default=str(DEFAULT_WXDOWN_DIR), help="Path to the local wxdown-service checkout")
    parser.add_argument("--port", default="65000", help="mitmproxy proxy port")
    parser.add_argument("--wport", default="65001", help="websocket port")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without starting the service")
    args = parser.parse_args()

    wxdown_dir = Path(args.wxdown_dir).expanduser()
    python = wxdown_dir / ".venv" / "bin" / "python"
    main_py = wxdown_dir / "main.py"
    cmd = [str(python), str(main_py), "--port", str(args.port), "--wport", str(args.wport)]
    if args.debug:
        cmd.append("--debug")
    if args.dry_run:
        print(" ".join(cmd))
        return 0

    if not python.exists():
        print(f"missing venv python: {python}", file=sys.stderr)
        return 2
    if not main_py.exists():
        print(f"missing wxdown-service main.py: {main_py}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    # Avoid mitmproxy using the user's current Clash/system proxy as its own
    # upstream unless explicitly set by WXDOWN_UPSTREAM_PROXY.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    return subprocess.call(cmd, cwd=str(wxdown_dir), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
