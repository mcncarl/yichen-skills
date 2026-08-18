from __future__ import annotations

import sys

from decrypt_databases import main as decrypt_main


def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("refresh_vault.py does not accept arguments")
    return decrypt_main(["--mode", "incremental"])


if __name__ == "__main__":
    raise SystemExit(main())

