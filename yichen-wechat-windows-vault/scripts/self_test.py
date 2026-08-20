"""Dependency and static profile checks that do not access WeChat data."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        import Crypto
        import frida
        import zstandard
    except ImportError as exc:
        print(f"missing dependency: {exc.name}", file=sys.stderr)
        return 1
    profiles = json.loads(Path(__file__).with_name("profiles.json").read_text(encoding="utf-8"))
    for digest, profile in profiles.items():
        assert len(digest) == 64 and int(digest, 16) >= 0
        assert profile["module"].casefold() == "weixin.dll"
        assert profile["rva"] > 0
        assert len(bytes.fromhex(profile["prologue"])) >= 16
    print(json.dumps({
        "ok": True,
        "python": sys.version.split()[0],
        "frida": frida.__version__,
        "profiles": len(profiles),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
