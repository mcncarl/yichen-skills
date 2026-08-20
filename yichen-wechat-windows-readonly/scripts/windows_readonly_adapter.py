#!/usr/bin/env python3
"""Fail-closed queries for an explicitly selected, already-readable Vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import stat
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Iterator, Sequence


MESSAGE_TABLE_RE = re.compile(r"^Msg_[0-9a-f]{32}$")
MESSAGE_DATABASE_RE = re.compile(r"^message_[0-9A-Za-z_-]+\.db$")
MAX_CONTENT_LENGTH = 10_000
MAX_LABEL_LENGTH = 256
MAX_QUERY_LIMIT = 500

TYPE_LABELS = {
    1: "text",
    3: "image",
    34: "audio",
    43: "video",
    47: "sticker",
    48: "location",
    49: "link",
    10000: "system",
}


class AdapterError(Exception):
    """A controlled error whose message is safe to return to the caller."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class FileState:
    size: int
    modified_ns: int
    inode: int
    device: int


@dataclass(frozen=True)
class Contact:
    username: str
    display_name: str
    remark: str
    nickname: str
    alias: str
    is_group: bool

    @property
    def contact_id(self) -> str:
        digest = hashlib.sha256(self.username.encode("utf-8")).hexdigest()[:16]
        return f"contact-{digest}"

    def public(self) -> dict:
        return {
            "contact_id": self.contact_id,
            "display_name": self.display_name,
            "is_group": self.is_group,
        }


def _bounded_text(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "")
    return text[:limit]


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & flag)


def _reject_reparse_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and _is_reparse_point(current):
            raise AdapterError(
                "reparse_point_rejected",
                "The selected Vault path contains a link or reparse point.",
            )


def resolve_vault_root(value: str) -> Path:
    supplied = Path(value)
    if not supplied.is_absolute():
        raise AdapterError("invalid_vault_root", "--vault-root must be an absolute path.")
    try:
        _reject_reparse_components(supplied)
        root = supplied.resolve(strict=True)
    except AdapterError:
        raise
    except OSError as exc:
        raise AdapterError("invalid_vault_root", "The selected Vault root is unavailable.") from exc
    if not root.is_dir():
        raise AdapterError("invalid_vault_root", "The selected Vault root is not a directory.")
    return root


def _validate_database(root: Path, relative: Path) -> Path:
    candidate = root / relative
    try:
        _reject_reparse_components(candidate)
        resolved = candidate.resolve(strict=True)
    except AdapterError:
        raise
    except OSError as exc:
        raise AdapterError("database_unavailable", "A required selected database is unavailable.") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.suffix.lower() != ".db":
        raise AdapterError("database_unavailable", "A required selected database is unavailable.")
    return resolved


def _optional_database(root: Path, relative: Path) -> Path | None:
    candidate = root / relative
    if not candidate.exists():
        return None
    return _validate_database(root, relative)


def discover_message_databases(root: Path) -> list[Path]:
    directory = root / "message"
    if not directory.exists():
        return []
    _reject_reparse_components(directory)
    if not directory.is_dir():
        raise AdapterError("invalid_vault_layout", "The selected Vault message location is invalid.")
    paths = []
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise AdapterError("database_unavailable", "The selected message databases are unavailable.") from exc
    for entry in entries:
        if MESSAGE_DATABASE_RE.fullmatch(entry.name):
            paths.append(_validate_database(root, Path("message") / entry.name))
    return paths


def _file_state(path: Path) -> FileState:
    try:
        info = path.stat()
    except OSError as exc:
        raise AdapterError("database_unavailable", "A selected database became unavailable.") from exc
    return FileState(info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev)


def _database_state(path: Path) -> tuple[FileState, FileState | None]:
    wal = Path(f"{path}-wal")
    wal_state = None
    if wal.exists():
        if _is_reparse_point(wal) or not wal.is_file():
            raise AdapterError("invalid_wal", "A selected database has an invalid WAL sidecar.")
        wal_state = _file_state(wal)
    return _file_state(path), wal_state


@contextmanager
def snapshot_databases(paths: Sequence[Path]) -> Iterator[dict[Path, Path]]:
    """Copy stable database/WAL pairs to a temporary query-only workspace."""

    unique_paths = list(dict.fromkeys(paths))
    if not unique_paths:
        raise AdapterError("database_unavailable", "No selected database is available for this query.")
    before = {path: _database_state(path) for path in unique_paths}
    with tempfile.TemporaryDirectory(prefix="yichen-wechat-readonly-") as temp_value:
        temp_root = Path(temp_value)
        copies: dict[Path, Path] = {}
        try:
            for index, source in enumerate(unique_paths):
                destination_dir = temp_root / f"db-{index}"
                destination_dir.mkdir()
                destination = destination_dir / source.name
                shutil.copyfile(source, destination)
                if before[source][1] is not None:
                    shutil.copyfile(Path(f"{source}-wal"), Path(f"{destination}-wal"))
                copies[source] = destination
        except OSError as exc:
            raise AdapterError("snapshot_failed", "The selected databases could not be snapshotted safely.") from exc

        after = {path: _database_state(path) for path in unique_paths}
        if before != after:
            raise AdapterError(
                "source_changed",
                "A selected database changed during the read-only snapshot; retry after it is stable.",
            )
        yield copies


@contextmanager
def connect_readonly(path: Path) -> Iterator[sqlite3.Connection]:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        result = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        if result != ["ok"]:
            raise AdapterError("corrupt_database", "A selected database is corrupt or unreadable.")
        yield connection
    except AdapterError:
        raise
    except sqlite3.Error as exc:
        raise AdapterError("corrupt_database", "A selected database is corrupt or unreadable.") from exc
    finally:
        if connection is not None:
            connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in {"contact", "SessionTable", "Name2Id"} and not MESSAGE_TABLE_RE.fullmatch(table):
        raise AdapterError("unsupported_schema", "A selected database contains an unsupported table name.")
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info([{table}])")}


def _choose_column(columns: set[str], *choices: str, required: bool = False) -> str | None:
    for choice in choices:
        if choice in columns:
            return choice
    if required:
        raise AdapterError("unsupported_schema", "A selected database has an unsupported schema.")
    return None


def _select_expression(column: str | None, alias: str) -> str:
    return f"[{column}] AS [{alias}]" if column else f"NULL AS [{alias}]"


def load_contacts(connection: sqlite3.Connection) -> tuple[list[Contact], dict[str, Contact]]:
    if not _table_exists(connection, "contact"):
        raise AdapterError("unsupported_schema", "The contact database has an unsupported schema.")
    columns = _table_columns(connection, "contact")
    username = _choose_column(columns, "username", "userName", required=True)
    nickname = _choose_column(columns, "nick_name", "nickname")
    remark = _choose_column(columns, "remark")
    alias = _choose_column(columns, "alias")
    sql = "SELECT " + ", ".join(
        (
            _select_expression(username, "username"),
            _select_expression(nickname, "nickname"),
            _select_expression(remark, "remark"),
            _select_expression(alias, "alias"),
        )
    ) + " FROM [contact]"
    contacts = []
    by_username = {}
    for row in connection.execute(sql):
        internal_name = _bounded_text(row["username"], MAX_LABEL_LENGTH)
        if not internal_name:
            continue
        safe_remark = _bounded_text(row["remark"], MAX_LABEL_LENGTH)
        safe_nickname = _bounded_text(row["nickname"], MAX_LABEL_LENGTH)
        safe_alias = _bounded_text(row["alias"], MAX_LABEL_LENGTH)
        display = safe_remark or safe_nickname or "Unnamed contact"
        contact = Contact(
            username=internal_name,
            display_name=display,
            remark=safe_remark,
            nickname=safe_nickname,
            alias=safe_alias,
            is_group="@chatroom" in internal_name,
        )
        contacts.append(contact)
        by_username[internal_name] = contact
    return contacts, by_username


def resolve_contact(query: str, contacts: Sequence[Contact]) -> Contact:
    normalized = query.strip().casefold()
    if not normalized:
        raise AdapterError("contact_not_found", "A contact name or contact_id is required.")
    id_matches = [contact for contact in contacts if contact.contact_id.casefold() == normalized]
    if id_matches:
        return id_matches[0]
    exact = [
        contact
        for contact in contacts
        if normalized in {
            contact.display_name.casefold(),
            contact.remark.casefold(),
            contact.nickname.casefold(),
            contact.alias.casefold(),
        }
    ]
    matches = exact or [
        contact
        for contact in contacts
        if any(
            normalized in value.casefold()
            for value in (contact.display_name, contact.remark, contact.nickname, contact.alias)
            if value
        )
    ]
    if not matches:
        raise AdapterError("contact_not_found", "No matching contact was found in the selected Vault.")
    if len(matches) > 1:
        candidates = [contact.public() for contact in sorted(matches, key=lambda item: item.contact_id)]
        raise AdapterError(
            "ambiguous_contact",
            "Multiple contacts match; retry with one returned contact_id.",
            {"candidates": candidates},
        )
    return matches[0]


def _base_message_type(value: object) -> int:
    try:
        return int(value or 0) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


def _type_label(value: object) -> str:
    base = _base_message_type(value)
    return TYPE_LABELS.get(base, f"type-{base}")


def _safe_message_content(value: object) -> str | None:
    if isinstance(value, str):
        return _bounded_text(value, MAX_CONTENT_LENGTH)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")[:MAX_CONTENT_LENGTH]
        except UnicodeDecodeError:
            return None
    return None


def _iso_timestamp(value: object) -> str:
    try:
        timestamp = int(value or 0)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, TypeError, ValueError):
        return ""


def _parse_time(value: str | None, *, end_of_day: bool = False) -> int | None:
    if value is None:
        return None
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min, timezone.utc)
        else:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError as exc:
        raise AdapterError("invalid_time", "Time values must use ISO 8601 format.") from exc


def _positive_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > MAX_QUERY_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_QUERY_LIMIT}")
    return parsed


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be nonnegative")
    return parsed


def _message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def _message_columns(connection: sqlite3.Connection, table: str) -> dict[str, str | None]:
    columns = _table_columns(connection, table)
    return {
        "local_id": _choose_column(columns, "local_id", "id"),
        "local_type": _choose_column(columns, "local_type", "type", required=True),
        "create_time": _choose_column(columns, "create_time", "timestamp", required=True),
        "real_sender_id": _choose_column(columns, "real_sender_id", "sender_id"),
        "message_content": _choose_column(columns, "message_content", "content"),
    }


def _name_to_id(connection: sqlite3.Connection) -> dict[int, str]:
    if not _table_exists(connection, "Name2Id"):
        return {}
    columns = _table_columns(connection, "Name2Id")
    if "user_name" not in columns:
        return {}
    mapping = {}
    for row in connection.execute("SELECT rowid, user_name FROM [Name2Id]"):
        try:
            mapping[int(row[0])] = _bounded_text(row[1], MAX_LABEL_LENGTH)
        except (TypeError, ValueError):
            continue
    return mapping


def _username_for_table(table: str, connection: sqlite3.Connection, contacts: Sequence[Contact]) -> str:
    target = table[4:]
    for username in _name_to_id(connection).values():
        if hashlib.md5(username.encode("utf-8")).hexdigest() == target:
            return username
    for contact in contacts:
        if hashlib.md5(contact.username.encode("utf-8")).hexdigest() == target:
            return contact.username
    return ""


def _message_tables(connection: sqlite3.Connection) -> list[str]:
    tables = []
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%' ORDER BY name"
    ):
        name = str(row[0] or "")
        if MESSAGE_TABLE_RE.fullmatch(name):
            tables.append(name)
    return tables


def _where_for_time(columns: dict[str, str | None], start: int | None, end: int | None) -> tuple[list[str], list]:
    clauses = []
    parameters: list = []
    create_time = columns["create_time"]
    if start is not None:
        clauses.append(f"[{create_time}] >= ?")
        parameters.append(start)
    if end is not None:
        clauses.append(f"[{create_time}] <= ?")
        parameters.append(end)
    return clauses, parameters


def _message_row(
    row: sqlite3.Row,
    contact: Contact,
    contacts_by_username: dict[str, Contact],
    name_ids: dict[int, str],
) -> dict:
    local_type = row["local_type"]
    base_type = _base_message_type(local_type)
    sender_username = ""
    try:
        sender_username = name_ids.get(int(row["real_sender_id"] or 0), "")
    except (TypeError, ValueError):
        pass
    sender_contact = contacts_by_username.get(sender_username)
    sender = sender_contact.display_name if sender_contact else contact.display_name
    item = {
        "message_id": str(row["local_id"] or ""),
        "message_type": _type_label(local_type),
        "sender": sender,
        "timestamp": int(row["create_time"] or 0),
        "time_utc": _iso_timestamp(row["create_time"]),
    }
    if base_type == 1:
        content = _safe_message_content(row["message_content"])
        item["content"] = content
        item["content_omitted"] = content is None
    else:
        item["content"] = None
        item["content_omitted"] = True
    return item


def _collect_history(
    contact: Contact,
    contacts_by_username: dict[str, Contact],
    message_paths: Sequence[Path],
    copies: dict[Path, Path],
    start: int | None,
    end: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    table = _message_table(contact.username)
    collected = []
    for source in message_paths:
        with connect_readonly(copies[source]) as connection:
            if not _table_exists(connection, table):
                continue
            columns = _message_columns(connection, table)
            clauses, parameters = _where_for_time(columns, start, end)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            expressions = (
                _select_expression(columns["local_id"], "local_id"),
                _select_expression(columns["local_type"], "local_type"),
                _select_expression(columns["create_time"], "create_time"),
                _select_expression(columns["real_sender_id"], "real_sender_id"),
                _select_expression(columns["message_content"], "message_content"),
            )
            sql = f"SELECT {', '.join(expressions)} FROM [{table}]{where} ORDER BY [create_time] DESC LIMIT ?"
            parameters.append(limit + offset)
            name_ids = _name_to_id(connection)
            for row in connection.execute(sql, parameters):
                collected.append(_message_row(row, contact, contacts_by_username, name_ids))
    collected.sort(key=lambda item: (item["timestamp"], item["message_id"]), reverse=True)
    page = collected[offset : offset + limit]
    page.sort(key=lambda item: (item["timestamp"], item["message_id"]))
    return page


def _load_contacts_from_copy(contact_source: Path, copies: dict[Path, Path]) -> tuple[list[Contact], dict[str, Contact]]:
    with connect_readonly(copies[contact_source]) as connection:
        return load_contacts(connection)


def command_status(root: Path) -> dict:
    contact = _optional_database(root, Path("contact/contact.db"))
    session = _optional_database(root, Path("session/session.db"))
    messages = discover_message_databases(root)
    if not any((contact, session, messages)):
        raise AdapterError("unsupported_vault", "The selected Vault has no supported database copy.")

    def health(path: Path) -> tuple[bool, str | None, bool]:
        wal_present = Path(f"{path}-wal").exists()
        try:
            with snapshot_databases([path]) as copies:
                with connect_readonly(copies[path]):
                    pass
            return True, None, wal_present
        except AdapterError as exc:
            return False, exc.code, wal_present

    result = {
        "vault": "explicitly-selected",
        "metadata_only": True,
        "contacts": {"available": contact is not None},
        "sessions": {"available": session is not None},
        "messages": {"available_count": len(messages)},
    }
    if contact:
        healthy, issue, wal = health(contact)
        result["contacts"].update({"healthy": healthy, "issue": issue, "wal_present": wal})
    if session:
        healthy, issue, wal = health(session)
        result["sessions"].update({"healthy": healthy, "issue": issue, "wal_present": wal})
    message_health = [health(path) for path in messages]
    result["messages"].update(
        {
            "healthy_count": sum(1 for healthy, _, _ in message_health if healthy),
            "unhealthy_count": sum(1 for healthy, _, _ in message_health if not healthy),
            "wal_count": sum(1 for _, _, wal in message_health if wal),
            "issues": sorted({issue for _, issue, _ in message_health if issue}),
        }
    )
    return result


def command_contacts(root: Path, query: str | None, limit: int) -> dict:
    source = _validate_database(root, Path("contact/contact.db"))
    with snapshot_databases([source]) as copies:
        contacts, _ = _load_contacts_from_copy(source, copies)
    if query:
        normalized = query.casefold()
        contacts = [
            contact
            for contact in contacts
            if any(
                normalized in value.casefold()
                for value in (contact.display_name, contact.remark, contact.nickname, contact.alias)
                if value
            )
        ]
    contacts.sort(key=lambda item: (not item.is_group, item.display_name.casefold(), item.contact_id))
    public = [contact.public() for contact in contacts[:limit]]
    return {"count": len(public), "contacts": public}


def command_sessions(root: Path, limit: int) -> dict:
    session_source = _validate_database(root, Path("session/session.db"))
    contact_source = _optional_database(root, Path("contact/contact.db"))
    sources = [session_source] + ([contact_source] if contact_source else [])
    with snapshot_databases(sources) as copies:
        contacts_by_username: dict[str, Contact] = {}
        if contact_source:
            _, contacts_by_username = _load_contacts_from_copy(contact_source, copies)
        with connect_readonly(copies[session_source]) as connection:
            if not _table_exists(connection, "SessionTable"):
                raise AdapterError("unsupported_schema", "The session database has an unsupported schema.")
            columns = _table_columns(connection, "SessionTable")
            required = {
                "username",
                "unread_count",
                "summary",
                "last_timestamp",
                "last_msg_type",
                "last_msg_sender",
                "last_sender_display_name",
            }
            if not required.issubset(columns):
                raise AdapterError("unsupported_schema", "The session database has an unsupported schema.")
            rows = connection.execute(
                """
                SELECT username, unread_count, summary, last_timestamp,
                       last_msg_type, last_msg_sender, last_sender_display_name
                FROM SessionTable
                WHERE last_timestamp > 0
                ORDER BY last_timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    sessions = []
    for row in rows:
        internal_name = _bounded_text(row["username"], MAX_LABEL_LENGTH)
        contact = contacts_by_username.get(internal_name)
        display = contact.display_name if contact else "Unnamed contact"
        contact_id = contact.contact_id if contact else f"contact-{hashlib.sha256(internal_name.encode()).hexdigest()[:16]}"
        sender_internal = _bounded_text(row["last_msg_sender"], MAX_LABEL_LENGTH)
        sender_contact = contacts_by_username.get(sender_internal)
        sender = sender_contact.display_name if sender_contact else _bounded_text(
            row["last_sender_display_name"], MAX_LABEL_LENGTH
        )
        message_type = _type_label(row["last_msg_type"])
        summary = _safe_message_content(row["summary"]) if _base_message_type(row["last_msg_type"]) == 1 else None
        if summary and ":\n" in summary:
            summary = summary.split(":\n", 1)[1]
        sessions.append(
            {
                "contact_id": contact_id,
                "display_name": display,
                "is_group": contact.is_group if contact else False,
                "unread": int(row["unread_count"] or 0),
                "last_message_type": message_type,
                "last_message": summary,
                "last_message_omitted": summary is None,
                "sender": sender,
                "timestamp": int(row["last_timestamp"] or 0),
                "time_utc": _iso_timestamp(row["last_timestamp"]),
            }
        )
    return {"count": len(sessions), "sessions": sessions}


def _contacts_and_messages(root: Path) -> tuple[Path, list[Path]]:
    contact_source = _validate_database(root, Path("contact/contact.db"))
    messages = discover_message_databases(root)
    if not messages:
        raise AdapterError("database_unavailable", "No selected message database is available.")
    return contact_source, messages


def command_history(
    root: Path,
    chat: str,
    start_value: str | None,
    end_value: str | None,
    limit: int,
    offset: int,
) -> dict:
    contact_source, message_sources = _contacts_and_messages(root)
    sources = [contact_source, *message_sources]
    with snapshot_databases(sources) as copies:
        contacts, by_username = _load_contacts_from_copy(contact_source, copies)
        contact = resolve_contact(chat, contacts)
        rows = _collect_history(
            contact,
            by_username,
            message_sources,
            copies,
            _parse_time(start_value),
            _parse_time(end_value, end_of_day=True),
            limit,
            offset,
        )
    return {"contact": contact.public(), "count": len(rows), "messages": rows}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def command_search(
    root: Path,
    keyword: str,
    chat: str | None,
    start_value: str | None,
    end_value: str | None,
    limit: int,
    offset: int,
) -> dict:
    if not keyword:
        raise AdapterError("invalid_query", "A non-empty search keyword is required.")
    contact_source, message_sources = _contacts_and_messages(root)
    sources = [contact_source, *message_sources]
    with snapshot_databases(sources) as copies:
        contacts, by_username = _load_contacts_from_copy(contact_source, copies)
        selected = resolve_contact(chat, contacts) if chat else None
        start = _parse_time(start_value)
        end = _parse_time(end_value, end_of_day=True)
        results = []
        for source in message_sources:
            with connect_readonly(copies[source]) as connection:
                tables = [_message_table(selected.username)] if selected else _message_tables(connection)
                name_ids = _name_to_id(connection)
                for table in tables:
                    if not _table_exists(connection, table):
                        continue
                    username = selected.username if selected else _username_for_table(table, connection, contacts)
                    contact = by_username.get(username)
                    if contact is None:
                        continue
                    columns = _message_columns(connection, table)
                    content_column = columns["message_content"]
                    if content_column is None:
                        continue
                    clauses, parameters = _where_for_time(columns, start, end)
                    clauses.extend(
                        (
                            f"([{columns['local_type']}] & 4294967295) = 1",
                            f"[{content_column}] LIKE ? ESCAPE '\\'",
                        )
                    )
                    parameters.extend((f"%{_escape_like(keyword)}%", limit + offset))
                    expressions = (
                        _select_expression(columns["local_id"], "local_id"),
                        _select_expression(columns["local_type"], "local_type"),
                        _select_expression(columns["create_time"], "create_time"),
                        _select_expression(columns["real_sender_id"], "real_sender_id"),
                        _select_expression(content_column, "message_content"),
                    )
                    sql = (
                        f"SELECT {', '.join(expressions)} FROM [{table}] "
                        f"WHERE {' AND '.join(clauses)} ORDER BY [create_time] DESC LIMIT ?"
                    )
                    for row in connection.execute(sql, parameters):
                        item = _message_row(row, contact, by_username, name_ids)
                        content = item.get("content")
                        if content is not None and keyword.casefold() in content.casefold():
                            item["contact"] = contact.public()
                            results.append(item)
        results.sort(key=lambda item: (item["timestamp"], item["message_id"]), reverse=True)
        page = results[offset : offset + limit]
        page.sort(key=lambda item: (item["timestamp"], item["message_id"]))
    return {"keyword": keyword, "count": len(page), "messages": page}


def command_stats(
    root: Path,
    chat: str,
    start_value: str | None,
    end_value: str | None,
) -> dict:
    contact_source, message_sources = _contacts_and_messages(root)
    sources = [contact_source, *message_sources]
    with snapshot_databases(sources) as copies:
        contacts, by_username = _load_contacts_from_copy(contact_source, copies)
        contact = resolve_contact(chat, contacts)
        table = _message_table(contact.username)
        start = _parse_time(start_value)
        end = _parse_time(end_value, end_of_day=True)
        type_counts: Counter[str] = Counter()
        sender_counts: Counter[str] = Counter()
        hourly = {str(hour): 0 for hour in range(24)}
        total = 0
        for source in message_sources:
            with connect_readonly(copies[source]) as connection:
                if not _table_exists(connection, table):
                    continue
                columns = _message_columns(connection, table)
                clauses, parameters = _where_for_time(columns, start, end)
                where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                for row in connection.execute(
                    f"SELECT [{columns['local_type']}], COUNT(*) FROM [{table}]{where} GROUP BY [{columns['local_type']}]",
                    parameters,
                ):
                    count = int(row[1] or 0)
                    type_counts[_type_label(row[0])] += count
                    total += count
                sender_column = columns["real_sender_id"]
                if sender_column:
                    name_ids = _name_to_id(connection)
                    for row in connection.execute(
                        f"SELECT [{sender_column}], COUNT(*) FROM [{table}]{where} GROUP BY [{sender_column}]",
                        parameters,
                    ):
                        try:
                            sender_username = name_ids.get(int(row[0] or 0), "")
                        except (TypeError, ValueError):
                            sender_username = ""
                        sender_contact = by_username.get(sender_username)
                        sender = sender_contact.display_name if sender_contact else contact.display_name
                        sender_counts[sender] += int(row[1] or 0)
                for row in connection.execute(
                    f"""
                    SELECT strftime('%H', [{columns['create_time']}], 'unixepoch'), COUNT(*)
                    FROM [{table}]{where}
                    GROUP BY 1
                    """,
                    parameters,
                ):
                    if row[0] is not None:
                        hourly[str(int(row[0]))] += int(row[1] or 0)
    return {
        "contact": contact.public(),
        "total": total,
        "type_breakdown": dict(type_counts.most_common()),
        "top_senders": [
            {"display_name": name, "count": count}
            for name, count in sender_counts.most_common(10)
        ],
        "hourly_utc": hourly,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", required=True, help="Absolute path to the explicitly selected Vault root")
    parser.add_argument(
        "--allow-private-content",
        action="store_true",
        help="Required on each invocation that returns contact or message data",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Return metadata-only Vault diagnostics")

    contacts = subparsers.add_parser("contacts", help="List or filter contacts")
    contacts.add_argument("--query")
    contacts.add_argument("--limit", type=_positive_limit, default=50)

    sessions = subparsers.add_parser("sessions", help="List recent sessions")
    sessions.add_argument("--limit", type=_positive_limit, default=20)

    history = subparsers.add_parser("history", help="Return history for one unambiguous contact")
    history.add_argument("chat", help="Display name or contact_id")
    history.add_argument("--start")
    history.add_argument("--end")
    history.add_argument("--limit", type=_positive_limit, default=100)
    history.add_argument("--offset", type=_nonnegative, default=0)

    search = subparsers.add_parser("search", help="Search text history")
    search.add_argument("keyword")
    search.add_argument("--chat", help="Optional display name or contact_id")
    search.add_argument("--start")
    search.add_argument("--end")
    search.add_argument("--limit", type=_positive_limit, default=100)
    search.add_argument("--offset", type=_nonnegative, default=0)

    stats = subparsers.add_parser("stats", help="Return message statistics for one contact")
    stats.add_argument("chat", help="Display name or contact_id")
    stats.add_argument("--start")
    stats.add_argument("--end")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = resolve_vault_root(args.vault_root)
        if args.command != "status" and not args.allow_private_content:
            raise AdapterError(
                "consent_required",
                "This command requires --allow-private-content on the current invocation.",
            )
        if args.command == "status":
            result = command_status(root)
        elif args.command == "contacts":
            result = command_contacts(root, args.query, args.limit)
        elif args.command == "sessions":
            result = command_sessions(root, args.limit)
        elif args.command == "history":
            result = command_history(root, args.chat, args.start, args.end, args.limit, args.offset)
        elif args.command == "search":
            result = command_search(root, args.keyword, args.chat, args.start, args.end, args.limit, args.offset)
        elif args.command == "stats":
            result = command_stats(root, args.chat, args.start, args.end)
        else:  # pragma: no cover - argparse guarantees a known command
            raise AdapterError("invalid_command", "The requested command is not supported.")
        print(json.dumps({"ok": True, "command": args.command, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except AdapterError as exc:
        payload = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        if exc.details:
            payload["error"]["details"] = exc.details
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 3
    except (OSError, sqlite3.Error):
        payload = {
            "ok": False,
            "error": {"code": "query_failed", "message": "The read-only query failed safely."},
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 3


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
