#!/usr/bin/env python3
"""Export current X/Twitter cookies from macOS Chrome to a Playwright JSON file.

The script prints cookie names only, never values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# The maintained, pinned pycryptodome distribution intentionally exposes the Crypto namespace.
from Crypto.Cipher import AES  # nosec B413
from Crypto.Protocol.KDF import PBKDF2  # nosec B413


CHROME_EPOCH_DELTA = 11644473600
CANONICAL_COOKIES_PATH = Path.home() / ".ailu" / "secrets" / "x" / "cookies.json"
ALLOWED_COOKIE_DOMAINS = ("x.com", "twitter.com")


def chrome_time_to_unix(value: int) -> float:
    if not value:
        return -1
    return max(0, value / 1_000_000 - CHROME_EPOCH_DELTA)


def get_chrome_password() -> str:
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
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


def host_matches_domain(host: str, domain: str) -> bool:
    normalized_host = host.strip().lower().lstrip(".")
    normalized_domain = domain.strip().lower().lstrip(".")
    return bool(normalized_domain) and (
        normalized_host == normalized_domain
        or normalized_host.endswith(f".{normalized_domain}")
    )


def validate_export_domains(domains: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(domain.strip().lower().lstrip(".") for domain in domains if domain.strip())
    )
    if set(normalized) != set(ALLOWED_COOKIE_DOMAINS):
        raise ValueError("Cookie export is restricted to x.com and twitter.com.")
    return ALLOWED_COOKIE_DOMAINS


def ensure_canonical_cookie_directory(output: Path) -> None:
    if output != CANONICAL_COOKIES_PATH:
        output.parent.mkdir(parents=True, exist_ok=True)
        return

    cursor = Path.home()
    for component in (".ailu", "secrets", "x"):
        cursor /= component
        try:
            current = cursor.lstat()
        except FileNotFoundError:
            cursor.mkdir(mode=0o700)
            current = cursor.lstat()
        if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode):
            raise RuntimeError(f"Canonical cookie directory is unsafe: {cursor}")
        cursor.chmod(0o700)


def write_private_cookie_json(output: Path, cookies: list[dict]) -> None:
    output = output.expanduser().absolute()
    ensure_canonical_cookie_directory(output)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.stage-",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(cookies, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        output.chmod(0o600)
        directory_descriptor = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def export_cookies(profile: Path, output: Path, domains: list[str]) -> list[dict]:
    domains = list(validate_export_domains(domains))
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
        if not any(host_matches_domain(host, domain) for domain in domains):
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

    write_private_cookie_json(output, cookies)
    return cookies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default=str(Path.home() / "Library/Application Support/Google/Chrome/Default"),
        help="Chrome profile directory containing the Cookies database.",
    )
    parser.add_argument("--output", default=str(CANONICAL_COOKIES_PATH))
    args = parser.parse_args()

    cookies = export_cookies(Path(args.profile), Path(args.output), list(ALLOWED_COOKIE_DOMAINS))
    names = sorted({cookie["name"] for cookie in cookies})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"exported={len(cookies)} output={args.output} time={now}")
    print("names=" + ",".join(names))


if __name__ == "__main__":
    main()
