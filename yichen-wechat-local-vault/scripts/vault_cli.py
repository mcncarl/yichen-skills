#!/usr/bin/env python3
"""
Unified read-only query CLI for the decrypted wechat-local-vault.

This script intentionally reads only the local decrypted vault produced by
decrypt_all_dbs.py. It does not touch the WeChat UI, does not send messages,
and does not modify WeChat databases.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from xml.etree import ElementTree as ET

try:
    import zstandard as zstd
except Exception:  # pragma: no cover - optional runtime dependency
    zstd = None


CONFIG_FILE = Path("~/.config/wechat-local-vault.json").expanduser()
DEFAULT_VAULT_DIR = Path("~/Library/Application Support/wechat-local-vault").expanduser()
DEFAULT_DECRYPTED_DIR = DEFAULT_VAULT_DIR / "decrypted/current"
DEFAULT_EXPORTS_DIR = Path("~/Documents/wechat-local-vault/exports").expanduser()
STATE_FILE = DEFAULT_VAULT_DIR / "state/vault_cli_last_check.json"

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZSTD_DECODER = zstd.ZstdDecompressor() if zstd else None

MESSAGE_TYPE_FILTERS = {
    "text": (1,),
    "image": (3,),
    "voice": (34,),
    "video": (43,),
    "sticker": (47,),
    "location": (48,),
    "link": (49,),
    "file": (49, 6),
    "call": (50,),
    "system": (10000,),
}

TYPE_LABELS = {
    1: "文本",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "链接/文件",
    50: "通话",
    10000: "系统",
    10002: "撤回",
}

FAVORITE_TYPE_MAP = {
    1: "文本",
    2: "图片",
    5: "文章",
    19: "名片",
    20: "视频号",
}

FAVORITE_TYPE_FILTERS = {
    "text": 1,
    "image": 2,
    "article": 5,
    "card": 19,
    "video": 20,
}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_config() -> dict:
    return load_json(CONFIG_FILE)


def resolve_decrypted_dir(value: str | None = None) -> Path:
    config = load_config()
    return Path(value or config.get("decrypted_dir") or DEFAULT_DECRYPTED_DIR).expanduser()


def resolve_exports_dir(value: str | None = None) -> Path:
    config = load_config()
    return Path(value or config.get("exports_dir") or DEFAULT_EXPORTS_DIR).expanduser()


def resolve_db_dir() -> Path | None:
    config = load_config()
    if config.get("db_base_path"):
        return Path(config["db_base_path"]).expanduser()
    if config.get("wxid"):
        return (
            Path("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files").expanduser()
            / config["wxid"]
            / "db_storage"
        )
    return None


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in con.execute(f"PRAGMA table_info([{table}])")}
    except sqlite3.Error:
        return set()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:100] or "wechat_export"


def parse_time(value: str | None, *, end_of_day: bool = False) -> int | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp())
        except ValueError:
            pass
    raise SystemExit(f"时间格式不支持: {value}")


def split_msg_type(local_type: int | None) -> tuple[int, int]:
    try:
        value = int(local_type or 0)
    except (TypeError, ValueError):
        return 0, 0
    if value > 0xFFFFFFFF:
        return value & 0xFFFFFFFF, value >> 32
    return value, 0


def type_label(local_type: int | None) -> str:
    base_type, _ = split_msg_type(local_type)
    return TYPE_LABELS.get(base_type, f"type={local_type}")


def matches_type(local_type: int | None, filter_name: str | None) -> bool:
    if not filter_name:
        return True
    base_type, sub_type = split_msg_type(local_type)
    expected = MESSAGE_TYPE_FILTERS[filter_name]
    if base_type != expected[0]:
        return False
    return len(expected) == 1 or sub_type == expected[1]


def decode_value(value, compression_flag=None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    data = bytes(value)
    should_try_zstd = data.startswith(ZSTD_MAGIC) or compression_flag == 4
    if should_try_zstd and ZSTD_DECODER:
        try:
            data = ZSTD_DECODER.decompress(data, max_output_size=1_000_000)
        except Exception:
            return "[压缩消息解码失败]"
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return "[二进制内容]"


def output(data, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data)


def load_contacts(decrypted_dir: Path) -> tuple[dict[str, dict], dict[int, str]]:
    contact_db = decrypted_dir / "contact/contact.db"
    if not contact_db.exists():
        return {}, {}
    contacts: dict[str, dict] = {}
    id_to_username: dict[int, str] = {}
    with connect(contact_db) as con:
        if not table_exists(con, "contact"):
            return {}, {}
        for row in con.execute("SELECT * FROM contact"):
            item = dict(row)
            username = item.get("username") or item.get("userName") or ""
            if not username:
                continue
            username = str(username)
            contact_id = item.get("id")
            if contact_id is not None:
                try:
                    id_to_username[int(contact_id)] = username
                except (TypeError, ValueError):
                    pass
            nick = str(item.get("nick_name") or item.get("nickname") or "")
            remark = str(item.get("remark") or "")
            alias = str(item.get("alias") or "")
            display = remark or nick or alias or username
            contacts[username] = {
                "username": username,
                "display_name": display,
                "remark": remark,
                "nick_name": nick,
                "alias": alias,
                "description": str(item.get("description") or ""),
                "avatar": str(item.get("small_head_url") or item.get("big_head_url") or ""),
                "is_group": "@chatroom" in username,
                "is_subscription": username.startswith("gh_"),
                "raw": item,
            }
    return contacts, id_to_username


def display_name(username: str, contacts: dict[str, dict]) -> str:
    return contacts.get(username, {}).get("display_name") or username


def resolve_chat(query: str, contacts: dict[str, dict]) -> dict | None:
    if query in contacts:
        return contacts[query]
    if query.startswith("wxid_") or "@chatroom" in query or query.startswith("gh_"):
        return {
            "username": query,
            "display_name": contacts.get(query, {}).get("display_name", query),
            "is_group": "@chatroom" in query,
        }
    q = query.lower()
    exact = [c for c in contacts.values() if q == c["display_name"].lower()]
    if exact:
        return exact[0]
    fuzzy = [
        c
        for c in contacts.values()
        if any(q in str(c.get(field) or "").lower() for field in ("display_name", "remark", "nick_name", "alias", "username"))
    ]
    return fuzzy[0] if fuzzy else None


def message_dbs(decrypted_dir: Path) -> list[Path]:
    return sorted((decrypted_dir / "message").glob("message_*.db"))


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode()).hexdigest()


def load_name2id(con: sqlite3.Connection) -> dict[int, str]:
    mapping: dict[int, str] = {}
    if not table_exists(con, "Name2Id"):
        return mapping
    try:
        for row in con.execute("SELECT rowid, user_name FROM Name2Id"):
            if row["user_name"]:
                mapping[int(row["rowid"])] = str(row["user_name"])
    except sqlite3.Error:
        return {}
    return mapping


def username_for_table(table: str, con: sqlite3.Connection) -> str:
    if not table.startswith("Msg_"):
        return ""
    target = table[4:]
    if not table_exists(con, "Name2Id"):
        return ""
    try:
        for row in con.execute("SELECT user_name FROM Name2Id"):
            username = str(row["user_name"] or "")
            if hashlib.md5(username.encode()).hexdigest() == target:
                return username
    except sqlite3.Error:
        return ""
    return ""


def username_for_table_from_contacts(table: str, contacts: dict[str, dict]) -> str:
    if not table.startswith("Msg_"):
        return ""
    target = table[4:]
    for username in contacts:
        if hashlib.md5(username.encode()).hexdigest() == target:
            return username
    return ""


def message_columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    columns = table_columns(con, table)
    result = {}
    for key, choices in {
        "local_id": ("local_id", "id", "rowid"),
        "server_id": ("server_id",),
        "local_type": ("local_type", "type"),
        "create_time": ("create_time", "timestamp"),
        "real_sender_id": ("real_sender_id", "sender_id"),
        "message_content": ("message_content", "content"),
        "compress_content": ("compress_content", "WCDB_CT_message_content"),
        "compression_flag": ("WCDB_CT_message_content",),
    }.items():
        for choice in choices:
            if choice == "rowid" or choice in columns:
                result[key] = choice
                break
    return result


def build_select_sql(table: str, cols: dict[str, str], start_ts: int | None, end_ts: int | None, keyword: str | None, type_name: str | None, limit: int | None, offset: int = 0) -> tuple[str, list]:
    select_parts = []
    aliases = {
        "local_id": "local_id",
        "server_id": "server_id",
        "local_type": "local_type",
        "create_time": "create_time",
        "real_sender_id": "real_sender_id",
        "message_content": "message_content",
        "compress_content": "compress_content",
        "compression_flag": "compression_flag",
    }
    for key, alias in aliases.items():
        col = cols.get(key)
        if col:
            select_parts.append(f"{col} AS {alias}")
        else:
            select_parts.append(f"NULL AS {alias}")
    clauses = []
    params: list = []
    if start_ts is not None and cols.get("create_time"):
        clauses.append(f"{cols['create_time']} >= ?")
        params.append(start_ts)
    if end_ts is not None and cols.get("create_time"):
        clauses.append(f"{cols['create_time']} <= ?")
        params.append(end_ts)
    if keyword and cols.get("message_content"):
        clauses.append(f"{cols['message_content']} LIKE ?")
        params.append(f"%{keyword}%")
    if type_name and cols.get("local_type"):
        expected = MESSAGE_TYPE_FILTERS[type_name]
        base = expected[0]
        clauses.append(f"({cols['local_type']} & 4294967295) = ?")
        params.append(base)
        if len(expected) > 1:
            sub = expected[1]
            clauses.append(f"(({cols['local_type']} >> 32) & 4294967295) = ?")
            params.append(sub)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT {', '.join(select_parts)} FROM [{table}] {where} ORDER BY create_time DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return sql, params


def parse_sender_prefix(content: str) -> tuple[str, str]:
    if ":\n" not in content:
        return "", content
    sender, text = content.split(":\n", 1)
    if sender.startswith("wxid_") or "@chatroom" not in sender:
        return sender, text
    return "", content


def media_hint(local_type: int | None, content: str, resolve_media: bool, db_dir: Path | None, chat_username: str, ts: int) -> str | None:
    base_type, _ = split_msg_type(local_type)
    if base_type == 3:
        return "[图片]"
    if base_type == 34:
        match = re.search(r'voicelength="(\d+)"', content or "")
        if match:
            return f"[语音，约 {int(match.group(1)) / 1000:.1f} 秒]"
        return "[语音]"
    if base_type == 43:
        return "[视频]"
    if base_type == 47:
        return "[表情]"
    if base_type == 48:
        return "[位置]"
    if base_type == 42:
        return "[名片]"
    if base_type == 50:
        return "[通话]"
    if base_type != 49 or not resolve_media or not db_dir:
        return None
    title = ""
    try:
        root = ET.fromstring(content)
        title = (root.findtext(".//title") or root.findtext(".//filename") or "").strip()
    except Exception:
        pass
    if not title:
        return None
    file_dir = db_dir.parent / "msg/file"
    if not file_dir.exists():
        return f"[文件] {title}"
    month = datetime.fromtimestamp(ts).strftime("%Y-%m")
    month_dir = file_dir / month
    if month_dir.exists():
        candidate = month_dir / title
        if candidate.exists():
            return f"[文件] {title}\n{candidate}"
    return f"[文件] {title}"


def format_content(local_type: int | None, content: str, resolve_media: bool, db_dir: Path | None, chat_username: str, ts: int) -> str:
    hint = media_hint(local_type, content, resolve_media, db_dir, chat_username, ts)
    if hint:
        return hint
    base_type, sub_type = split_msg_type(local_type)
    if base_type == 49:
        try:
            root = ET.fromstring(content)
            app_type = int(root.findtext(".//type") or 0)
            title = (root.findtext(".//title") or "").strip()
            desc = (root.findtext(".//des") or "").strip()
            if app_type == 5:
                return f"[链接] {title or desc}".strip()
            if app_type in (33, 36, 44):
                return f"[小程序] {title or desc}".strip()
            if sub_type == 6 or app_type == 6:
                return f"[文件] {title or desc}".strip()
            return f"[链接/文件] {title or desc}".strip()
        except Exception:
            return content.strip() or "[链接/文件]"
    if base_type not in (1, 10000):
        return f"[{type_label(local_type)}] {content}".strip()
    return content.strip()


def row_to_message(row: sqlite3.Row, db_name: str, table: str, chat: dict, contacts: dict[str, dict], name2id: dict[int, str], resolve_media: bool = False, db_dir: Path | None = None) -> dict:
    local_type = row["local_type"]
    ts = int(row["create_time"] or 0)
    content = decode_value(row["message_content"], row["compression_flag"]) or decode_value(row["compress_content"], row["compression_flag"])
    prefix_sender, content = parse_sender_prefix(content)
    sender_username = ""
    sender_id = row["real_sender_id"]
    try:
        sender_username = name2id.get(int(sender_id), "")
    except (TypeError, ValueError):
        sender_username = ""
    if not sender_username:
        sender_username = prefix_sender
    if chat.get("is_group"):
        sender = display_name(sender_username, contacts) if sender_username else ""
    elif sender_username and sender_username != chat["username"]:
        sender = display_name(sender_username, contacts)
    elif str(sender_id) == "2":
        sender = "我"
    else:
        sender = chat["display_name"]
    text = format_content(local_type, content, resolve_media, db_dir, chat["username"], ts)
    return {
        "db": db_name,
        "table": table,
        "local_id": row["local_id"],
        "server_id": row["server_id"],
        "type": type_label(local_type),
        "local_type": local_type,
        "sender": sender,
        "sender_username": sender_username,
        "timestamp": ts,
        "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "",
        "content": text,
    }


def find_chat_tables(decrypted_dir: Path, chat: dict) -> list[tuple[Path, str]]:
    target = message_table(chat["username"])
    matches = []
    for db_path in message_dbs(decrypted_dir):
        with connect(db_path) as con:
            if table_exists(con, target):
                matches.append((db_path, target))
    return matches


def collect_history(decrypted_dir: Path, chat: dict, start_ts: int | None, end_ts: int | None, limit: int, offset: int, type_name: str | None, resolve_media: bool = False) -> list[dict]:
    contacts, _ = load_contacts(decrypted_dir)
    db_dir = resolve_db_dir()
    rows = []
    candidate_limit = limit + offset
    for db_path, table in find_chat_tables(decrypted_dir, chat):
        with connect(db_path) as con:
            cols = message_columns(con, table)
            sql, params = build_select_sql(table, cols, start_ts, end_ts, None, type_name, candidate_limit, 0)
            name2id = load_name2id(con)
            for row in con.execute(sql, params):
                msg = row_to_message(row, db_path.name, table, chat, contacts, name2id, resolve_media, db_dir)
                if matches_type(msg["local_type"], type_name):
                    rows.append(msg)
    rows.sort(key=lambda item: (item["timestamp"], str(item["local_id"])), reverse=True)
    page = rows[offset : offset + limit]
    page.sort(key=lambda item: (item["timestamp"], str(item["local_id"])))
    return page


def command_status(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    names = [
        "contact/contact.db",
        "session/session.db",
        "sns/sns.db",
        "favorite/favorite.db",
        "message/message_resource.db",
    ]
    names.extend(str(p.relative_to(decrypted_dir)) for p in message_dbs(decrypted_dir))
    data = {
        "decrypted_dir": str(decrypted_dir),
        "exists": decrypted_dir.exists(),
        "databases": [{"path": rel, "available": (decrypted_dir / rel).exists()} for rel in sorted(set(names))],
    }
    output(data if args.format == "json" else render_status_text(data), args.format)


def render_status_text(data: dict) -> str:
    lines = [f"明文 vault: {data['decrypted_dir']}", f"状态: {'可用' if data['exists'] else '不存在'}", "", "数据库:"]
    for item in data["databases"]:
        lines.append(f"  {'OK' if item['available'] else '--'} {item['path']}")
    return "\n".join(lines)


def session_rows(decrypted_dir: Path, only_unread: bool, limit: int | None = None) -> list[dict]:
    session_db = decrypted_dir / "session/session.db"
    if not session_db.exists():
        raise SystemExit(f"找不到 session.db，请先增量或全量解密: {session_db}")
    contacts, _ = load_contacts(decrypted_dir)
    rows = []
    with connect(session_db) as con:
        if not table_exists(con, "SessionTable"):
            raise SystemExit("session.db 中没有 SessionTable")
        where = "WHERE unread_count > 0" if only_unread else "WHERE last_timestamp > 0"
        sql = (
            "SELECT username, unread_count, summary, last_timestamp, last_msg_type, "
            f"last_msg_sender, last_sender_display_name FROM SessionTable {where} "
            "ORDER BY last_timestamp DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            query = con.execute(sql, (limit,))
        else:
            query = con.execute(sql)
        for row in query:
            username = str(row["username"] or "")
            summary = decode_value(row["summary"], 4)
            if ":\n" in summary:
                summary = summary.split(":\n", 1)[1]
            sender_username = str(row["last_msg_sender"] or "")
            sender = display_name(sender_username, contacts) if sender_username else str(row["last_sender_display_name"] or "")
            ts = int(row["last_timestamp"] or 0)
            rows.append({
                "chat": display_name(username, contacts),
                "username": username,
                "is_group": "@chatroom" in username,
                "unread": int(row["unread_count"] or 0),
                "last_message": summary,
                "msg_type": type_label(row["last_msg_type"]),
                "sender": sender,
                "timestamp": ts,
                "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "",
            })
    return rows


def render_sessions_text(rows: list[dict], title: str) -> str:
    if not rows:
        return "没有找到会话"
    lines = [f"{title}（{len(rows)} 个）", ""]
    for row in rows:
        head = f"[{row['time']}] {row['chat']}"
        if row["is_group"]:
            head += " [群]"
        if row["unread"]:
            head += f" ({row['unread']}条未读)"
        body = f"  {row['msg_type']}: "
        if row["sender"] and row["is_group"]:
            body += f"{row['sender']}: "
        body += row["last_message"]
        lines.extend([head, body, ""])
    return "\n".join(lines).rstrip()


def command_sessions(args: argparse.Namespace) -> None:
    rows = session_rows(resolve_decrypted_dir(args.decrypted_dir), False, args.limit)
    output(rows if args.format == "json" else render_sessions_text(rows, "最近会话"), args.format)


def command_unread(args: argparse.Namespace) -> None:
    rows = session_rows(resolve_decrypted_dir(args.decrypted_dir), True, args.limit)
    output(rows if args.format == "json" else render_sessions_text(rows, "未读会话"), args.format)


def command_new_messages(args: argparse.Namespace) -> None:
    rows = session_rows(resolve_decrypted_dir(args.decrypted_dir), False, None)
    current = {row["username"]: row["timestamp"] for row in rows}
    previous = load_json(STATE_FILE)
    if not previous:
        save_json(STATE_FILE, current)
        unread = [row for row in rows if row["unread"] > 0]
        data = {"first_call": True, "unread_count": len(unread), "messages": unread}
        text = render_sessions_text(unread, "当前未读会话") if unread else "当前无未读消息；已记录状态，下次只返回新增。"
        output(data if args.format == "json" else text, args.format)
        return
    changed = [row for row in rows if row["timestamp"] > int(previous.get(row["username"], 0) or 0)]
    changed.sort(key=lambda item: item["timestamp"])
    save_json(STATE_FILE, current)
    data = {"first_call": False, "new_count": len(changed), "messages": changed}
    text = render_sessions_text(changed, "新增消息") if changed else "无新消息"
    output(data if args.format == "json" else text, args.format)


def command_contacts(args: argparse.Namespace) -> None:
    contacts, _ = load_contacts(resolve_decrypted_dir(args.decrypted_dir))
    if args.detail:
        item = resolve_chat(args.detail, contacts)
        if not item:
            raise SystemExit(f"找不到联系人: {args.detail}")
        data = {k: v for k, v in item.items() if k != "raw"}
        output(data if args.format == "json" else render_contact_detail(data), args.format)
        return
    items = list(contacts.values())
    if args.query:
        q = args.query.lower()
        items = [
            item for item in items
            if any(q in str(item.get(field) or "").lower() for field in ("username", "display_name", "remark", "nick_name", "alias"))
        ]
    items.sort(key=lambda item: (not item["is_group"], item["display_name"]))
    items = [{k: v for k, v in item.items() if k != "raw"} for item in items[: args.limit]]
    output({"count": len(items), "contacts": items} if args.format == "json" else render_contacts_text(items), args.format)


def render_contacts_text(items: list[dict]) -> str:
    if not items:
        return "没有找到联系人"
    lines = []
    for index, item in enumerate(items, 1):
        tag = "群" if item["is_group"] else "联系人"
        lines.append(f"{index}. [{tag}] {item['display_name']}")
        if item.get("remark"):
            lines.append(f"   备注: {item['remark']}")
        if item.get("nick_name") and item["nick_name"] != item.get("remark"):
            lines.append(f"   昵称: {item['nick_name']}")
        lines.append(f"   username: {item['username']}")
    return "\n".join(lines)


def render_contact_detail(item: dict) -> str:
    lines = [item["display_name"], f"username: {item['username']}"]
    for key, label in [("remark", "备注"), ("nick_name", "昵称"), ("alias", "微信号"), ("description", "描述"), ("avatar", "头像")]:
        if item.get(key):
            lines.append(f"{label}: {item[key]}")
    lines.append(f"类型: {'群聊' if item.get('is_group') else '联系人'}")
    return "\n".join(lines)


def command_members(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    contacts, _ = load_contacts(decrypted_dir)
    group = resolve_chat(args.group, contacts)
    if not group or not group.get("is_group"):
        raise SystemExit(f"找不到群聊: {args.group}")
    contact_db = decrypted_dir / "contact/contact.db"
    owner = ""
    members = []
    with connect(contact_db) as con:
        if table_exists(con, "contact") and table_exists(con, "chat_room") and table_exists(con, "chatroom_member"):
            room = con.execute("SELECT id FROM contact WHERE username=? OR userName=?", (group["username"], group["username"])).fetchone()
            if room:
                room_id = room["id"]
                owner_row = con.execute("SELECT owner FROM chat_room WHERE id=?", (room_id,)).fetchone()
                owner_username = str(owner_row["owner"] or "") if owner_row else ""
                owner = display_name(owner_username, contacts) if owner_username else ""
                ids = [row["member_id"] for row in con.execute("SELECT member_id FROM chatroom_member WHERE room_id=?", (room_id,))]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    for row in con.execute(f"SELECT id, username, nick_name, remark FROM contact WHERE id IN ({placeholders})", ids):
                        username = str(row["username"] or "")
                        members.append({
                            "username": username,
                            "display_name": row["remark"] or row["nick_name"] or username,
                            "remark": row["remark"] or "",
                            "nick_name": row["nick_name"] or "",
                            "is_owner": username == owner_username,
                        })
    if not members:
        stats = collect_stats(decrypted_dir, group, None, None)
        members = [{"display_name": item["name"], "message_count": item["count"]} for item in stats["top_senders"]]
    members.sort(key=lambda item: (not item.get("is_owner", False), item.get("display_name", "")))
    data = {"group": group["display_name"], "username": group["username"], "owner": owner, "member_count": len(members), "members": members}
    output(data if args.format == "json" else render_members_text(data), args.format)


def render_members_text(data: dict) -> str:
    lines = [f"{data['group']} 群成员（{data['member_count']} 人）"]
    if data.get("owner"):
        lines.append(f"群主: {data['owner']}")
    for index, item in enumerate(data["members"], 1):
        suffix = " [群主]" if item.get("is_owner") else ""
        count = f" - {item['message_count']}条" if "message_count" in item else ""
        lines.append(f"{index}. {item['display_name']}{suffix}{count}")
    return "\n".join(lines)


def command_history(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    contacts, _ = load_contacts(decrypted_dir)
    chat = resolve_chat(args.chat, contacts)
    if not chat:
        raise SystemExit(f"找不到聊天对象: {args.chat}")
    rows = collect_history(
        decrypted_dir,
        chat,
        parse_time(args.start_time),
        parse_time(args.end_time, end_of_day=True),
        args.limit,
        args.offset,
        args.type,
        args.media,
    )
    data = {"chat": chat["display_name"], "username": chat["username"], "count": len(rows), "messages": rows}
    output(data if args.format == "json" else render_messages_text(rows), args.format)


def render_messages_text(rows: list[dict]) -> str:
    if not rows:
        return "没有找到消息"
    lines = []
    for row in rows:
        sender = f"{row['sender']}: " if row.get("sender") else ""
        lines.append(f"[{row['time']}] {sender}{row['content']}")
    return "\n".join(lines)


def command_search(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    contacts, _ = load_contacts(decrypted_dir)
    start_ts = parse_time(args.start_time)
    end_ts = parse_time(args.end_time, end_of_day=True)
    candidate_limit = args.limit + args.offset
    results = []
    chats = []
    if args.chat:
        for chat_query in args.chat:
            chat = resolve_chat(chat_query, contacts)
            if chat:
                chats.append(chat)
        for chat in chats:
            for row in collect_history(decrypted_dir, chat, start_ts, end_ts, candidate_limit, 0, args.type, False):
                if args.keyword.lower() in row["content"].lower():
                    row["chat"] = chat["display_name"]
                    row["chat_username"] = chat["username"]
                    results.append(row)
    else:
        for db_path in message_dbs(decrypted_dir):
            with connect(db_path) as con:
                tables = [row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
                name2id = load_name2id(con)
                for table in tables:
                    username = username_for_table(table, con) or username_for_table_from_contacts(table, contacts)
                    chat = {
                        "username": username,
                        "display_name": display_name(username, contacts) if username else table,
                        "is_group": "@chatroom" in username,
                    }
                    cols = message_columns(con, table)
                    sql, params = build_select_sql(table, cols, start_ts, end_ts, args.keyword, args.type, candidate_limit, 0)
                    try:
                        for row in con.execute(sql, params):
                            msg = row_to_message(row, db_path.name, table, chat, contacts, name2id)
                            if args.keyword.lower() in msg["content"].lower() and matches_type(msg["local_type"], args.type):
                                msg["chat"] = chat["display_name"]
                                msg["chat_username"] = chat["username"]
                                results.append(msg)
                    except sqlite3.Error:
                        continue
    results.sort(key=lambda item: item["timestamp"], reverse=True)
    page = results[args.offset : args.offset + args.limit]
    page.sort(key=lambda item: item["timestamp"])
    data = {"keyword": args.keyword, "count": len(page), "messages": page}
    output(data if args.format == "json" else render_search_text(page), args.format)


def render_search_text(rows: list[dict]) -> str:
    if not rows:
        return "没有找到匹配消息"
    return "\n".join(f"[{row['time']}] [{row.get('chat', '')}] {row.get('sender', '')}: {row['content']}".strip() for row in rows)


def collect_stats(decrypted_dir: Path, chat: dict, start_ts: int | None, end_ts: int | None) -> dict:
    contacts, _ = load_contacts(decrypted_dir)
    total = 0
    type_counts: dict[str, int] = {}
    sender_counts: dict[str, int] = {}
    hourly = {hour: 0 for hour in range(24)}
    for db_path, table in find_chat_tables(decrypted_dir, chat):
        with connect(db_path) as con:
            name2id = load_name2id(con)
            cols = message_columns(con, table)
            clauses = []
            params = []
            if start_ts is not None:
                clauses.append(f"{cols['create_time']} >= ?")
                params.append(start_ts)
            if end_ts is not None:
                clauses.append(f"{cols['create_time']} <= ?")
                params.append(end_ts)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            for row in con.execute(f"SELECT {cols['local_type']} AS local_type, COUNT(*) AS count FROM [{table}] {where} GROUP BY {cols['local_type']}", params):
                label = type_label(row["local_type"])
                count = int(row["count"] or 0)
                type_counts[label] = type_counts.get(label, 0) + count
                total += count
            for row in con.execute(f"SELECT {cols['real_sender_id']} AS sender_id, COUNT(*) AS count FROM [{table}] {where} GROUP BY {cols['real_sender_id']}", params):
                sender_username = name2id.get(int(row["sender_id"] or 0), "")
                sender = display_name(sender_username, contacts) if sender_username else str(row["sender_id"])
                sender_counts[sender] = sender_counts.get(sender, 0) + int(row["count"] or 0)
            for row in con.execute(f"SELECT cast(strftime('%H', {cols['create_time']}, 'unixepoch', 'localtime') as integer) AS hour, COUNT(*) AS count FROM [{table}] {where} GROUP BY hour", params):
                if row["hour"] is not None:
                    hourly[int(row["hour"])] += int(row["count"] or 0)
    return {
        "total": total,
        "type_breakdown": dict(sorted(type_counts.items(), key=lambda item: item[1], reverse=True)),
        "top_senders": [{"name": name, "count": count} for name, count in sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)[:10]],
        "hourly": hourly,
    }


def command_stats(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    contacts, _ = load_contacts(decrypted_dir)
    chat = resolve_chat(args.chat, contacts)
    if not chat:
        raise SystemExit(f"找不到聊天对象: {args.chat}")
    stats = collect_stats(decrypted_dir, chat, parse_time(args.start_time), parse_time(args.end_time, end_of_day=True))
    data = {"chat": chat["display_name"], "username": chat["username"], "is_group": chat.get("is_group", False), **stats}
    output(data if args.format == "json" else render_stats_text(data), args.format)


def render_stats_text(data: dict) -> str:
    lines = [f"{data['chat']} 统计", f"消息总数: {data['total']}", "", "消息类型:"]
    for label, count in data["type_breakdown"].items():
        pct = count / data["total"] * 100 if data["total"] else 0
        lines.append(f"  {label}: {count} ({pct:.1f}%)")
    lines.append("")
    lines.append("发言排行:")
    for item in data["top_senders"]:
        lines.append(f"  {item['name']}: {item['count']}")
    lines.append("")
    lines.append("24小时分布:")
    max_count = max(data["hourly"].values()) if data["hourly"] else 0
    for hour in range(24):
        count = data["hourly"].get(hour, 0)
        bar = "#" * (int(count / max_count * 24) if max_count else 0)
        lines.append(f"  {hour:02d}:00 | {bar} {count}")
    return "\n".join(lines)


def command_export(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    exports_dir = resolve_exports_dir(args.exports_dir)
    contacts, _ = load_contacts(decrypted_dir)
    chat = resolve_chat(args.chat, contacts)
    if not chat:
        raise SystemExit(f"找不到聊天对象: {args.chat}")
    rows = collect_history(
        decrypted_dir,
        chat,
        parse_time(args.start_time),
        parse_time(args.end_time, end_of_day=True),
        args.limit,
        0,
        args.type,
        args.media,
    )
    if args.format == "markdown":
        body = render_export_markdown(chat, rows, args.start_time, args.end_time)
        suffix = "md"
    else:
        body = render_messages_text(rows)
        suffix = "txt"
    out_path = Path(args.output).expanduser() if args.output else exports_dir / "cli_exports" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_name(chat['display_name'])}.{suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body.rstrip() + "\n", encoding="utf-8")
    print(out_path)
    print(f"Exported {len(rows)} messages.")


def digest_range_label(start_time: str | None, end_time: str | None) -> str:
    if start_time and end_time and start_time[:10] == end_time[:10]:
        return start_time[:10]
    if start_time or end_time:
        return f"{(start_time or 'earliest')[:10]}_{(end_time or 'latest')[:10]}"
    return datetime.now().strftime("%Y-%m-%d")


def digest_folder(data_root: Path, group: dict) -> Path:
    return data_root / f"{safe_name(group['username'])}-{safe_name(group['display_name'])}"


def last_digest_timestamp(folder: Path) -> int | None:
    history = load_json(folder / "history.json")
    value = (history.get("last_digest") or {}).get("last_message_timestamp")
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def digest_stats_from_rows(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    usable = []
    for row in rows:
        content = row.get("content") or ""
        if row.get("type") == "系统" or "revokemsg" in content:
            continue
        usable.append(row)
        sender = row.get("sender") or "未知"
        counts[sender] = counts.get(sender, 0) + 1
    leaderboard = [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]]
    active_senders = [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True) if count >= 3]
    return {
        "message_count": len(usable),
        "leaderboard": leaderboard,
        "active_senders": active_senders,
        "last_message_timestamp": max((row["timestamp"] for row in rows), default=0),
    }


def render_digest_source_markdown(group: dict, rows: list[dict], stats: dict, range_text: str) -> str:
    lines = [
        f"{group['display_name']} 群聊精华素材 · {range_text}",
        "",
        f"消息统计: 共 {stats['message_count']} 条消息",
    ]
    for index, item in enumerate(stats["leaderboard"], 1):
        lines.append(f"{index}. {item['name']}: {item['count']} 条")
    lines.extend([
        "",
        "群友画像候选（3条以上）",
    ])
    if stats["active_senders"]:
        for item in stats["active_senders"]:
            lines.append(f"- {item['name']}: {item['count']} 条")
    else:
        lines.append("- 无")
    lines.extend([
        "",
        "消息素材",
        "",
    ])
    for row in rows:
        sender = row.get("sender") or "未知"
        lines.append(f"- id={row.get('local_id')} time={row['time']} sender={sender} type={row['type']} content={row['content']}")
    return "\n".join(lines)


def command_digest_source(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    contacts, _ = load_contacts(decrypted_dir)
    group = resolve_chat(args.group, contacts)
    if not group or not group.get("is_group"):
        raise SystemExit(f"找不到群聊: {args.group}")

    data_root = Path(args.data_root).expanduser() if args.data_root else Path.cwd() / "wechat"
    folder = digest_folder(data_root, group)
    folder.mkdir(parents=True, exist_ok=True)
    for child in ("profiles", "profiles-roast", "imgs", "sources"):
        (folder / child).mkdir(parents=True, exist_ok=True)

    start_ts = parse_time(args.start)
    if args.since_last:
        start_ts = last_digest_timestamp(folder) or start_ts
    end_ts = parse_time(args.end, end_of_day=True)
    rows = collect_history(decrypted_dir, group, start_ts, end_ts, args.limit, 0, None, args.media)
    stats = digest_stats_from_rows(rows)
    range_text = digest_range_label(args.start, args.end)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    source_json = folder / "sources" / f"{stamp}-{range_text}.json"
    source_md = folder / "sources" / f"{stamp}-{range_text}.md"
    payload = {
        "group": {"name": group["display_name"], "username": group["username"]},
        "range": {"start": args.start or "", "end": args.end or "", "since_last": args.since_last},
        "stats": stats,
        "messages": rows,
        "notes": {
            "image_content_is_opaque": True,
            "image_description_extension": str(folder / "imgs/{message_id}.txt"),
            "profiles_dir": str(folder / "profiles"),
            "history_file": str(folder / "history.json"),
        },
    }
    source_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_md.write_text(render_digest_source_markdown(group, rows, stats, range_text) + "\n", encoding="utf-8")
    result = {
        "folder": str(folder),
        "source_json": str(source_json),
        "source_markdown": str(source_md),
        "message_count": len(rows),
        "digest_stats_count": stats["message_count"],
        "last_message_timestamp": stats["last_message_timestamp"],
        "next_step": "Use the source files to draft a normal or roast digest, then update history.json after the final digest is accepted.",
    }
    output(result if args.format == "json" else "\n".join(f"{k}: {v}" for k, v in result.items()), args.format)


def render_export_markdown(chat: dict, rows: list[dict], start_time: str | None, end_time: str | None) -> str:
    lines = [
        f"# 聊天记录: {chat['display_name']}",
        "",
        f"- 会话 ID: {chat['username']}",
        f"- 类型: {'群聊' if chat.get('is_group') else '私聊'}",
        f"- 时间范围: {start_time or '最早'} ~ {end_time or '最新'}",
        f"- 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 消息数量: {len(rows)}",
        "",
        "## 时间线",
        "",
    ]
    for row in rows:
        sender = f"{row['sender']}: " if row.get("sender") else ""
        lines.append(f"- {row['time']} [{row['type']}] {sender}{row['content']}")
    return "\n".join(lines)


def parse_favorite(content: str, fav_type: int) -> str:
    if not content:
        return ""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return ""
    item = root if root.tag == "favitem" else root.find(".//favitem")
    if item is None:
        return ""
    if fav_type == 1:
        return (item.findtext("desc") or "").strip()
    if fav_type == 2:
        return "[图片收藏]"
    if fav_type == 5:
        title = (item.findtext(".//pagetitle") or "").strip()
        desc = (item.findtext(".//pagedesc") or "").strip()
        return f"{title} - {desc}" if desc else title
    if fav_type == 19:
        return (item.findtext("desc") or "").strip()
    if fav_type == 20:
        nickname = (item.findtext(".//nickname") or "").strip()
        desc = (item.findtext(".//desc") or "").strip()
        return " ".join(part for part in (nickname, desc) if part) or "[视频号]"
    return (item.findtext("desc") or "").strip() or "[收藏]"


def command_favorites(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    fav_db = decrypted_dir / "favorite/favorite.db"
    if not fav_db.exists():
        raise SystemExit(f"找不到 favorite.db: {fav_db}")
    contacts, _ = load_contacts(decrypted_dir)
    where = []
    params = []
    if args.type:
        where.append("type = ?")
        params.append(FAVORITE_TYPE_FILTERS[args.type])
    if args.query:
        where.append("content LIKE ?")
        params.append(f"%{args.query}%")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = []
    with connect(fav_db) as con:
        if not table_exists(con, "fav_db_item"):
            raise SystemExit("favorite.db 中没有 fav_db_item")
        for row in con.execute(
            f"SELECT local_id, type, update_time, content, fromusr, realchatname FROM fav_db_item {where_sql} ORDER BY update_time DESC LIMIT ?",
            (*params, args.limit),
        ):
            ts = int(row["update_time"] or 0)
            fav_type = int(row["type"] or 0)
            rows.append({
                "id": row["local_id"],
                "type": FAVORITE_TYPE_MAP.get(fav_type, f"type={fav_type}"),
                "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "",
                "summary": parse_favorite(row["content"] or "", fav_type),
                "from": display_name(str(row["fromusr"] or ""), contacts) if row["fromusr"] else "",
                "source_chat": display_name(str(row["realchatname"] or ""), contacts) if row["realchatname"] else "",
            })
    data = {"count": len(rows), "favorites": rows}
    output(data if args.format == "json" else render_favorites_text(rows), args.format)


def render_favorites_text(rows: list[dict]) -> str:
    if not rows:
        return "没有找到收藏"
    lines = []
    for row in rows:
        entry = f"[{row['time']}] [{row['type']}] {row['summary']}"
        if row["from"]:
            entry += f"\n  来自: {row['from']}"
        if row["source_chat"]:
            entry += f"\n  聊天: {row['source_chat']}"
        lines.append(entry)
    return "\n\n".join(lines)


def xml_text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    return (node.text or "").strip() if node is not None else ""


def parse_moment(content: str, tid: str, db_user: str) -> dict:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        root = ET.fromstring(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content))
    timeline = root.find("TimelineObject") if root.tag != "TimelineObject" else root
    if timeline is None:
        timeline = root
    media = []
    for item in timeline.findall(".//media"):
        media.append({
            "type": xml_text(item, "type"),
            "url": xml_text(item, "url"),
            "thumb": xml_text(item, "thumb"),
        })
    links = []
    for path in ("ContentObject/contentUrl", ".//url"):
        for node in timeline.findall(path):
            if node.text and node.text.strip():
                links.append(node.text.strip())
    create_time = xml_text(timeline, "createTime")
    ts = int(create_time) if create_time.isdigit() else 0
    return {
        "tid": tid,
        "username": xml_text(timeline, "username") or db_user,
        "nickname": xml_text(timeline, "nickname"),
        "timestamp": ts,
        "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "",
        "content": xml_text(timeline, "contentDesc"),
        "type": xml_text(timeline, "ContentObject/contentStyle") or xml_text(timeline, "ContentObject/contentSubStyle"),
        "media": media,
        "links": sorted(set(links)),
    }


def command_moments(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    sns_db = decrypted_dir / "sns/sns.db"
    if not sns_db.exists():
        raise SystemExit(f"找不到 sns.db: {sns_db}")
    contacts, _ = load_contacts(decrypted_dir)
    usernames = set(args.username or [])
    if args.name:
        q = args.name.lower()
        for item in contacts.values():
            if any(q in str(item.get(field) or "").lower() for field in ("username", "display_name", "remark", "nick_name", "alias")):
                usernames.add(item["username"])
    if not usernames:
        raise SystemExit("请传 --name 或 --username")
    start_ts = parse_time(args.start)
    end_ts = parse_time(args.end, end_of_day=True)
    posts = []
    with connect(sns_db) as con:
        placeholders = ",".join("?" for _ in usernames)
        for row in con.execute(f"SELECT tid, user_name, content FROM SnsTimeLine WHERE user_name IN ({placeholders})", tuple(usernames)):
            if not row["content"]:
                continue
            try:
                post = parse_moment(row["content"], str(row["tid"]), str(row["user_name"]))
            except Exception as exc:
                post = {"tid": str(row["tid"]), "username": str(row["user_name"]), "time": "", "timestamp": 0, "content": f"[无法解析 XML: {exc}]", "media": [], "links": []}
            if start_ts and (not post["timestamp"] or post["timestamp"] < start_ts):
                continue
            if end_ts and (not post["timestamp"] or post["timestamp"] > end_ts):
                continue
            if args.keyword:
                haystack = json.dumps(post, ensure_ascii=False)
                if args.keyword.lower() not in haystack.lower():
                    continue
            post["display_name"] = display_name(post["username"], contacts)
            posts.append(post)
    posts.sort(key=lambda item: item["timestamp"], reverse=True)
    posts = posts[: args.limit]
    data = {"count": len(posts), "moments": posts}
    output(data if args.format == "json" else render_moments_text(posts), args.format)


def render_moments_text(posts: list[dict]) -> str:
    if not posts:
        return "没有找到匹配朋友圈"
    lines = []
    for post in posts:
        suffix = []
        if post.get("media"):
            suffix.append(f"{len(post['media'])}个媒体")
        if post.get("links"):
            suffix.append(f"{len(post['links'])}个链接")
        header = f"[{post['time']}] {post.get('display_name') or post['username']}"
        if suffix:
            header += f" ({'，'.join(suffix)})"
        lines.append(header)
        lines.append(post.get("content") or "[无文字内容]")
        for link in post.get("links", [])[:5]:
            lines.append(f"  link: {link}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the decrypted wechat-local-vault.")
    parser.add_argument("--decrypted-dir", help="覆盖明文 vault 目录")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="查看 vault 可用数据库")
    p.add_argument("--format", choices=["json", "text"], default="text")
    p.set_defaults(func=command_status)

    p = sub.add_parser("sessions", help="最近会话")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_sessions)

    p = sub.add_parser("unread", help="未读会话")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_unread)

    p = sub.add_parser("new-messages", help="自上次调用以来的新消息")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_new_messages)

    p = sub.add_parser("contacts", help="联系人/群聊搜索")
    p.add_argument("--query")
    p.add_argument("--detail")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_contacts)

    p = sub.add_parser("members", help="群成员")
    p.add_argument("group")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_members)

    p = sub.add_parser("history", help="聊天记录")
    p.add_argument("chat")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--type", choices=sorted(MESSAGE_TYPE_FILTERS))
    p.add_argument("--media", action="store_true", help="尝试附带本地文件路径提示")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_history)

    p = sub.add_parser("search", help="全局或指定会话搜索")
    p.add_argument("keyword")
    p.add_argument("--chat", action="append")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--type", choices=sorted(MESSAGE_TYPE_FILTERS))
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_search)

    p = sub.add_parser("stats", help="聊天统计")
    p.add_argument("chat")
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_stats)

    p = sub.add_parser("export", help="导出聊天记录")
    p.add_argument("chat")
    p.add_argument("--format", choices=["markdown", "txt"], default="markdown")
    p.add_argument("--output")
    p.add_argument("--exports-dir")
    p.add_argument("--start-time", default="")
    p.add_argument("--end-time", default="")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--type", choices=sorted(MESSAGE_TYPE_FILTERS))
    p.add_argument("--media", action="store_true")
    p.set_defaults(func=command_export)

    p = sub.add_parser("digest-source", help="生成群聊摘要素材包")
    p.add_argument("group")
    p.add_argument("--start", help="开始时间 YYYY-MM-DD [HH:MM[:SS]]")
    p.add_argument("--end", help="结束时间 YYYY-MM-DD [HH:MM[:SS]]")
    p.add_argument("--since-last", action="store_true", help="优先从该群 history.json 的上次摘要时间继续")
    p.add_argument("--data-root", help="摘要归档根目录，默认当前项目的 wechat/")
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--media", action="store_true", help="尝试附带本地文件路径提示")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_digest_source)

    p = sub.add_parser("favorites", help="收藏夹")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--type", choices=sorted(FAVORITE_TYPE_FILTERS))
    p.add_argument("--query")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_favorites)

    p = sub.add_parser("moments", help="朋友圈")
    p.add_argument("--name")
    p.add_argument("--username", action="append")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--keyword")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_moments)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
