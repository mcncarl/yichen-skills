"""Shared safety and filesystem helpers for the Windows vault."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable


APP_NAME = "yichen-wechat-windows-vault"
DEFAULT_HOME = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / APP_NAME


class VaultError(RuntimeError):
    """A user-facing vault error."""


def vault_home(value: str | Path | None = None) -> Path:
    path = Path(value).expanduser() if value else DEFAULT_HOME
    return path.resolve()


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Keep this best-effort and dependency-free. Windows ACL inheritance remains
        # authoritative; files containing keys are never written outside this root.
        os.chmod(path, 0o700)
    return path


def require_explicit_dir(value: str | Path | None, label: str) -> Path:
    if value is None or not str(value).strip():
        raise VaultError(f"{label} is required; automatic folder scanning is disabled")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise VaultError(f"{label} is not a directory: {path}")
    return path


def require_under(child: Path, parent: Path, label: str) -> Path:
    child = child.resolve()
    parent = parent.resolve()
    if child != parent and parent not in child.parents:
        raise VaultError(f"{label} must stay under {parent}")
    return child


def atomic_json(path: Path, value: Any, *, private: bool = False) -> None:
    ensure_private_dir(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if private:
            os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultError(f"invalid JSON file: {path}") from exc


def readonly_connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise VaultError(f"database not found: {path}")
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_names(con: sqlite3.Connection, prefix: str | None = None) -> list[str]:
    sql = "SELECT name FROM sqlite_master WHERE type='table'"
    params: tuple[str, ...] = ()
    if prefix is not None:
        sql += " AND name LIKE ? ESCAPE '\\'"
        params = (prefix.replace("%", "\\%").replace("_", "\\_") + "%",)
    return [row[0] for row in con.execute(sql, params)]


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({quote_identifier(table)})")}


def find_db(root: Path, names: Iterable[str]) -> Path | None:
    wanted = {name.casefold() for name in names}
    for path in sorted(root.rglob("*.db")):
        if path.name.casefold() in wanted:
            return path
    return None


def iter_message_dbs(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("message_*.db")
        if path.stem.removeprefix("message_").isdigit()
    )
