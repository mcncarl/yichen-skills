"""Diagnose only an explicitly supplied Windows WeChat data directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vault_common import VaultError, require_explicit_dir


def diagnose(root: Path) -> dict:
    databases = []
    for path in sorted(root.rglob("*.db")):
        with path.open("rb") as handle:
            header = handle.read(16)
        kind = "plaintext" if header == b"SQLite format 3\x00" else "encrypted"
        databases.append({
            "relative_path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "kind": kind,
            "salt_fingerprint": None if kind == "plaintext" else hashlib.sha256(header).hexdigest()[:12],
        })
    return {
        "database_count": len(databases),
        "encrypted_count": sum(item["kind"] == "encrypted" for item in databases),
        "plaintext_count": sum(item["kind"] == "plaintext" for item in databases),
        "databases": databases,
    }


def inspect_dll(path: Path) -> dict:
    if not path.is_file():
        raise VaultError(f"DLL not found: {path}")
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest().upper()
    profiles_path = Path(__file__).with_name("profiles.json")
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    profile = profiles.get(digest)
    return {
        "sha256": digest,
        "supported": profile is not None,
        "profile_version": None if profile is None else profile["version"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-root", required=True)
    parser.add_argument("--dll", help="Optional explicit Weixin.dll path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = diagnose(require_explicit_dir(args.db_root, "--db-root"))
        if args.dll:
            result["dll"] = inspect_dll(Path(args.dll).expanduser().resolve())
    except (OSError, VaultError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Databases: {result['database_count']} (encrypted {result['encrypted_count']}, plaintext {result['plaintext_count']})")
        for item in result["databases"]:
            print(f"- {item['kind']:9} {item['relative_path']}")


if __name__ == "__main__":
    main()
