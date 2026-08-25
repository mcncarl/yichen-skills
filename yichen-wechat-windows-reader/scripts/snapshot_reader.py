#!/usr/bin/env python3
"""Read-only analyzer for user-supplied plaintext Weixin 4.x snapshots."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Iterator

try:
    import zstandard
except ImportError:  # reported by validate when compressed rows are encountered
    zstandard = None

PRIVATE_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "YichenWeChatVault"
DEFAULT_EXPORTS = PRIVATE_ROOT / "exports"
REQUIRED_DATABASES = (
    "contact/contact.db",
    "session/session.db",
    "favorite/favorite.db",
    "sns/sns.db",
    "message/message_resource.db",
)
MESSAGE_PATTERNS = ("message_*.db", "biz_message_*.db")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class ReaderError(RuntimeError):
    pass


@contextmanager
def connect_read_only(path: Path) -> Iterator[sqlite3.Connection]:
    """Open SQLite in immutable/query-only mode; never create journals beside input."""
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        yield con
    finally:
        con.close()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info([{table}])")}


def message_databases(root: Path) -> list[Path]:
    found: set[Path] = set()
    message_root = root / "message"
    for pattern in MESSAGE_PATTERNS:
        found.update(message_root.glob(pattern))
    return sorted(p for p in found if p.is_file())


def validate_snapshot(root: Path) -> dict:
    root = root.resolve()
    missing = [item for item in REQUIRED_DATABASES if not (root / item).is_file()]
    msg_dbs = message_databases(root)
    if not msg_dbs:
        missing.append("message/{message_*.db|biz_message_*.db}")
    checked: list[str] = []
    errors: list[str] = []
    for rel in [*REQUIRED_DATABASES]:
        path = root / rel
        if not path.is_file():
            continue
        try:
            with connect_read_only(path) as con:
                result = con.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    errors.append(f"{rel}: quick_check={result}")
                checked.append(rel)
        except sqlite3.Error as exc:
            errors.append(f"{rel}: {exc}")
    for path in msg_dbs:
        rel = path.relative_to(root).as_posix()
        try:
            with connect_read_only(path) as con:
                result = con.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    errors.append(f"{rel}: quick_check={result}")
                checked.append(rel)
        except sqlite3.Error as exc:
            errors.append(f"{rel}: {exc}")
    return {"valid": not missing and not errors, "missing": missing, "errors": errors, "checked": sorted(checked), "message_families": sorted({p.name.split("_")[0] for p in msg_dbs})}


def require_valid(root: Path) -> None:
    report = validate_snapshot(root)
    if not report["valid"]:
        raise ReaderError(json.dumps(report, ensure_ascii=False))


def contact_records(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    with connect_read_only(root / "contact/contact.db") as con:
        if not table_exists(con, "contact"):
            raise ReaderError("contact/contact.db lacks table 'contact'")
        for raw in con.execute("SELECT * FROM contact"):
            row = dict(raw)
            username = str(row.get("username") or row.get("userName") or "")
            if not username:
                continue
            display = str(row.get("remark") or row.get("nick_name") or row.get("nickname") or row.get("alias") or "未命名会话")
            chat_id = hashlib.sha256(username.encode("utf-8")).hexdigest()[:24]
            result[username] = {"chat_id": chat_id, "display_name": display, "kind": "group" if "@chatroom" in username else "contact"}
    return result


def select_chat(root: Path, chat_id: str) -> tuple[str, dict]:
    matches = [(username, item) for username, item in contact_records(root).items() if item["chat_id"] == chat_id]
    if len(matches) != 1:
        raise ReaderError("chat_id must match exactly one chat; run 'chats' and choose a listed ID")
    return matches[0]


def decode(value, compressed=None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    data = bytes(value)
    if data.startswith(ZSTD_MAGIC) or compressed == 4:
        if zstandard is None:
            raise ReaderError("zstandard is required to decode compressed message content")
        data = zstandard.ZstdDecompressor().decompress(data, max_output_size=8_000_000)
    return data.decode("utf-8", errors="replace")


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def table_mapping(con: sqlite3.Connection, table: str) -> dict[str, str]:
    available = columns(con, table)
    choices = {
        "local_id": ("local_id", "id"), "server_id": ("server_id",),
        "local_type": ("local_type", "type"), "create_time": ("create_time", "timestamp"),
        "sender_id": ("real_sender_id", "sender_id"), "content": ("message_content", "content"),
        "compressed": ("compress_content", "WCDB_CT_message_content"), "compression_flag": ("WCDB_CT_message_content",),
    }
    return {key: next((name for name in names if name in available), "") for key, names in choices.items()}


def sender_map(con: sqlite3.Connection) -> dict[int, str]:
    if not table_exists(con, "Name2Id"):
        return {}
    try:
        return {int(row["rowid"]): str(row["user_name"]) for row in con.execute("SELECT rowid,user_name FROM Name2Id") if row["user_name"]}
    except sqlite3.Error:
        return {}


def load_account_identity(root: Path) -> str:
    manifest = root / "snapshot-manifest.json"
    if not manifest.is_file():
        return ""
    try:
        value = json.loads(manifest.read_text(encoding="utf-8")).get("account_username", "")
        return str(value)
    except (OSError, ValueError, TypeError):
        raise ReaderError("snapshot-manifest.json is invalid")


def iter_messages(root: Path, username: str) -> Iterator[dict]:
    contacts = contact_records(root)
    account = load_account_identity(root)
    table = message_table(username)
    for db_path in message_databases(root):
        with connect_read_only(db_path) as con:
            if not table_exists(con, table):
                continue
            mapping = table_mapping(con, table)
            select = []
            for key in ("local_id", "server_id", "local_type", "create_time", "sender_id", "content", "compressed", "compression_flag"):
                select.append(f"[{mapping[key]}] AS [{key}]" if mapping[key] else f"NULL AS [{key}]")
            names = sender_map(con)
            for row in con.execute(f"SELECT {','.join(select)} FROM [{table}] ORDER BY [create_time] ASC"):
                content = decode(row["content"], row["compression_flag"]) or decode(row["compressed"], row["compression_flag"])
                sender_username = names.get(int(row["sender_id"]), "") if row["sender_id"] is not None else ""
                if not sender_username and ":\n" in content:
                    possible, rest = content.split(":\n", 1)
                    if possible.startswith("wxid_"):
                        sender_username, content = possible, rest
                direction = "unknown"
                if account and sender_username:
                    direction = "outgoing" if sender_username == account else "incoming"
                sender = contacts.get(sender_username, {}).get("display_name") or ("我" if direction == "outgoing" else "未知成员")
                timestamp = int(row["create_time"] or 0)
                yield {"message_id": str(row["server_id"] or row["local_id"] or ""), "time": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "", "timestamp": timestamp, "type": int(row["local_type"] or 0) & 0xFFFFFFFF, "sender": sender, "direction": direction, "content": content}


def filtered_messages(root: Path, chat_id: str, keyword: str | None, start: int | None, end: int | None, limit: int) -> list[dict]:
    username, _ = select_chat(root, chat_id)
    matches = []
    for item in iter_messages(root, username):
        if start is not None and item["timestamp"] < start:
            continue
        if end is not None and item["timestamp"] > end:
            continue
        if keyword is not None and keyword.casefold() not in item["content"].casefold():
            continue
        matches.append(item)
    matches.sort(key=lambda item: (item["timestamp"], item["message_id"]))
    return matches[-limit:] if limit else matches


def parse_date(value: str | None, end=False) -> int | None:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    if end:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp())


def render_markdown(chat: dict, messages: list[dict]) -> str:
    lines = [f"# {chat['display_name']}", "", f"会话 ID：`{chat['chat_id']}`", ""]
    for item in messages:
        lines.extend([f"## {item['time']} · {item['sender']} · {item['direction']}", "", item["content"], ""])
    return "\n".join(lines)


def require_safe_output(path: Path, confirmed: bool) -> Path:
    resolved = path.expanduser().resolve()
    private = DEFAULT_EXPORTS.resolve()
    try:
        resolved.relative_to(private)
    except ValueError:
        if not confirmed:
            raise ReaderError(f"output is outside the private default; repeat with --confirm-external-output: {resolved}")
    return resolved


def atomic_write(path: Path, content: str, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ReaderError("output exists; pass --overwrite to replace it")
    fd, name = tempfile.mkstemp(prefix=".wechat-reader-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path, help="user-supplied plaintext snapshot root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    chats = sub.add_parser("chats"); chats.add_argument("--query", default="")
    for name in ("history", "search"):
        cmd = sub.add_parser(name); cmd.add_argument("chat_id"); cmd.add_argument("--start"); cmd.add_argument("--end"); cmd.add_argument("--limit", type=int, default=500)
        if name == "search": cmd.add_argument("keyword")
    export = sub.add_parser("export"); export.add_argument("chat_id"); export.add_argument("--start"); export.add_argument("--end"); export.add_argument("--limit", type=int, default=5000); export.add_argument("--output", type=Path); export.add_argument("--confirm-external-output", action="store_true"); export.add_argument("--overwrite", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = args.snapshot.resolve()
    try:
        if args.command == "validate":
            report = validate_snapshot(root); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["valid"] else 2
        require_valid(root)
        if args.command == "chats":
            query = args.query.casefold(); items = [item for item in contact_records(root).values() if not query or query in item["display_name"].casefold()]
            print(json.dumps(items, ensure_ascii=False, indent=2)); return 0
        messages = filtered_messages(root, args.chat_id, getattr(args, "keyword", None), parse_date(args.start), parse_date(args.end, True), args.limit)
        _, chat = select_chat(root, args.chat_id)
        if args.command == "export":
            target = args.output or DEFAULT_EXPORTS / f"{chat['chat_id']}.md"
            target = require_safe_output(target, args.confirm_external_output)
            atomic_write(target, render_markdown(chat, messages), args.overwrite)
            print(json.dumps({"output": str(target), "messages": len(messages)}, ensure_ascii=False)); return 0
        print(json.dumps({"chat": chat, "messages": messages}, ensure_ascii=False, indent=2)); return 0
    except (ReaderError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
