from __future__ import annotations

import argparse

from vault_common import KEYS_FILE, choose_db_root, choose_profile, collect_databases, load_keys, weixin_pids


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose local Windows WeChat vault readiness")
    parser.add_argument("--db-root")
    parser.add_argument("--dll")
    args = parser.parse_args()

    root = choose_db_root(args.db_root)
    databases = collect_databases(root)
    salts = {page[:16] for _, _, page in databases}
    pids = weixin_pids()
    keys = {k: v for k, v in load_keys().items() if not k.startswith("_")}
    try:
        dll, _, profile = choose_profile(args.dll)
        profile_status = f"supported {profile['version']}"
    except RuntimeError as exc:
        dll = None
        profile_status = str(exc)

    print(f"database_root: {root}")
    print(f"databases: {len(databases)}")
    print(f"distinct_salts: {len(salts)}")
    print(f"weixin_processes: {len(pids)}")
    print(f"verified_keys: {len(keys)}")
    print(f"key_file: {KEYS_FILE}")
    print(f"dll: {dll or 'not detected'}")
    print(f"profile: {profile_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
