"""Read-only queries for decrypted Windows WeChat 4.x vault copies."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from vault_common import (
    VaultError, atomic_json, find_db, iter_message_dbs, load_json,
    quote_identifier, readonly_connect, require_explicit_dir, table_columns,
    table_names, vault_home,
)


TYPE_LABELS = {
    1: "text", 3: "image", 34: "voice", 37: "contact-card", 42: "contact-card",
    43: "video", 47: "sticker", 48: "location", 49: "app", 50: "call",
    10000: "system",
}


def parse_time(value: str | None, end: bool = False) -> int | None:
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return int(text)
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d" and end:
                parsed += dt.timedelta(days=1, microseconds=-1)
            return int(parsed.timestamp())
        except ValueError:
            pass
    raise VaultError(f"invalid time: {value}")


def decode_blob(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes):
        return str(value)
    for raw in (value,):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(value).decode("utf-8", "replace")
    except Exception:
        return value.decode("utf-8", "replace")


def emit(value, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, list):
        for item in value:
            print(" | ".join(f"{key}={val}" for key, val in item.items() if val not in (None, "")))
    elif isinstance(value, dict):
        for key, val in value.items():
            print(f"{key}: {val}")
    else:
        print(value)


def contact_db(root: Path) -> Path:
    path = find_db(root, ["contact.db"])
    if path is None:
        raise VaultError("contact.db not found")
    return path


def load_contacts(root: Path) -> list[dict]:
    with readonly_connect(contact_db(root)) as con:
        if "contact" not in table_names(con):
            raise VaultError("contact table not found")
        rows = con.execute(
            "SELECT id,username,alias,remark,nick_name,local_type,delete_flag,"
            "is_in_chat_room,chat_room_type FROM contact"
        ).fetchall()
    return [dict(row) for row in rows]


def display_name(contact: dict) -> str:
    return contact.get("remark") or contact.get("nick_name") or contact.get("alias") or contact.get("username") or ""


def resolve_contact(root: Path, query: str) -> dict:
    needle = query.casefold()
    contacts = load_contacts(root)
    exact = [item for item in contacts if needle in {
        str(item.get(key) or "").casefold() for key in ("username", "alias", "remark", "nick_name")
    }]
    if len(exact) == 1:
        return exact[0]
    partial = [item for item in contacts if any(
        needle in str(item.get(key) or "").casefold()
        for key in ("username", "alias", "remark", "nick_name")
    )]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise VaultError(f"contact not found: {query}")
    names = ", ".join(display_name(item) for item in partial[:8])
    raise VaultError(f"contact is ambiguous: {query} ({names})")


def command_status(root: Path) -> dict:
    expected = ["contact.db", "session.db", "favorite.db", "sns.db", "message_resource.db"]
    found = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.db"))
    return {
        "decrypted_root": str(root),
        "database_count": len(found),
        "message_shards": len(iter_message_dbs(root)),
        "components": {name: any(path.endswith(name) for path in found) for name in expected},
        "databases": found,
    }


def command_contacts(root: Path, query: str | None, limit: int) -> list[dict]:
    rows = load_contacts(root)
    if query:
        needle = query.casefold()
        rows = [row for row in rows if any(
            needle in str(row.get(key) or "").casefold()
            for key in ("username", "alias", "remark", "nick_name")
        )]
    rows.sort(key=lambda row: display_name(row).casefold())
    return [{**row, "display_name": display_name(row)} for row in rows[:limit]]


def command_members(root: Path, group: str) -> dict:
    contact = resolve_contact(root, group)
    with readonly_connect(contact_db(root)) as con:
        room = con.execute("SELECT id,username,owner FROM chat_room WHERE username=?", (contact["username"],)).fetchone()
        if room is None:
            raise VaultError(f"not a group chat: {group}")
        members = con.execute(
            "SELECT c.username,c.alias,c.remark,c.nick_name FROM chatroom_member m "
            "JOIN contact c ON c.id=m.member_id WHERE m.room_id=?", (room["id"],)
        ).fetchall()
    items = [dict(row) for row in members]
    return {"group": contact["username"], "name": display_name(contact), "owner": room["owner"], "members": items}


def session_db(root: Path) -> Path:
    path = find_db(root, ["session.db"])
    if path is None:
        raise VaultError("session.db not found")
    return path


def command_sessions(root: Path, unread: bool, limit: int) -> list[dict]:
    contacts = {row["username"]: row for row in load_contacts(root)}
    where = "WHERE unread_count>0" if unread else ""
    with readonly_connect(session_db(root)) as con:
        rows = con.execute(
            "SELECT username,unread_count,summary,last_timestamp,sort_timestamp,last_msg_type,"
            "last_msg_sub_type,last_sender_display_name FROM SessionTable " + where +
            " ORDER BY sort_timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["name"] = display_name(contacts.get(item["username"], {"username": item["username"]}))
        item["summary"] = decode_blob(item["summary"])
        result.append(item)
    return result


def _message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def _candidate_tables(root: Path, contact: dict | None) -> list[tuple[Path, str, str]]:
    selected = _message_table(contact["username"]) if contact else None
    result = []
    contacts = load_contacts(root) if contact is None else [contact]
    by_table = {_message_table(item["username"]).casefold(): item["username"] for item in contacts}
    for path in iter_message_dbs(root):
        with readonly_connect(path) as con:
            for table in table_names(con, "Msg_"):
                if selected is None or table.casefold() == selected.casefold():
                    result.append((path, table, by_table.get(table.casefold(), "")))
    return result


def _message_type(local_type: int) -> tuple[int, int]:
    value = int(local_type or 0)
    if value > 0xFFFF:
        return value & 0xFFFF, value >> 16
    return value, 0


def _rows_from_table(
    path: Path, table: str, username: str, start: int | None, end: int | None,
    keyword: str | None, type_name: str | None,
) -> list[dict]:
    conditions = []
    params: list[object] = []
    if start is not None:
        conditions.append("create_time>=?")
        params.append(start)
    if end is not None:
        conditions.append("create_time<=?")
        params.append(end)
    sql = (
        "SELECT local_id,server_id,local_type,sort_seq,real_sender_id,create_time,status,"
        "message_content,compress_content,source,packed_info_data FROM " + quote_identifier(table)
    )
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    with readonly_connect(path) as con:
        rows = con.execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        content = decode_blob(item.get("message_content")) or decode_blob(item.get("compress_content"))
        base_type, subtype = _message_type(item.get("local_type") or 0)
        label = TYPE_LABELS.get(base_type, f"type-{base_type}")
        if keyword and keyword.casefold() not in content.casefold():
            continue
        if type_name and label != type_name:
            continue
        item.update({
            "chat": username, "content": content, "type": label, "subtype": subtype,
            "database": path.name, "table": table,
        })
        for binary in ("message_content", "compress_content", "source", "packed_info_data"):
            item.pop(binary, None)
        result.append(item)
    return result


def collect_messages(
    root: Path, chat: str | None, start: int | None, end: int | None,
    keyword: str | None, type_name: str | None, limit: int, offset: int,
) -> list[dict]:
    contact = resolve_contact(root, chat) if chat else None
    rows = []
    for path, table, username in _candidate_tables(root, contact):
        rows.extend(_rows_from_table(path, table, username or (contact or {}).get("username", ""), start, end, keyword, type_name))
    rows.sort(key=lambda row: (row.get("sort_seq") or row.get("create_time") or 0, row.get("local_id") or 0), reverse=True)
    return rows[offset : offset + limit]


def command_stats(root: Path, chat: str, start: int | None, end: int | None) -> dict:
    rows = collect_messages(root, chat, start, end, None, None, 1_000_000, 0)
    by_type = Counter(row["type"] for row in rows)
    by_sender = Counter(str(row.get("real_sender_id") or "unknown") for row in rows)
    return {
        "chat": resolve_contact(root, chat)["username"],
        "message_count": len(rows),
        "by_type": dict(by_type.most_common()),
        "by_sender_id": dict(by_sender.most_common()),
        "first_timestamp": min((row["create_time"] for row in rows), default=None),
        "last_timestamp": max((row["create_time"] for row in rows), default=None),
    }


def command_favorites(root: Path, query: str | None, limit: int) -> list[dict]:
    path = find_db(root, ["favorite.db"])
    if path is None:
        raise VaultError("favorite.db not found")
    with readonly_connect(path) as con:
        rows = con.execute(
            "SELECT local_id,server_id,type,update_time,content,fromusr,realchatname "
            "FROM fav_db_item ORDER BY update_time DESC"
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = decode_blob(item["content"])
        if query and query.casefold() not in item["content"].casefold():
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _xml_value(root: ET.Element, *paths: str) -> str:
    for path in paths:
        value = root.findtext(path)
        if value:
            return value
    return ""


def command_moments(root: Path, username: list[str] | None, keyword: str | None, limit: int) -> list[dict]:
    path = find_db(root, ["sns.db"])
    if path is None:
        raise VaultError("sns.db not found")
    conditions = []
    params: list[object] = []
    if username:
        conditions.append("user_name IN (" + ",".join("?" for _ in username) + ")")
        params.extend(username)
    # pack_info_buf is an opaque protobuf and may be declared as TEXT in some
    # builds despite containing arbitrary bytes. It is intentionally excluded.
    sql = "SELECT tid,user_name,content FROM SnsTimeLine"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    with readonly_connect(path) as con:
        rows = con.execute(sql, params).fetchall()
    result = []
    for row in rows:
        raw = decode_blob(row["content"])
        if keyword and keyword.casefold() not in raw.casefold():
            continue
        item = {"tid": row["tid"], "username": row["user_name"], "raw": raw}
        try:
            xml = ET.fromstring(raw)
            location = xml.find(".//location")
            item.update({
                "text": _xml_value(xml, ".//contentDesc", ".//content"),
                "create_time": _xml_value(xml, ".//createTime"),
                "location": "" if location is None else (location.get("poiName") or location.text or ""),
            })
        except ET.ParseError:
            item["text"] = raw
        result.append(item)
        if len(result) >= limit:
            break
    return result


def command_new_messages(root: Path, state_file: Path, limit: int) -> dict:
    state = load_json(state_file, {"last_timestamp": 0})
    since = int(state.get("last_timestamp", 0))
    rows = collect_messages(root, None, since + 1, None, None, None, limit, 0)
    newest = max((int(row["create_time"]) for row in rows), default=since)
    atomic_json(state_file, {"last_timestamp": newest}, private=True)
    return {"since": since, "newest": newest, "messages": rows}


def command_resources(root: Path, chat: str, local_id: int | None, limit: int) -> dict:
    path = find_db(root, ["message_resource.db"])
    if path is None:
        raise VaultError("message_resource.db not found")
    with readonly_connect(path) as con:
        chat_row = con.execute(
            "SELECT rowid,user_name FROM ChatName2Id WHERE user_name=?", (chat,)
        ).fetchone()
        if chat_row is None:
            try:
                contact = resolve_contact(root, chat)
            except VaultError:
                return {"chat": chat, "resources": []}
            chat_row = con.execute(
                "SELECT rowid,user_name FROM ChatName2Id WHERE user_name=?", (contact["username"],)
            ).fetchone()
        if chat_row is None:
            return {"chat": chat, "resources": []}
        conditions = ["i.chat_id=?"]
        params: list[object] = [chat_row[0]]
        if local_id is not None:
            conditions.append("i.message_local_id=?")
            params.append(local_id)
        params.append(limit)
        rows = con.execute(
            "SELECT i.message_id,i.message_local_type,i.message_create_time,"
            "i.message_local_id,i.message_svr_id,d.resource_id,d.type AS resource_type,"
            "d.size,d.status,d.data_index FROM MessageResourceInfo i "
            "LEFT JOIN MessageResourceDetail d ON d.message_id=i.message_id WHERE "
            + " AND ".join(conditions)
            + " ORDER BY i.message_create_time DESC LIMIT ?",
            params,
        ).fetchall()
    return {"chat": chat_row["user_name"], "resources": [dict(row) for row in rows]}


def command_digest(root: Path, args: argparse.Namespace) -> dict:
    rows = collect_messages(
        root, args.group, parse_time(args.start), parse_time(args.end, True),
        None, None, args.limit, 0,
    )
    contact = resolve_contact(root, args.group)
    destination = Path(args.output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter(row["type"] for row in rows)
    lines = [
        f"# {display_name(contact)} digest source",
        "",
        f"- Messages: {len(rows)}",
        f"- Types: {json.dumps(dict(counts), ensure_ascii=False)}",
        "",
        "## Timeline",
        "",
    ]
    for row in reversed(rows):
        stamp = dt.datetime.fromtimestamp(row["create_time"]).isoformat(sep=" ", timespec="seconds")
        lines.append(f"- {stamp} [{row['type']}] {row['content']}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(destination), "message_count": len(rows), "by_type": dict(counts)}


def export_messages(root: Path, args: argparse.Namespace) -> dict:
    rows = collect_messages(
        root, args.chat, parse_time(args.start_time), parse_time(args.end_time, True),
        None, args.type, args.limit, 0,
    )
    destination = Path(args.output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    title = display_name(resolve_contact(root, args.chat))
    lines = [f"# {title}", ""] if args.export_format == "markdown" else []
    for row in reversed(rows):
        stamp = dt.datetime.fromtimestamp(row["create_time"]).isoformat(sep=" ", timespec="seconds")
        lines.append(f"- {stamp} [{row['type']}] {row['content']}" if args.export_format == "markdown" else f"{stamp}\t{row['type']}\t{row['content']}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(destination), "message_count": len(rows)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decrypted-root", required=True, help="Explicit decrypted vault root")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name, unread in (("sessions", False), ("unread", True)):
        p = sub.add_parser(name); p.add_argument("--limit", type=int, default=20); p.set_defaults(unread=unread)
    p = sub.add_parser("new-messages"); p.add_argument("--limit", type=int, default=100); p.add_argument("--vault-home")
    p = sub.add_parser("contacts"); p.add_argument("--query"); p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("members"); p.add_argument("group")
    for name in ("history", "search"):
        p = sub.add_parser(name)
        if name == "history": p.add_argument("chat")
        else: p.add_argument("keyword"); p.add_argument("--chat")
        p.add_argument("--start-time"); p.add_argument("--end-time"); p.add_argument("--type", choices=sorted(set(TYPE_LABELS.values())))
        p.add_argument("--limit", type=int, default=50); p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("stats"); p.add_argument("chat"); p.add_argument("--start-time"); p.add_argument("--end-time")
    p = sub.add_parser("favorites"); p.add_argument("--query"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("moments"); p.add_argument("--username", action="append"); p.add_argument("--keyword"); p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("resources"); p.add_argument("chat"); p.add_argument("--local-id", type=int); p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("export"); p.add_argument("chat"); p.add_argument("--output", required=True); p.add_argument("--export-format", choices=["markdown", "txt"], default="markdown"); p.add_argument("--start-time"); p.add_argument("--end-time"); p.add_argument("--type", choices=sorted(set(TYPE_LABELS.values()))); p.add_argument("--limit", type=int, default=500)
    p = sub.add_parser("digest-source"); p.add_argument("group"); p.add_argument("--output", required=True); p.add_argument("--start"); p.add_argument("--end"); p.add_argument("--limit", type=int, default=5000)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = require_explicit_dir(args.decrypted_root, "--decrypted-root")
        if args.command == "status": result = command_status(root)
        elif args.command in ("sessions", "unread"): result = command_sessions(root, args.unread, args.limit)
        elif args.command == "new-messages": result = command_new_messages(root, vault_home(args.vault_home) / "query-state.json", args.limit)
        elif args.command == "contacts": result = command_contacts(root, args.query, args.limit)
        elif args.command == "members": result = command_members(root, args.group)
        elif args.command in ("history", "search"):
            result = collect_messages(root, getattr(args, "chat", None), parse_time(args.start_time), parse_time(args.end_time, True), getattr(args, "keyword", None), args.type, args.limit, args.offset)
        elif args.command == "stats": result = command_stats(root, args.chat, parse_time(args.start_time), parse_time(args.end_time, True))
        elif args.command == "favorites": result = command_favorites(root, args.query, args.limit)
        elif args.command == "moments": result = command_moments(root, args.username, args.keyword, args.limit)
        elif args.command == "resources": result = command_resources(root, args.chat, args.local_id, args.limit)
        elif args.command == "export": result = export_messages(root, args)
        elif args.command == "digest-source": result = command_digest(root, args)
        else: raise VaultError(f"unsupported command: {args.command}")
        emit(result, args.format)
    except (OSError, VaultError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
