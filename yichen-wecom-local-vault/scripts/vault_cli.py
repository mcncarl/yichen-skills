#!/usr/bin/env python3
"""Read-only command line interface for decrypted WeCom local snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from wecom_common import (
    choose_dataset,
    dataset_id,
    discover_datasets,
    inspect_dataset,
    iter_databases,
    key_for_database,
    latest_snapshot,
    load_key_file,
    utc_now,
    vault_root,
)
from wecom_crypto import PAGE_SIZE, database_format, decrypt_database


MESSAGE_TABLES = ("message_table", "message_small_table", "kf_message_tableV1")
CORE_NAMES = ("message.db", "session.db", "user.db")
TYPE_NAMES = {
    0: "文本/混合",
    2: "文本",
    4: "图片",
    7: "语音",
    15: "图片/文件",
    38: "应用消息",
    40: "通话/音视频",
    503: "状态",
    1011: "会议通知",
}


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def output(value, fmt: str = "json") -> None:
    if fmt == "json":
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)


def snapshot_path(value: str | None) -> Path:
    path = Path(value).expanduser() if value else latest_snapshot()
    if not path.is_dir():
        raise SystemExit(f"快照目录不存在: {path}")
    return path


def parse_time(value: str | None) -> int | None:
    if not value:
        return None
    for form in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(value, form).timestamp())
        except ValueError:
            pass
    raise SystemExit(f"无法解析时间: {value}")


def format_time(value) -> str:
    try:
        stamp = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if stamp > 20_000_000_000:
        stamp //= 1000
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S") if stamp > 0 else ""


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data) and shift < 64:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, position
        shift += 7
    raise ValueError("invalid protobuf varint")


def _clean_text(value: str) -> str:
    value = "".join(character if character in "\n\t" or character.isprintable() else " " for character in value)
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _protobuf_text(data: bytes, depth: int = 0) -> list[str]:
    if depth > 4 or not data:
        return []
    position = 0
    values: list[str] = []
    try:
        while position < len(data):
            tag, position = _read_varint(data, position)
            wire_type = tag & 7
            if tag == 0:
                return []
            if wire_type == 0:
                _, position = _read_varint(data, position)
            elif wire_type == 1:
                position += 8
            elif wire_type == 5:
                position += 4
            elif wire_type == 2:
                length, position = _read_varint(data, position)
                if position + length > len(data):
                    return []
                segment = data[position : position + length]
                position += length
                try:
                    text = _clean_text(segment.decode("utf-8")) if b"\x00" not in segment else ""
                except UnicodeDecodeError:
                    text = ""
                if len(text) >= 2 and not re.fullmatch(r"[0-9a-fA-F]{32,}", text):
                    values.append(text)
                else:
                    values.extend(_protobuf_text(segment, depth + 1))
            else:
                return []
            if position > len(data):
                return []
    except (ValueError, IndexError):
        return []
    deduped = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def decode_content(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return _clean_text(raw)
    data = bytes(raw)
    if not data:
        return ""
    try:
        plain = data.decode("utf-8")
        controls = sum(1 for byte in data if byte < 32 and byte not in (9, 10, 13))
        if controls / len(data) <= 0.08:
            return _clean_text(plain)
    except UnicodeDecodeError:
        pass
    values = _protobuf_text(data)
    if values:
        return "\n".join(values[:12])
    return f"[二进制内容 {len(data)} 字节]"


def load_users(snapshot: Path) -> dict[int, dict]:
    path = snapshot / "user.db"
    users: dict[int, dict] = {}
    if not path.exists():
        return users
    with connect(path) as connection:
        if table_exists(connection, "user_table"):
            columns = table_columns(connection, "user_table")
            wanted = [name for name in ("id", "name", "real_name", "account", "external_corp_name", "external_job") if name in columns]
            if "id" in wanted:
                for row in connection.execute(f'SELECT {",".join(wanted)} FROM user_table'):
                    item = dict(row)
                    try:
                        user_id = int(item["id"])
                    except (TypeError, ValueError):
                        continue
                    display = item.get("real_name") or item.get("name") or item.get("account") or str(user_id)
                    corp = item.get("external_corp_name") or ""
                    if corp and corp not in display:
                        display = f"{display} ({corp})"
                    item["display_name"] = display
                    users[user_id] = item
        if table_exists(connection, "external_user_relation_v3"):
            columns = table_columns(connection, "external_user_relation_v3")
            wanted = [name for name in ("user_id", "remarks", "real_remarks", "corp_remark") if name in columns]
            if "user_id" in wanted:
                for row in connection.execute(f'SELECT {",".join(wanted)} FROM external_user_relation_v3'):
                    item = dict(row)
                    try:
                        user_id = int(item["user_id"])
                    except (TypeError, ValueError):
                        continue
                    display = item.get("real_remarks") or item.get("remarks") or item.get("corp_remark")
                    if display:
                        users.setdefault(user_id, {"id": user_id})["display_name"] = display
    return users


def conversation_kind(conversation_id: str) -> str:
    return {"R": "群聊", "S": "单聊", "M": "微信联系人", "O": "应用/公众号", "Y": "系统会话"}.get(conversation_id[:1], "其他")


def load_sessions(snapshot: Path) -> dict[str, dict]:
    path = snapshot / "session.db"
    sessions: dict[str, dict] = {}
    if not path.exists():
        return sessions
    with connect(path) as connection:
        if not table_exists(connection, "conversation_table"):
            return sessions
        columns = table_columns(connection, "conversation_table")
        wanted = [name for name in ("id", "name", "roomname_remark", "last_message_time", "last_message_id") if name in columns]
        if "id" not in wanted:
            return sessions
        for row in connection.execute(f'SELECT {",".join(wanted)} FROM conversation_table'):
            item = dict(row)
            conversation_id = str(item.get("id") or "")
            if not conversation_id:
                continue
            sessions[conversation_id] = {
                "conversation_id": conversation_id,
                "display_name": item.get("roomname_remark") or item.get("name") or conversation_id,
                "kind": conversation_kind(conversation_id),
                "last_message_time": int(item.get("last_message_time") or 0),
                "last_message_id": int(item.get("last_message_id") or 0),
            }
    return sessions


def load_member_names(snapshot: Path) -> dict[str, dict[int, str]]:
    path = snapshot / "session.db"
    mapping: dict[str, dict[int, str]] = {}
    if not path.exists():
        return mapping
    with connect(path) as connection:
        if table_exists(connection, "conversation_user_table"):
            columns = table_columns(connection, "conversation_user_table")
            if {"conversation_id", "user_id", "nick_name"} <= columns:
                for row in connection.execute("SELECT conversation_id,user_id,nick_name FROM conversation_user_table"):
                    if row["nick_name"]:
                        mapping.setdefault(str(row["conversation_id"]), {})[int(row["user_id"])] = str(row["nick_name"])
    return mapping


def resolve_session(query: str, sessions: dict[str, dict]) -> dict:
    if query in sessions:
        return sessions[query]
    lowered = query.lower()
    exact = [item for item in sessions.values() if item["display_name"].lower() == lowered]
    fuzzy = [item for item in sessions.values() if lowered in item["display_name"].lower() or lowered in item["conversation_id"].lower()]
    matches = exact or fuzzy
    if not matches:
        raise SystemExit(f"找不到会话: {query}")
    if len(matches) > 1:
        names = ", ".join(item["display_name"] for item in matches[:8])
        raise SystemExit(f"会话名称不唯一，请使用 conversation_id: {names}")
    return matches[0]


def iter_messages(snapshot: Path, conversation_id: str | None, start: int | None, end: int | None, keyword: str | None, limit: int) -> list[dict]:
    path = snapshot / "message.db"
    if not path.exists():
        raise SystemExit(f"快照缺少 message.db: {snapshot}")
    sessions = load_sessions(snapshot)
    users = load_users(snapshot)
    members = load_member_names(snapshot)
    messages = []
    with connect(path) as connection:
        for table in MESSAGE_TABLES:
            if not table_exists(connection, table):
                continue
            columns = table_columns(connection, table)
            required = {"conversation_id", "sender_id", "content_type", "send_time"}
            if not required <= columns:
                continue
            fields = [name for name in ("message_id", "server_id", "sequence", "sender_id", "conversation_id", "content_type", "send_time", "flag", "content", "extra_content", "local_extra_content") if name in columns]
            clauses = []
            params = []
            if conversation_id:
                clauses.append("conversation_id=?")
                params.append(conversation_id)
            max_time_row = connection.execute(f'SELECT MAX(send_time) FROM "{table}"').fetchone()
            time_scale = 1000 if max_time_row and int(max_time_row[0] or 0) > 20_000_000_000 else 1
            if start is not None:
                clauses.append("send_time>=?")
                params.append(start * time_scale)
            if end is not None:
                clauses.append("send_time<=?")
                params.append(end * time_scale)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            scan_limit = min(max(limit * 50, 1000), 50000) if keyword else limit
            sql = f'SELECT {",".join(fields)} FROM "{table}"{where} ORDER BY send_time DESC LIMIT ?'
            params.append(scan_limit)
            for row in connection.execute(sql, params):
                item = dict(row)
                cid = str(item.get("conversation_id") or "")
                sender_id = int(item.get("sender_id") or 0)
                content = decode_content(item.get("content")) or decode_content(item.get("extra_content")) or decode_content(item.get("local_extra_content"))
                content_type = int(item.get("content_type") or 0)
                display_content = content or f"[{TYPE_NAMES.get(content_type, f'未知类型 {content_type}')}]"
                if keyword and keyword.lower() not in display_content.lower():
                    continue
                messages.append({
                    "source_table": table,
                    "message_id": int(item.get("message_id") or 0),
                    "server_id": int(item.get("server_id") or 0),
                    "sequence": int(item.get("sequence") or 0),
                    "conversation_id": cid,
                    "conversation": sessions.get(cid, {}).get("display_name") or cid,
                    "sender_id": sender_id,
                    "sender": members.get(cid, {}).get(sender_id) or users.get(sender_id, {}).get("display_name") or (str(sender_id) if sender_id else "系统"),
                    "content_type": content_type,
                    "type_name": TYPE_NAMES.get(content_type, f"未知({content_type})"),
                    "send_time": int(item.get("send_time") or 0),
                    "time": format_time(item.get("send_time")),
                    "content": display_content,
                })
    messages.sort(key=lambda item: (item["send_time"], item["sequence"], item["message_id"]))
    return messages[-limit:]


def command_discover(args) -> None:
    datasets = discover_datasets(args.data_dir)
    result = [{"dataset_id": dataset_id(path), "core_databases": list(CORE_NAMES)} for path in datasets]
    if args.show_paths:
        for item, path in zip(result, datasets):
            item["path"] = str(path)
    output({"count": len(result), "datasets": result})


def command_status(args) -> None:
    dataset = choose_dataset(args.data_dir)
    summary = inspect_dataset(dataset)
    if args.show_paths:
        summary["path"] = str(dataset)
    output(summary)


def decrypt_dataset(explicit: str | None, keys: dict) -> Path:
    if explicit:
        return choose_dataset(explicit)
    expected = keys.get("dataset_id")
    if expected:
        matches = [path for path in discover_datasets() if dataset_id(path) == expected]
        if len(matches) == 1:
            return matches[0]
    return choose_dataset(None)


def command_decrypt(args) -> None:
    keys = load_key_file(Path(args.key_file).expanduser() if args.key_file else None)
    dataset = decrypt_dataset(args.data_dir, keys)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    destination = vault_root() / "snapshots" / f"{stamp}-{dataset_id(dataset)}"
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    results = []
    for relative, source in iter_databases(dataset):
        with source.open("rb") as handle:
            kind = database_format(handle.read(PAGE_SIZE))
        key = key_for_database(keys, relative)
        if kind == "wecom-wxsqlite3-aes128" and key is None:
            results.append({"database": str(relative), "status": "skipped", "reason": "missing key"})
            continue
        try:
            details = decrypt_database(source, destination / relative, key or bytes(16), apply_wal=not args.no_wal)
            results.append({"database": str(relative), "status": "ok", **details})
        except Exception as exc:
            results.append({"database": str(relative), "status": "failed", "reason": str(exc)})
    manifest = {
        "version": 1,
        "created_at": utc_now(),
        "dataset_id": dataset_id(dataset),
        "contains_plaintext_wecom_data": True,
        "wal_merge_enabled": not args.no_wal,
        "results": results,
    }
    manifest_path = destination / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(manifest_path, 0o600)
    failed = [item for item in results if item["status"] != "ok"]
    output({"snapshot": str(destination), "decrypted": len(results) - len(failed), "not_decrypted": len(failed), "manifest": str(manifest_path)})


def command_sessions(args) -> None:
    snapshot = snapshot_path(args.snapshot)
    sessions = list(load_sessions(snapshot).values())
    sessions.sort(key=lambda item: item["last_message_time"], reverse=True)
    if args.query:
        query = args.query.lower()
        sessions = [item for item in sessions if query in item["display_name"].lower() or query in item["conversation_id"].lower()]
    output({"count": min(len(sessions), args.limit), "sessions": sessions[: args.limit]})


def command_contacts(args) -> None:
    users = list(load_users(snapshot_path(args.snapshot)).values())
    if args.query:
        query = args.query.lower()
        users = [item for item in users if query in str(item.get("display_name", "")).lower() or query in str(item.get("account", "")).lower()]
    users.sort(key=lambda item: str(item.get("display_name", "")))
    output({"count": min(len(users), args.limit), "contacts": users[: args.limit]})


def messages_for_args(args) -> tuple[dict | None, list[dict]]:
    snapshot = snapshot_path(args.snapshot)
    session = resolve_session(args.chat, load_sessions(snapshot)) if getattr(args, "chat", None) else None
    messages = iter_messages(
        snapshot,
        session["conversation_id"] if session else None,
        parse_time(args.start),
        parse_time(args.end),
        getattr(args, "keyword", None),
        args.limit,
    )
    return session, messages


def command_history(args) -> None:
    session, messages = messages_for_args(args)
    output({"session": session, "count": len(messages), "messages": messages})


def command_search(args) -> None:
    _, messages = messages_for_args(args)
    output({"keyword": args.keyword, "count": len(messages), "messages": messages})


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", value).strip(" .")
    return value[:100] or "wecom-export"


def command_export(args) -> None:
    session, messages = messages_for_args(args)
    if session is None:
        raise SystemExit("export 需要指定会话")
    suffix = "json" if args.format == "json" else "md"
    if args.output:
        destination = Path(args.output).expanduser()
    else:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        destination = vault_root() / "exports" / f"{stamp}-{safe_name(session['display_name'])}.{suffix}"
    if destination.exists():
        raise SystemExit(f"拒绝覆盖已有文件: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        with destination.open("x", encoding="utf-8") as handle:
            json.dump({"session": session, "count": len(messages), "messages": messages}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    else:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(f"# {session['display_name']}\n\n")
            handle.write(f"- conversation_id: `{session['conversation_id']}`\n- messages: {len(messages)}\n\n")
            for message in messages:
                content = message["content"].replace("\n", "\n  ")
                handle.write(f"- {message['time']} · {message['sender']}\n  {content}\n")
    os.chmod(destination, 0o600)
    output({"output": str(destination), "messages": len(messages), "contains_plaintext_wecom_data": True})


def add_message_filters(parser, *, chat_required: bool) -> None:
    parser.add_argument("chat" if chat_required else "--chat", help="会话名称或 conversation_id")
    parser.add_argument("--snapshot")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--limit", type=int, default=200)


def main() -> int:
    parser = argparse.ArgumentParser(description="Query a private decrypted WeCom snapshot")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("discover", help="发现本机企业微信数据集")
    command.add_argument("--data-dir")
    command.add_argument("--show-paths", action="store_true")
    command.set_defaults(func=command_discover)

    command = sub.add_parser("status", help="检查数据库数量和加密格式")
    command.add_argument("--data-dir")
    command.add_argument("--show-paths", action="store_true")
    command.set_defaults(func=command_status)

    command = sub.add_parser("decrypt", help="创建新的只读明文快照")
    command.add_argument("--data-dir")
    command.add_argument("--key-file")
    command.add_argument("--no-wal", action="store_true")
    command.set_defaults(func=command_decrypt)

    command = sub.add_parser("sessions", help="列出会话")
    command.add_argument("--snapshot")
    command.add_argument("--query")
    command.add_argument("--limit", type=int, default=50)
    command.set_defaults(func=command_sessions)

    command = sub.add_parser("contacts", help="列出联系人")
    command.add_argument("--snapshot")
    command.add_argument("--query")
    command.add_argument("--limit", type=int, default=100)
    command.set_defaults(func=command_contacts)

    command = sub.add_parser("history", help="查询指定会话历史")
    add_message_filters(command, chat_required=True)
    command.set_defaults(func=command_history)

    command = sub.add_parser("search", help="全文搜索已解密消息")
    command.add_argument("keyword")
    add_message_filters(command, chat_required=False)
    command.set_defaults(func=command_search)

    command = sub.add_parser("export", help="导出指定会话")
    add_message_filters(command, chat_required=True)
    command.add_argument("--format", choices=("markdown", "json"), default="markdown")
    command.add_argument("--output")
    command.set_defaults(func=command_export)

    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1:
        raise SystemExit("--limit 必须大于 0")
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
