from __future__ import annotations

import sys

from vault_cli import main as vault_main

ALLOWED_COMMANDS = {
    "status",
    "sessions",
    "unread",
    "new-messages",
    "contacts",
    "members",
    "history",
    "search",
    "stats",
    "favorites",
    "moments",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        raise SystemExit(f"allowed commands: {allowed}")
    if any(arg in {"--decrypted-dir", "--exports-dir", "--data-root"} for arg in sys.argv[2:]):
        raise SystemExit("custom filesystem paths are not allowed through the gateway wrapper")
    vault_main(sys.argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
