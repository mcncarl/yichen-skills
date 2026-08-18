from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

from vault_common import PROFILES
from wechat_media import _find_node


def _check_mcp_registered() -> bool:
    """Check if the MCP server is registered in any supported client config."""
    home = Path.home()
    candidates = [
        home / ".workbuddy" / "mcp.json",
        Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Claude" / "claude_desktop_config.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "wechat-windows-vault" in data.get("mcpServers", {}):
                    return True
            except (json.JSONDecodeError, OSError):
                continue
    return False


def main() -> int:
    app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "wechat-windows-vault"
    fixtures_path = Path(__file__).resolve().parent.parent / "references" / "profile-fixtures.json"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8")) if fixtures_path.is_file() else {}
    fixtures_ok = bool(fixtures) and all(
        fingerprint in PROFILES
        and PROFILES[fingerprint]["version"] == fixture["version"]
        and PROFILES[fingerprint]["pbkdf2_rva"] == int(fixture["pbkdf2_rva"], 0)
        and PROFILES[fingerprint]["prologue"].lower() == fixture["prologue"].lower()
        for fingerprint, fixture in fixtures.items()
    )
    modules = ["Crypto", "av", "frida", "faster_whisper", "mcp", "opencc", "yaml", "zstandard"]
    try:
        node_runtime = bool(_find_node())
    except RuntimeError:
        node_runtime = False
    result = {
        "python": sys.version.split()[0],
        "dependencies": {name: importlib.util.find_spec(name) is not None for name in modules},
        "node_runtime": node_runtime,
        "node_silk": (app_dir / "node-runtime" / "node_modules" / "silk-wasm").is_dir(),
        "mcp_registered": _check_mcp_registered(),
        "private_directory": str(app_dir),
        "profile_fixtures": fixtures_ok,
    }
    result["ok"] = (
        all(result["dependencies"].values())
        and result["node_runtime"]
        and result["node_silk"]
        and fixtures_ok
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
