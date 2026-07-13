#!/usr/bin/env python3
"""Export current X/Twitter cookies from macOS Chrome to a Playwright JSON file.

The script prints cookie names only, never values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2


CHROME_EPOCH_DELTA = 11644473600


def chrome_time_to_unix(value: int) -> float:
    if not value:
        return -1
    return max(0, value / 1_000_000 - CHROME_EPOCH_DELTA)


def get_chrome_password() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def decrypt_cookie(host: str, encrypted_value: bytes, password: str) -> str:
    if not encrypted_value:
        return ""
    if not encrypted_value.startswith((b"v10", b"v11")):
        return encrypted_value.decode("utf-8", "ignore")

    key = PBKDF2(password, b"saltysalt", dkLen=16, count=1003)
    cipher = AES.new(key, AES.MODE_CBC, IV=b" " * 16)
    decrypted = cipher.decrypt(encrypted_value[3:])
    pad = decrypted[-1]
    if 1 <= pad <= 16:
        decrypted = decrypted[:-pad]

    host_hash = hashlib.sha256(host.encode("utf-8")).digest()
    if decrypted.startswith(host_hash):
        decrypted = decrypted[len(host_hash) :]
    return decrypted.decode("utf-8", "ignore")


def same_site(value: int) -> str:
    return {0: "None", 1: "Lax", 2: "Strict", -1: "Lax"}.get(value, "Lax")


def export_cookies(profile: Path, output: Path, domains: list[str]) -> list[dict]:
    cookie_db = profile / "Cookies"
    if not cookie_db.exists():
        raise FileNotFoundError(f"Chrome cookie DB not found: {cookie_db}")

    password = get_chrome_password()
    with tempfile.TemporaryDirectory() as td:
        temp_db = Path(td) / "Cookies"
        shutil.copy2(cookie_db, temp_db)
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT host_key, name, path, value, encrypted_value, expires_utc,
                   is_secure, is_httponly, samesite
            FROM cookies
            """
        ).fetchall()
        conn.close()

    cookies = []
    for row in rows:
        host = row["host_key"]
        if not any(domain in host for domain in domains):
            continue
        value = row["value"] or decrypt_cookie(host, row["encrypted_value"], password)
        if not value:
            continue
        cookies.append(
            {
                "name": row["name"],
                "value": value,
                "domain": host,
                "path": row["path"] or "/",
                "expires": chrome_time_to_unix(row["expires_utc"]),
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": same_site(row["samesite"]),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
    return cookies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default=str(Path.home() / "Library/Application Support/Google/Chrome/Default"),
        help="Chrome profile directory containing the Cookies database.",
    )
    parser.add_argument("--output", default="/tmp/x_current_cookies.json")
    parser.add_argument("--domains", nargs="+", default=["x.com", "twitter.com"])
    args = parser.parse_args()

    cookies = export_cookies(Path(args.profile), Path(args.output), args.domains)
    names = sorted({cookie["name"] for cookie in cookies})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"exported={len(cookies)} output={args.output} time={now}")
    print("names=" + ",".join(names))


if __name__ == "__main__":
    main()
