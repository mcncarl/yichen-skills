#!/usr/bin/env python3
"""
Unified read-only query CLI for the decrypted wechat-local-vault.

Mac commands read the local decrypted vault produced by decrypt_all_dbs.py.
The explicit snapshot subcommand uses a separately validated plaintext snapshot.
It does not touch the WeChat UI, send messages, or modify WeChat databases.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from xml.etree import ElementTree as ET

from wechat_schema import message_columns as shared_message_columns
from wechat_schema import message_table as shared_message_table
from message_display import ENVELOPE, HIDDEN_ID, PLACEHOLDER_TYPES, file_attachment_size, format_message_content, public_value, redact_text

try:
    import zstandard as zstd
except Exception:  # pragma: no cover - optional runtime dependency
    zstd = None


CONFIG_FILE = Path("~/.config/wechat-local-vault.json").expanduser()
DEFAULT_VAULT_DIR = Path("~/Library/Application Support/wechat-local-vault").expanduser()
DEFAULT_DECRYPTED_DIR = DEFAULT_VAULT_DIR / "decrypted/current"
DEFAULT_EXPORTS_DIR = Path("~/Documents/wechat-local-vault/exports").expanduser()
STATE_FILE = DEFAULT_VAULT_DIR / "state/vault_cli_last_check.json"
INCLUDE_IDENTIFIERS = ContextVar("include_identifiers", default=False)

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZSTD_DECODER = zstd.ZstdDecompressor() if zstd else None
# Received files are kept per month; another file with the same name is saved as name(1).ext.
RENAMED_COPY_LIMIT = 20

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


def decode_bytes(value, compression_flag=None) -> bytes | None:
    """Stored body as bytes, zstd-decompressed when marked; None if decompression fails."""
    data = bytes(value)
    should_try_zstd = data.startswith(ZSTD_MAGIC) or compression_flag == 4
    if should_try_zstd and ZSTD_DECODER:
        try:
            return ZSTD_DECODER.decompress(data, max_output_size=1_000_000)
        except Exception:
            return None
    return data


def decode_value(value, compression_flag=None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    data = decode_bytes(value, compression_flag)
    if data is None:
        return "[压缩消息解码失败]"
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return "[二进制内容]"


def output(data, fmt: str, render=None) -> None:
    # Text is rendered from the same public copy as JSON, so it hides the same identifiers.
    data = public_value(data, include_identifiers=INCLUDE_IDENTIFIERS.get())
    if fmt == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data) if render else data)


def visible(value) -> bool:
    return bool(value) and value != HIDDEN_ID


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
    return shared_message_table(username)


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


def username_for_table_from_contacts(table: str, contacts: dict[str, dict]) -> str:
    if not table.startswith("Msg_"):
        return ""
    target = table[4:]
    for username in contacts:
        if hashlib.md5(username.encode()).hexdigest() == target:
            return username
    return ""


def message_columns(con: sqlite3.Connection, table: str) -> dict[str, str]:
    return shared_message_columns(table_columns(con, table), legacy_mac=True)


def build_select_sql(table: str, cols: dict[str, str], start_ts: int | None, end_ts: int | None, keyword: str | None, type_name: str | None, limit: int | None, offset: int = 0, decode_compressed: bool = False) -> tuple[str, list]:
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
        match = f"{cols['message_content']} LIKE ?"
        if decode_compressed and cols.get("local_type"):
            # LIKE never sees inside zstd BLOBs (long texts, links, files, forwards);
            # the caller decodes those rows and matches their readable text instead.
            skipped = ", ".join(str(base) for base in sorted(PLACEHOLDER_TYPES))
            match = f"({match} OR (typeof({cols['message_content']}) = 'blob' AND ({cols['local_type']} & 4294967295) NOT IN ({skipped})))"
        clauses.append(match)
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
    # A stored group prefix is one username, not arbitrary prose or XML.
    # XML payloads can themselves end with ':\n'; treating the whole payload
    # as a sender used to erase their content. Keep an ambiguous body intact.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?:@openim)?", sender):
        return sender, text
    return "", content


def received_file_path(month_dir: Path, title: str, expected_size: int | None) -> Path | None:
    """Locate a received file, including WeChat's renamed copies such as name(1).zip.

    The size recorded in the message decides between same-named files. Without it,
    only the exact name is trusted: a renamed copy may belong to another chat.
    """
    if Path(title).name != title or not month_dir.exists():
        return None
    stem, suffix = os.path.splitext(title)
    names = [title] + [f"{stem}({n}){suffix}" for n in range(1, RENAMED_COPY_LIMIT + 1)]
    root = month_dir.resolve()
    for name in names:
        candidate = month_dir / name
        try:
            if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
                continue
            if expected_size is None:
                if name == title:
                    return candidate
            elif candidate.stat().st_size == expected_size:
                return candidate
        except OSError:
            continue
    return None


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
    readable = format_message_content(local_type, content)
    if not readable.startswith("[文件] "):
        return None
    title = readable.removeprefix("[文件] ").strip()
    if not title:
        return None
    file_dir = db_dir.parent / "msg/file"
    if not file_dir.exists():
        return f"[文件] {title}"
    month_dir = file_dir / datetime.fromtimestamp(ts).strftime("%Y-%m")
    path = received_file_path(month_dir, title, file_attachment_size(content))
    return f"[文件] {title}\n{path}" if path else f"[文件] {title}"


def format_content(local_type: int | None, content: str, resolve_media: bool, db_dir: Path | None, chat_username: str, ts: int) -> str:
    hint = media_hint(local_type, content, resolve_media, db_dir, chat_username, ts)
    if hint:
        return format_message_content(1, hint)
    return format_message_content(local_type, content)


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
    output(data, args.format, render_status_text)


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
            _, summary = parse_sender_prefix(summary)
            summary = format_message_content(row["last_msg_type"], summary)
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
                "last_msg_sender": sender_username,
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
    output(rows, args.format, lambda shown: render_sessions_text(shown, "最近会话"))


def command_unread(args: argparse.Namespace) -> None:
    rows = session_rows(resolve_decrypted_dir(args.decrypted_dir), True, args.limit)
    output(rows, args.format, lambda shown: render_sessions_text(shown, "未读会话"))


def command_new_messages(args: argparse.Namespace) -> None:
    rows = session_rows(resolve_decrypted_dir(args.decrypted_dir), False, None)
    current = {row["username"]: row["timestamp"] for row in rows}
    previous = load_json(STATE_FILE)
    if not previous:
        save_json(STATE_FILE, current)
        unread = [row for row in rows if row["unread"] > 0]
        data = {"first_call": True, "unread_count": len(unread), "messages": unread}
        output(data, args.format, lambda shown: render_sessions_text(shown["messages"], "当前未读会话") if shown["messages"] else "当前无未读消息；已记录状态，下次只返回新增。")
        return
    changed = [row for row in rows if row["timestamp"] > int(previous.get(row["username"], 0) or 0)]
    changed.sort(key=lambda item: item["timestamp"])
    save_json(STATE_FILE, current)
    data = {"first_call": False, "new_count": len(changed), "messages": changed}
    output(data, args.format, lambda shown: render_sessions_text(shown["messages"], "新增消息") if shown["messages"] else "无新消息")


def command_contacts(args: argparse.Namespace) -> None:
    contacts, _ = load_contacts(resolve_decrypted_dir(args.decrypted_dir))
    if args.detail:
        item = resolve_chat(args.detail, contacts)
        if not item:
            raise SystemExit(f"找不到联系人: {args.detail}")
        data = {k: v for k, v in item.items() if k != "raw"}
        output(data, args.format, render_contact_detail)
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
    output({"count": len(items), "contacts": items}, args.format, lambda shown: render_contacts_text(shown["contacts"]))


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
        # Identifiers stay hidden unless --include-identifiers was given.
        if visible(item.get("alias")):
            lines.append(f"   微信号: {item['alias']}")
        if visible(item.get("username")):
            lines.append(f"   username: {item['username']}")
    return "\n".join(lines)


def render_contact_detail(item: dict) -> str:
    lines = [item["display_name"]]
    if visible(item.get("username")):
        lines.append(f"username: {item['username']}")
    for key, label in [("remark", "备注"), ("nick_name", "昵称"), ("alias", "微信号"), ("description", "描述"), ("avatar", "头像")]:
        if visible(item.get(key)):
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
    owner_username = ""
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
        members = [{"display_name": item["name"], "username": item["sender_username"], "message_count": item["count"]} for item in stats["top_senders"]]
    members.sort(key=lambda item: (not item.get("is_owner", False), item.get("display_name", "")))
    data = {"group": group["display_name"], "username": group["username"], "owner": owner, "owner_username": owner_username,
            "member_count": len(members), "members": members}
    output(data, args.format, render_members_text)


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
    output(data, args.format, lambda shown: render_messages_text(shown["messages"]))


def render_messages_text(rows: list[dict]) -> str:
    if not rows:
        return "没有找到消息"
    lines = []
    for row in rows:
        sender = f"{row['sender']}: " if row.get("sender") else ""
        lines.append(f"[{row['time']}] {sender}{row['content']}")
    return "\n".join(lines)


def search_table(con: sqlite3.Connection, db_name: str, table: str, chat: dict, contacts: dict[str, dict], name2id: dict[int, str], keyword: str, start_ts: int | None, end_ts: int | None, type_name: str | None, limit: int) -> list[dict]:
    """Newest-first messages of one table whose readable text contains keyword.

    A compressed body must contain the keyword before it is rendered, compared the
    way LIKE compares plain rows (ASCII case-insensitive bytes), so a label such as
    "[文件]" never matches on its own. Keywords with XML-escaped characters skip
    that shortcut and rely on rendering.
    """
    if limit <= 0:
        return []
    needle = keyword.lower()
    needle_bytes = keyword.encode("utf-8").lower()
    shortcut = not any(ch in keyword for ch in "&<>\"'")
    cols = message_columns(con, table)
    sql, params = build_select_sql(table, cols, start_ts, end_ts, keyword, type_name, None, 0, decode_compressed=True)
    found: list[dict] = []
    for row in con.execute(sql, params):
        body = row["message_content"]
        if shortcut and isinstance(body, bytes):
            data = decode_bytes(body, row["compression_flag"])
            if data is not None and needle_bytes not in data.lower():
                continue
        msg = row_to_message(row, db_name, table, chat, contacts, name2id)
        if needle in msg["content"].lower() and matches_type(msg["local_type"], type_name):
            msg["chat"] = chat["display_name"]
            msg["chat_username"] = chat["username"]
            found.append(msg)
            if len(found) >= limit:
                break
    return found


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
            for db_path, table in find_chat_tables(decrypted_dir, chat):
                with connect(db_path) as con:
                    results.extend(search_table(con, db_path.name, table, chat, contacts, load_name2id(con), args.keyword, start_ts, end_ts, args.type, candidate_limit))
    else:
        # Hash each known username once instead of rescanning every name for every table.
        contact_tables = {message_table(username): username for username in contacts}
        for db_path in message_dbs(decrypted_dir):
            with connect(db_path) as con:
                tables = [row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
                name2id = load_name2id(con)
                name_tables = {message_table(username): username for username in name2id.values()}
                for table in tables:
                    username = name_tables.get(table) or contact_tables.get(table, "")
                    chat = {
                        "username": username,
                        "display_name": display_name(username, contacts) if username else table,
                        "is_group": "@chatroom" in username,
                    }
                    try:
                        results.extend(search_table(con, db_path.name, table, chat, contacts, name2id, args.keyword, start_ts, end_ts, args.type, candidate_limit))
                    except sqlite3.Error:
                        continue
    results.sort(key=lambda item: item["timestamp"], reverse=True)
    page = results[args.offset : args.offset + args.limit]
    page.sort(key=lambda item: item["timestamp"])
    data = {"keyword": args.keyword, "count": len(page), "messages": page}
    output(data, args.format, lambda shown: render_search_text(shown["messages"]))


def render_search_text(rows: list[dict]) -> str:
    if not rows:
        return "没有找到匹配消息"
    return "\n".join(f"[{row['time']}] [{row.get('chat', '')}] {row.get('sender', '')}: {row['content']}".strip() for row in rows)


def collect_stats(decrypted_dir: Path, chat: dict, start_ts: int | None, end_ts: int | None) -> dict:
    contacts, _ = load_contacts(decrypted_dir)
    total = 0
    type_counts: dict[str, int] = {}
    sender_counts: dict[str, int] = {}
    sender_usernames: dict[str, str] = {}
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
                sender_usernames.setdefault(sender, sender_username)
            for row in con.execute(f"SELECT cast(strftime('%H', {cols['create_time']}, 'unixepoch', 'localtime') as integer) AS hour, COUNT(*) AS count FROM [{table}] {where} GROUP BY hour", params):
                if row["hour"] is not None:
                    hourly[int(row["hour"])] += int(row["count"] or 0)
    return {
        "total": total,
        "type_breakdown": dict(sorted(type_counts.items(), key=lambda item: item[1], reverse=True)),
        "top_senders": [{"name": name, "sender_username": sender_usernames.get(name, ""), "count": count}
                        for name, count in sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)[:10]],
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
    output(data, args.format, render_stats_text)


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
    body = public_value(body, include_identifiers=INCLUDE_IDENTIFIERS.get())
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
    safe_payload = public_value(payload, include_identifiers=INCLUDE_IDENTIFIERS.get())
    source_json.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = render_digest_source_markdown(group, rows, stats, range_text)
    source_md.write_text(public_value(markdown, include_identifiers=INCLUDE_IDENTIFIERS.get()) + "\n", encoding="utf-8")
    result = {
        "folder": str(folder),
        "source_json": str(source_json),
        "source_markdown": str(source_md),
        "message_count": len(rows),
        "digest_stats_count": stats["message_count"],
        "last_message_timestamp": stats["last_message_timestamp"],
        "next_step": "Use the source files to draft a normal or roast digest, then update history.json after the final digest is accepted.",
    }
    output(result, args.format, lambda shown: "\n".join(f"{k}: {v}" for k, v in shown.items()))


def render_export_markdown(chat: dict, rows: list[dict], start_time: str | None, end_time: str | None) -> str:
    chat = public_value(chat, include_identifiers=INCLUDE_IDENTIFIERS.get())
    rows = public_value(rows, include_identifiers=INCLUDE_IDENTIFIERS.get())
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
                # Kept beside the names so a name that fell back to an identifier is hidden with it.
                "sender_username": str(row["fromusr"] or ""),
                "chat_username": str(row["realchatname"] or ""),
            })
    data = {"count": len(rows), "favorites": rows}
    output(data, args.format, lambda shown: render_favorites_text(shown["favorites"]))


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
    output(data, args.format, lambda shown: render_moments_text(shown["moments"]))


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


# pending: messages that may still need the account owner. Signals verified on a
# real 4.x vault: a private chat whose last word is the other side's, @me, quotes
# of me, my name and @all in groups, transfers not received, private red packets
# and missed calls. Each is a candidate for a person or agent to judge.

PENDING_MAX_WINDOW_DAYS = 14
PENDING_TRANSFER_LOOKBACK_DAYS = 3
PENDING_PRIVATE_TAIL = 30
PENDING_SHOWN_TAIL = 8
PENDING_TEXT_LIMIT = 300
PENDING_MANIFEST_MAX_AGE_HOURS = 2
# Per-group caps keep chatty groups from burying the rest of the report.
PENDING_CAPS = {"at_all_per_group": 2, "at_all_total": 30, "mention_per_group": 3, "mention_total": 30, "hits_total": 80}
PENDING_REQUIRED_DB = re.compile(r"^(?:contact/contact|session/session|message/message_\d+)\.db$")
PENDING_COLUMNS = ("local_id", "local_type", "create_time", "real_sender_id", "message_content",
                   "compress_content", "compression_flag", "source", "source_flag")
TRANSFER_TYPE = (2000 << 32) | 49
RED_PACKET_TYPE = (2001 << 32) | 49
QUOTE_SUBTYPE = 57
PAT_SUBTYPE = 62
CALL_TYPE = 50
SYSTEM_TYPES = {10000, 10002}
SYSTEM_ACCOUNTS = {
    "brandsessionholder", "brandservicesessionholder", "notifymessage", "filehelper",
    "weixin", "fmessage", "floatbottle", "medianote", "newsapp", "qqmail", "qmessage",
    "tmessage", "mphelper", "qqsafe", "voip", "voipapp", "masssendapp", "feedsapp",
    "blogapp", "qqfriend", "officialaccounts", "helper_entry", "exmail_tool",
    "userexperience_alarm", "notification_messages",
}
ACK_TEXT = re.compile(
    r"^(?:好的?|好滴|好嘞|嗯+|哦+|噢+|ok|okk|收到|谢谢|感谢|多谢|哈+|嘿+|行|可以|没问题|👌|👍|🙏|"
    r"\[[^\]]{1,6}\])+[!！。~～.]*$",
    re.I,
)
PENDING_COUNT_LABELS = [
    ("private_pending", "私聊待回复"),
    ("private_pending_new", "其中本期新增"),
    ("at_me", "@我"),
    ("quote_me", "引用我"),
    ("name_mention", "提到我"),
    ("at_all", "@所有人"),
    ("pending_to_me", "待收转账"),
    ("refunded_to_me", "已退还转账"),
    ("pending_from_me", "转出未收"),
    ("red_packets", "私聊红包"),
    ("missed_calls", "未接来电"),
]


def fmt_minute(ts: int | float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def clip(text: str, limit: int = PENDING_TEXT_LIMIT) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def display_text(text: str, limit: int = PENDING_TEXT_LIMIT) -> str:
    """One display line: envelopes become placeholders, credentials and IDs are hidden.

    Quote titles, quoted text and transfer memos are typed by people and may carry
    XML; one raw envelope would otherwise turn the whole text report into a placeholder.
    """
    return clip(format_message_content(1, text), limit)


def chat_key(username: str) -> str:
    # Stable across runs, so a later check can tell which chats were already listed.
    return hashlib.md5(username.encode("utf-8")).hexdigest()[:10]


def xml_field(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{tag}>", text, re.S)
    return html.unescape(match.group(1)).strip() if match else ""


def is_private_chat(username: str) -> bool:
    return (bool(username) and "@chatroom" not in username
            and not username.startswith(("gh_", "@")) and username not in SYSTEM_ACCOUNTS)


class PendingScan:
    """Read-only view of one decrypted vault for the pending check."""

    def __init__(self, decrypted_dir: Path) -> None:
        self.contacts, _ = load_contacts(decrypted_dir)
        if not self.contacts:
            raise SystemExit("联系人库为空或缺失，请先增量解析")
        self.me = ""
        self.my_names: set[str] = set()
        self.dbs: list[tuple[sqlite3.Connection, set[str], dict[int, str]]] = []
        for path in message_dbs(decrypted_dir):
            con = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")}
            self.dbs.append((con, tables, load_name2id(con)))

    def close(self) -> None:
        for con, _, _ in self.dbs:
            con.close()

    def fetch(self, username: str, *, start: int | None = None, end: int | None = None,
              last: int | None = None, local_type: int | None = None) -> list[dict]:
        """One chat's messages from every message DB, oldest first; `last` keeps the newest N."""
        table = message_table(username)
        rows = []
        for index, (con, tables, name2id) in enumerate(self.dbs):
            if table not in tables:
                continue
            cols = message_columns(con, table)
            available = table_columns(con, table)
            cols.update({key: name for key, name in (("source", "source"), ("source_flag", "WCDB_CT_source")) if name in available})
            if "create_time" not in cols or (local_type is not None and "local_type" not in cols):
                continue
            clauses, params = [], []
            if start is not None:
                clauses.append(f"{cols['create_time']} >= ?")
                params.append(start)
            if end is not None:
                clauses.append(f"{cols['create_time']} <= ?")
                params.append(end)
            if local_type is not None:
                clauses.append(f"{cols['local_type']} = ?")
                params.append(local_type)
            select = ", ".join(f"{cols.get(key, 'NULL')} AS {key}" for key in PENDING_COLUMNS)
            sql = f"SELECT {select} FROM [{table}]"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += f" ORDER BY {cols['create_time']} DESC"
            if last:
                sql += " LIMIT ?"
                params.append(last)
            rows.extend(self._message(row, name2id, index) for row in con.execute(sql, params))
        rows.sort(key=lambda m: (m["ts"], m["db"], m["local_id"]))
        return rows[-last:] if last else rows

    def _message(self, row: sqlite3.Row, name2id: dict[int, str], db_index: int) -> dict:
        content = decode_value(row["message_content"], row["compression_flag"]) or decode_value(row["compress_content"], row["compression_flag"])
        prefix, body = parse_sender_prefix(content)
        try:
            sender = name2id.get(int(row["real_sender_id"]), "")
        except (TypeError, ValueError):
            sender = ""
        base, sub = split_msg_type(row["local_type"])
        return {
            "db": db_index,
            "local_id": int(row["local_id"] or 0),
            "ts": int(row["create_time"] or 0),
            "local_type": row["local_type"],
            "base": base,
            "sub": sub,
            "sender": sender or prefix,
            "body": body,
            "source": decode_value(row["source"], row["source_flag"]),
        }

    def identify_self(self, tails: dict[str, list[dict]]) -> None:
        """Find the account owner: the one speaker besides the partner in private chats.

        A private chat holds only the partner, the owner and sender-less notices, so the
        data decides even when --decrypted-dir points at another account's vault. The
        configured wxid, minus the 4-hex suffix of its data folder, is used when it is
        among those speakers or when no recent private chat has an owner message.
        """
        speakers: Counter[str] = Counter()
        for username, messages in tails.items():
            speakers.update({m["sender"] for m in messages if m["sender"] and m["sender"] != username})
        wxid = str(load_config().get("wxid") or "")
        configured = next((name for name in (wxid, re.sub(r"_[0-9a-f]{4}$", "", wxid)) if name and name in self.contacts), "")
        if configured and (configured in speakers or not speakers):
            self.me = configured
        elif speakers:
            self.me = speakers.most_common(1)[0][0]
        else:
            raise SystemExit("无法确认本账号：最近私聊里没有本人发言，配置的账号也不在联系人库中")
        contact = self.contacts.get(self.me, {})
        self.my_names = {name for name in (contact.get("nick_name"), contact.get("remark")) if name and len(name) >= 2}

    def name_of(self, username: str, fallback: str = "未知成员") -> str:
        if username == self.me:
            return "我"
        name = self.contacts.get(username, {}).get("display_name") or ""
        if not name or name == username:
            return fallback
        # Keep names verbatim: `history "<name>"` lookups match them exactly.
        return display_text(name) if ENVELOPE.search(html.unescape(name)) else redact_text(name)

    def contact_kind(self, username: str) -> str:
        if username.endswith("@openim"):
            return "企业微信"
        return "好友" if self.contacts.get(username, {}).get("raw", {}).get("local_type") == 1 else "非好友"

    def group_muted(self, username: str) -> bool:
        # chat_room_notify 0 = 消息免打扰 (checked against unread counts on a real vault).
        return self.contacts.get(username, {}).get("raw", {}).get("chat_room_notify") == 0

    def readable(self, msg: dict) -> str:
        body = msg["body"]
        if msg["local_type"] == TRANSFER_TYPE:
            amount, memo = xml_field(body, "feedesc"), xml_field(body, "pay_memo")
            text = f"[转账] {amount}" + (f"（备注：{memo}）" if memo else "")
        elif msg["base"] == CALL_TYPE:
            text = "[通话] " + xml_field(body, "msg")
        elif msg["base"] == 49 and msg["sub"] == QUOTE_SUBTYPE:
            text = xml_field(body, "title")
            refer = re.search(r"<refermsg>(.*?)</refermsg>", body, re.S)
            if refer:
                block = refer.group(1)
                quoted_type = xml_field(block, "type") or "1"
                quoted = format_message_content(int(quoted_type) if quoted_type.isdigit() else 49, xml_field(block, "content"))
                text += f"（引用 {xml_field(block, 'displayname') or '某人'}：{clip(quoted, 80)}）"
        else:
            text = format_message_content(msg["local_type"], body)
        return display_text(text)

    def at_list(self, msg: dict) -> set[str]:
        raw = xml_field(msg["source"], "atuserlist") if "atuserlist" in msg["source"] else ""
        return {item.strip() for item in raw.split(",") if item.strip()}

    def quotes_me(self, msg: dict) -> bool:
        if not (msg["base"] == 49 and msg["sub"] == QUOTE_SUBTYPE):
            return False
        refer = re.search(r"<refermsg>(.*?)</refermsg>", msg["body"], re.S)
        return bool(refer) and xml_field(refer.group(1), "chatusr") == self.me

    def view(self, msg: dict) -> dict:
        return {"time": fmt_minute(msg["ts"]), "ts": msg["ts"], "from": self.name_of(msg["sender"]), "text": self.readable(msg)}


def pending_manifest(decrypted_dir: Path) -> dict:
    """Newest successful decrypt manifest written for this decrypted dir, and its data gaps.

    decrypt_all_dbs.py keeps manifests in <vault>/manifests beside decrypted/current and
    records the output each one describes, so another account's run is never used.
    """
    info = {"name": "", "created_at": "", "created_ts": 0.0, "gaps": []}
    target = decrypted_dir.expanduser().resolve()
    aborted = ""
    for path in sorted((decrypted_dir.parent.parent / "manifests").glob("decrypt-*.json"), reverse=True):
        try:
            data = load_json(path)
            if not data.get("decrypted_dir") or Path(str(data["decrypted_dir"])).expanduser().resolve() != target:
                continue
            created = datetime.fromisoformat(str(data["created_at"])).timestamp()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if data.get("aborted"):
            aborted = aborted or path.name
            continue
        stale = set(data.get("stale_databases") or [])
        for record in data.get("records") or []:
            rel = str(record.get("rel") or "")
            if PENDING_REQUIRED_DB.match(rel) and (record.get("status") not in ("ok", "unchanged") or rel in stale):
                info["gaps"].append(f"{rel}: {record.get('status')} {clip(str(record.get('reason') or ''), 120)}".strip())
        info.update(name=path.name, created_at=fmt_minute(created), created_ts=created)
        break
    if aborted:
        info["gaps"].insert(0, f"最近一次解析被中止（{aborted}），数据停留在{info['created_at'] or '更早的解析'}")
    if not info["name"]:
        info["gaps"].append("找不到这个明文目录的解密 manifest，无法确认数据新鲜度")
    return info


def load_previous_pending(value: str | None) -> dict:
    """An earlier pending JSON (missed_check collect output works too)."""
    if not value:
        return {}
    path = Path(value).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise SystemExit(f"无法读取 --previous 指定的 JSON: {path}")
    return data


def pending_window(value: str, until: int, previous: dict) -> tuple[int, str]:
    if value == "last":
        last = (previous.get("window") or {}).get("until")
        if not isinstance(last, int):
            raise SystemExit("--since last 需要用 --previous 指定上次的 pending JSON")
        since, how = last, "接上次检查"
    elif re.fullmatch(r"\d+[hd]", value):
        since = until - int(value[:-1]) * (3600 if value.endswith("h") else 86400)
        how = f"近 {value}"
    else:
        since, how = parse_time(value) or 0, "指定起点"
    floor = until - PENDING_MAX_WINDOW_DAYS * 86400
    if since < floor:
        since, how = floor, how + f"（超过 {PENDING_MAX_WINDOW_DAYS} 天，已截断）"
    return since, how


def low_signal(messages: list[dict]) -> bool:
    for msg in messages:
        # Stickers, system notices and 拍一拍 (49/62) carry nothing to answer.
        if msg["base"] == 47 or msg["base"] in SYSTEM_TYPES or (msg["base"] == 49 and msg["sub"] == PAT_SUBTYPE):
            continue
        if msg["base"] == 1 and ACK_TEXT.match(re.sub(r"\s+", "", msg["body"] or "")):
            continue
        return False
    return True


def pending_private(scan: PendingScan, sessions: list[dict], tails: dict[str, list[dict]], since: int, floor: int, seen: set[tuple]) -> list[dict]:
    items = []
    for session in sessions:
        username = session["username"]
        tail = tails.get(username)
        if tail is None:
            continue
        # A connected call counts as having talked, whoever dialled.
        cut = max((i for i, m in enumerate(tail)
                   if (m["sender"] == scan.me and m["base"] not in SYSTEM_TYPES)
                   or (m["base"] == CALL_TYPE and "通话时长" in m["body"])), default=-1)
        waiting = [m for m in tail[cut + 1:] if m["sender"] != scan.me and m["base"] != 10002]
        if not waiting or waiting[-1]["ts"] < floor:
            continue
        key = chat_key(username)
        items.append({
            "chat": scan.name_of(username, "未知联系人"),
            "username": username,
            "chat_key": key,
            "kind": scan.contact_kind(username),
            "unread": session["unread"],
            "waiting_count": len(waiting),
            "waiting_since": fmt_minute(waiting[0]["ts"]),
            "last_time": fmt_minute(waiting[-1]["ts"]),
            "last_ts": waiting[-1]["ts"],
            "new_in_window": waiting[-1]["ts"] >= since,
            "seen_before": (key, waiting[-1]["ts"]) in seen,
            "low_signal": low_signal(waiting),
            "messages": [scan.view(m) for m in waiting[-PENDING_SHOWN_TAIL:]],
        })
    items.sort(key=lambda item: (item["low_signal"], -item["last_ts"]))
    return items


def unnamed_group(scan: PendingScan, messages: list[dict]) -> str:
    """WeChat titles a nameless group by its members; mirror that with the busiest senders."""
    counts = Counter(m["sender"] for m in messages if m["sender"] and m["sender"] != scan.me)
    names = [scan.name_of(username) for username, _ in counts.most_common(3)]
    names = [name for name in names if name != "未知成员"]
    return f"未命名群（{'、'.join(names)} 等）" if names else "未命名群"


def pending_groups(scan: PendingScan, sessions: list[dict], since: int, until: int) -> dict[str, list[dict]]:
    hits: dict[str, list[dict]] = {"at_me": [], "quote_me": [], "name_mention": [], "at_all": []}
    for session in sessions:
        username = session["username"]
        if "@chatroom" not in username or session["timestamp"] < since:
            continue
        muted = scan.group_muted(username)
        messages = scan.fetch(username, start=since, end=until)
        group = scan.name_of(username, "") or unnamed_group(scan, messages)
        my_times = [m["ts"] for m in messages if m["sender"] == scan.me]
        at_all_here = mention_here = 0
        for index, msg in enumerate(messages):
            if msg["sender"] == scan.me:
                continue
            ats = scan.at_list(msg)
            text = scan.readable(msg)
            if scan.me in ats:
                kind = "at_me"
            elif scan.quotes_me(msg):
                kind = "quote_me"
            elif "notify@all" in ats or text.startswith("@所有人"):
                kind = "at_all"
            elif msg["base"] == 1 and any(name in text for name in scan.my_names):
                kind = "name_mention"
            else:
                continue
            if kind == "at_all":
                at_all_here += 1
                if at_all_here > PENDING_CAPS["at_all_per_group"]:
                    continue
            if kind == "name_mention":
                mention_here += 1
                if mention_here > PENDING_CAPS["mention_per_group"]:
                    continue
            item = {"chat": group, "username": username, **scan.view(msg), "muted_group": muted}
            if kind != "at_all":
                item["you_spoke_after"] = any(ts > msg["ts"] for ts in my_times)
                context = [m for m in messages[max(0, index - 3):index] if m["base"] not in SYSTEM_TYPES]
                item["context"] = [scan.view(m) for m in context]
            hits[kind].append(item)
    limits = {"at_all": PENDING_CAPS["at_all_total"], "name_mention": PENDING_CAPS["mention_total"]}
    for kind, items in hits.items():
        # Unmuted groups first: their notices were meant to reach the owner.
        items.sort(key=lambda item: (item["muted_group"], -item["ts"]))
        del items[limits.get(kind, PENDING_CAPS["hits_total"]):]
    return hits


def pending_money_and_calls(scan: PendingScan, sessions: list[dict], since: int, until: int) -> tuple[dict, list[dict]]:
    lookback = min(since, until - PENDING_TRANSFER_LOOKBACK_DAYS * 86400)
    transfers: dict[str, dict] = {}
    red_packets, calls = [], []
    for session in sessions:
        username = session["username"]
        if session["timestamp"] < lookback:
            continue
        chat = scan.name_of(username, "未知会话")
        for msg in scan.fetch(username, start=lookback, end=until, local_type=TRANSFER_TYPE):
            body = msg["body"]
            tid = xml_field(body, "transferid") or f"{chat_key(username)}-{msg['ts']}"
            entry = transfers.setdefault(tid, {"chat": chat, "username": username, "states": {}})
            state = xml_field(body, "paysubtype")
            entry["states"][state] = {"ts": msg["ts"], "sender": msg["sender"]}
            if state == "1":
                # Only the initiating message names the parties: payer_username is often
                # empty there (the sender pays), and a refund's receiver is the payer.
                invalid = xml_field(body, "invalidtime")
                entry.update({
                    "payer": xml_field(body, "payer_username") or msg["sender"],
                    "receiver": xml_field(body, "receiver_username"),
                    "amount": xml_field(body, "feedesc"),
                    "memo": xml_field(body, "pay_memo"),
                    "invalid": int(invalid) if invalid.isdigit() else 0,
                })
        if not is_private_chat(username) or session["timestamp"] < since:
            continue
        window = scan.fetch(username, start=since, end=until)
        my_times = [m["ts"] for m in window if m["sender"] == scan.me]
        for index, msg in enumerate(window):
            if msg["sender"] == scan.me:
                continue
            if msg["local_type"] == RED_PACKET_TYPE:
                opened = any(m["base"] == 10000 and "领取" in m["body"] for m in window[index + 1:])
                red_packets.append({"chat": chat, "username": username, **scan.view(msg), "opened_hint": opened})
            elif msg["base"] == CALL_TYPE and "通话时长" not in msg["body"]:
                contacted = any(ts > msg["ts"] for ts in my_times)
                calls.append({"chat": chat, "username": username, **scan.view(msg), "you_contacted_after": contacted})
    now = time.time()
    money: dict[str, list[dict]] = {"pending_to_me": [], "refunded_to_me": [], "pending_from_me": [], "red_packets": red_packets}
    for entry in transfers.values():
        states = entry["states"]
        if "1" not in states:
            continue  # started before the lookback; its parties are unknown
        settled = bool({"3", "4"} & set(states))
        view = {"chat": entry["chat"], "username": entry["username"], "amount": display_text(entry["amount"]),
                "memo": display_text(entry["memo"], 80), "time": fmt_minute(states["1"]["ts"])}
        if entry["receiver"] == scan.me:
            view["from"] = scan.name_of(entry["payer"], "对方")
            if not settled:
                view["expires"] = fmt_minute(entry["invalid"]) if entry["invalid"] else ""
                view["maybe_expired"] = bool(entry["invalid"]) and entry["invalid"] < now
                money["pending_to_me"].append(view)
            elif "4" in states and states["4"]["ts"] >= since and (
                states["4"]["sender"] != scan.me or (entry["invalid"] and states["4"]["ts"] >= entry["invalid"])
            ):
                # Refunded at/after the deadline or not by the owner: it timed out unreceived.
                # An early refund the owner sent is a deliberate 退还, not a miss.
                view["refunded_at"] = fmt_minute(states["4"]["ts"])
                money["refunded_to_me"].append(view)
        elif entry["payer"] == scan.me and not settled:
            view["to"] = scan.name_of(entry["receiver"], "对方")
            money["pending_from_me"].append(view)
    return money, calls


def write_private_output(path: Path, body, fmt: str, render=None) -> None:
    """Write the full result for the owner only: it quotes private chats."""
    body = public_value(body, include_identifiers=INCLUDE_IDENTIFIERS.get())
    if fmt == "json":
        text = json.dumps(body, ensure_ascii=False, indent=2)
    else:
        text = render(body) if render else body
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")
    os.chmod(path, 0o600)


def command_pending(args: argparse.Namespace) -> None:
    if args.pending_days < 1:
        raise SystemExit("--pending-days 至少为 1")
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    manifest = pending_manifest(decrypted_dir)
    now = time.time()
    # The vault holds nothing newer than its last decrypt, so the window ends there.
    until = int(min(manifest["created_ts"], now)) if manifest["created_ts"] else int(now)
    if manifest["created_ts"] and now - manifest["created_ts"] > PENDING_MANIFEST_MAX_AGE_HOURS * 3600:
        manifest["gaps"].append(f"manifest 已超过 {PENDING_MANIFEST_MAX_AGE_HOURS} 小时，请先增量解析")
    previous = load_previous_pending(args.previous)
    since, how = pending_window(args.since, until, previous)
    seen = {(item.get("chat_key"), item.get("last_ts")) for item in previous.get("private_pending") or [] if isinstance(item, dict)}
    sessions = session_rows(decrypted_dir, False, None)
    floor = until - args.pending_days * 86400
    scan = PendingScan(decrypted_dir)
    try:
        tails = {session["username"]: scan.fetch(session["username"], end=until, last=PENDING_PRIVATE_TAIL)
                 for session in sessions if is_private_chat(session["username"]) and session["timestamp"] >= floor}
        scan.identify_self(tails)
        private = pending_private(scan, sessions, tails, since, floor, seen)
        groups = pending_groups(scan, sessions, since, until)
        money, calls = pending_money_and_calls(scan, sessions, since, until)
    finally:
        scan.close()
    counts = {
        "private_pending": len(private),
        "private_pending_new": sum(1 for item in private if item["new_in_window"] and not item["seen_before"]),
        **{key: len(items) for key, items in groups.items()},
        **{key: len(items) for key, items in money.items()},
        "missed_calls": len(calls),
    }
    data = {
        "generated_at": fmt_minute(now),
        "window": {"since": since, "until": until, "since_text": fmt_minute(since), "until_text": fmt_minute(until), "how": how},
        "pending_days": args.pending_days,
        "manifest": {key: manifest[key] for key in ("name", "created_at", "gaps")},
        "counts": counts,
        "private_pending": private,
        "groups": groups,
        "money": money,
        "missed_calls": calls,
    }
    if not args.output:
        output(data, args.format, render_pending_text)
        return
    path = Path(args.output).expanduser()
    write_private_output(path, data, args.format, render_pending_text)
    summary = {"output": str(path), "window": data["window"], "manifest_gaps": manifest["gaps"], "counts": counts}
    output(summary, args.format, render_pending_summary)


def render_pending_summary(summary: dict) -> str:
    window = summary["window"]
    lines = [
        f"窗口：{window['since_text']} → {window['until_text']}（{window['how']}）",
        "统计：" + "｜".join(f"{label} {summary['counts'][key]}" for key, label in PENDING_COUNT_LABELS),
    ]
    if summary["manifest_gaps"]:
        lines.append("数据缺口：" + "；".join(summary["manifest_gaps"]))
    lines.append(f"完整结果：{summary['output']}")
    return "\n".join(lines)


def render_pending_text(data: dict) -> str:
    window, counts, manifest = data["window"], data["counts"], data["manifest"]
    source = manifest["name"] or "未找到 manifest"
    if manifest["created_at"]:
        source += f"（解析于 {manifest['created_at']}）"
    lines = [
        f"# 待处理消息候选（{window['since_text']} → {window['until_text']}）",
        "",
        f"- 窗口：{window['how']}；私聊待回复回看 {data['pending_days']} 天，转账回看 {PENDING_TRANSFER_LOOKBACK_DAYS} 天",
        f"- 数据：{source}" + ("；缺口：" + "；".join(manifest["gaps"]) if manifest["gaps"] else "；所需消息库均成功或未变化"),
        "- 统计：" + "｜".join(f"{label} {counts[key]}" for key, label in PENDING_COUNT_LABELS),
        "- 说明：候选只是信号，需结合上下文判断；图片/语音内容不可见。",
        "",
        f"## 1. 私聊：对方最后发言、我还没回（近 {data['pending_days']} 天）",
    ]
    if not data["private_pending"]:
        lines.append("无")
    for item in data["private_pending"]:
        tags = [item["kind"], f"未读 {item['unread']}" if item["unread"] else "已读", f"待回 {item['waiting_count']} 条"]
        if item["seen_before"]:
            tags.append("上期已列出")
        if not item["new_in_window"]:
            tags.append("本期无新消息")
        if item["low_signal"]:
            tags.append("疑似客套/表情")
        lines.append(f"### {item['chat']}（{'，'.join(tags)}；最后 {item['last_time']}）")
        lines.extend(f"- {m['time']} {m['text']}" for m in item["messages"])
        if item["waiting_count"] > len(item["messages"]):
            lines.append(f"- …更早还有 {item['waiting_count'] - len(item['messages'])} 条（自 {item['waiting_since']} 起）")
        lines.append("")
    sections = [
        ("at_me", "## 2. 群里 @我"),
        ("quote_me", "## 3. 群里引用我的消息"),
        ("name_mention", "## 4. 群里提到我的名字（未 @）"),
        ("at_all", f"## 5. @所有人（每群最多 {PENDING_CAPS['at_all_per_group']} 条，未免打扰的群在前）"),
    ]
    for key, title in sections:
        lines.append(title)
        items = data["groups"][key]
        if not items:
            lines.append("无")
        for item in items:
            flags = ["免打扰群" if item["muted_group"] else "提醒群"]
            if "you_spoke_after" in item:
                flags.append("之后我在该群发过言" if item["you_spoke_after"] else "之后我未在该群发言")
            lines.append(f"- {item['time']}【{item['chat']}】{item['from']}：{item['text']}（{'，'.join(flags)}）")
            for ctx in item.get("context", []):
                lines.append(f"  - 上文 {ctx['time'][11:]} {ctx['from']}：{clip(ctx['text'], 120)}")
        lines.append("")
    money = data["money"]
    lines.append("## 6. 钱")
    if not any(money.values()):
        lines.append("无")
    for item in money["pending_to_me"]:
        memo = f"，备注 {item['memo']}" if item["memo"] else ""
        expiry = f"，{'可能已过期' if item['maybe_expired'] else '截止'} {item['expires']}" if item.get("expires") else ""
        lines.append(f"- 待我收款：{item['from']} 在【{item['chat']}】{item['time']} 转 {item['amount']}{memo}{expiry}")
    for item in money["refunded_to_me"]:
        lines.append(f"- 已过期退还（我没收）：{item['from']} 在【{item['chat']}】{item['time']} 转 {item['amount']}，{item['refunded_at']} 退回")
    for item in money["pending_from_me"]:
        lines.append(f"- 我转出、对方未收：给 {item['to']}（【{item['chat']}】{item['time']}）{item['amount']}")
    for item in money["red_packets"]:
        lines.append(f"- 私聊红包：{item['chat']} {item['time']}（{'疑似已领取' if item['opened_hint'] else '未见领取记录'}）")
    lines.append("")
    lines.append("## 7. 未接/拒接来电")
    if not data["missed_calls"]:
        lines.append("无")
    for item in data["missed_calls"]:
        contacted = "之后我联系过对方" if item["you_contacted_after"] else "之后我未联系对方"
        lines.append(f"- {item['time']} {item['chat']}：{item['text']}（{contacted}）")
    return "\n".join(lines).rstrip()


# transfers: every transfer in a period, one row per transferid. The payer's message
# (paysubtype 1) names the parties, amount and memo; 3 is the receipt, 4 the return.
TRANSFER_SETTLE_DAYS = 3  # a receipt or return can land after the window that holds the payment
TRANSFER_OWNER_SESSIONS = 50
TRANSFER_DIRECTIONS = {"in": "转入", "out": "转出", "others": "他人之间"}


def transfer_amount(text: str) -> Decimal | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    try:
        return Decimal(match.group(0).replace(",", "")) if match else None
    except InvalidOperation:
        return None


def yuan(value: Decimal) -> str:
    return f"￥{value:,.2f}"


def transfer_status(entry: dict, until: int) -> tuple[str, int]:
    states, invalid = entry["states"], entry["invalid"]
    if "3" in states:
        return "已收款", states["3"]["ts"]
    if "4" in states:
        refund = states["4"]
        # The receiver returns a transfer before its deadline; one that runs out comes back by itself.
        returned = refund["sender"] == entry["receiver"] and not (invalid and refund["ts"] >= invalid)
        return ("已退还" if returned else "超时退还"), refund["ts"]
    if invalid and invalid < until:
        return "已过期未收", 0
    return "待收款", 0


def collect_transfers(scan: PendingScan, usernames: list[str], start: int | None, end: int | None, until: int) -> tuple[list[dict], int]:
    margin = TRANSFER_SETTLE_DAYS * 86400
    fetch_start = start - margin if start is not None else None
    fetch_end = end + margin if end is not None else None
    entries: dict[str, dict] = {}
    for username in usernames:
        for msg in scan.fetch(username, start=fetch_start, end=fetch_end, local_type=TRANSFER_TYPE):
            body = msg["body"]
            tid = xml_field(body, "transferid") or f"{chat_key(username)}-{msg['ts']}"
            entry = entries.setdefault(tid, {"username": username, "states": {}, "invalid": 0})
            state = xml_field(body, "paysubtype")
            entry["states"].setdefault(state, {"ts": msg["ts"], "sender": msg["sender"]})
            if state == "1":
                invalid = xml_field(body, "invalidtime")
                entry.update({
                    "payer": xml_field(body, "payer_username") or msg["sender"],
                    "receiver": xml_field(body, "receiver_username"),
                    "amount": xml_field(body, "feedesc"),
                    "memo": xml_field(body, "pay_memo"),
                    "invalid": int(invalid) if invalid.isdigit() else 0,
                })
    rows, unmatched = [], 0
    for entry in entries.values():
        states = entry["states"]
        first = min(item["ts"] for item in states.values())
        if "1" not in states:
            # The payment message is gone or older than the fetch: amount and parties are unknown.
            if (start is None or first >= start) and (end is None or first <= end):
                unmatched += 1
            continue
        sent = states["1"]["ts"]
        if (start is not None and sent < start) or (end is not None and sent > end):
            continue
        if entry["receiver"] == scan.me:
            direction, other = "in", entry["payer"]
        elif entry["payer"] == scan.me:
            direction, other = "out", entry["receiver"]
        else:
            direction, other = "others", ""
        status, settled = transfer_status(entry, until)
        amount = transfer_amount(entry["amount"])
        rows.append({
            "ts": sent,
            "time": fmt_minute(sent),
            "chat": scan.name_of(entry["username"], "未知会话"),
            "username": entry["username"],
            "direction": TRANSFER_DIRECTIONS[direction],
            "counterpart": scan.name_of(other, "对方") if other else f"{scan.name_of(entry['payer'], '某人')} → {scan.name_of(entry['receiver'], '某人')}",
            "amount": display_text(entry["amount"]) or "金额未知",
            "amount_value": str(amount) if amount is not None else None,
            "memo": display_text(entry["memo"], 120),
            "status": status,
            "settled_at": fmt_minute(settled),
            "expires": fmt_minute(entry["invalid"]) if status == "待收款" and entry["invalid"] else "",
        })
    rows.sort(key=lambda row: row["ts"])
    return rows, unmatched


def transfer_totals(rows: list[dict]) -> dict:
    buckets = {
        "received": ("转入", "已收款"), "paid": ("转出", "已收款"),
        "pending_in": ("转入", "待收款"), "pending_out": ("转出", "待收款"),
    }
    totals = {}
    for key, (direction, status) in buckets.items():
        picked = [row for row in rows if row["direction"] == direction and row["status"] == status]
        values = [Decimal(row["amount_value"]) for row in picked if row["amount_value"] is not None]
        totals[key] = {"count": len(picked), "amount": yuan(sum(values, Decimal(0))), "unknown_amount": len(picked) - len(values)}
    received = sum((Decimal(row["amount_value"]) for row in rows if row["direction"] == "转入" and row["status"] == "已收款" and row["amount_value"]), Decimal(0))
    paid = sum((Decimal(row["amount_value"]) for row in rows if row["direction"] == "转出" and row["status"] == "已收款" and row["amount_value"]), Decimal(0))
    totals["net"] = ("+" if received >= paid else "-") + yuan(abs(received - paid))
    totals["returned"] = sum(1 for row in rows if row["status"] in ("已退还", "超时退还", "已过期未收"))
    return totals


def command_transfers(args: argparse.Namespace) -> None:
    decrypted_dir = resolve_decrypted_dir(args.decrypted_dir)
    start, end = parse_time(args.start_time), parse_time(args.end_time, end_of_day=True)
    if start is not None and end is not None and start > end:
        raise SystemExit("--start-time 晚于 --end-time")
    manifest = pending_manifest(decrypted_dir)
    now = time.time()
    until = int(min(manifest["created_ts"], now)) if manifest["created_ts"] else int(now)
    sessions = session_rows(decrypted_dir, False, None)
    scan = PendingScan(decrypted_dir)
    try:
        private = [s["username"] for s in sessions if is_private_chat(s["username"])][:TRANSFER_OWNER_SESSIONS]
        scan.identify_self({username: scan.fetch(username, end=until, last=PENDING_PRIVATE_TAIL) for username in private})
        if args.chat:
            chats = []
            for query in args.chat:
                chat = resolve_chat(query, scan.contacts)
                if not chat:
                    raise SystemExit(f"找不到聊天对象: {query}")
                chats.append(chat["username"])
        else:
            # Every chat that still has a message table, including ones no longer in the session list.
            tables = set().union(*(tables for _, tables, _ in scan.dbs)) if scan.dbs else set()
            known = dict.fromkeys([*scan.contacts, *(s["username"] for s in sessions)])
            chats = [username for username in known if message_table(username) in tables]
            unnamed = len(tables) - len({message_table(username) for username in chats})
            if unnamed:
                manifest["gaps"].append(f"{unnamed} 个消息表对不上联系人或会话，未统计")
        rows, unmatched = collect_transfers(scan, list(dict.fromkeys(chats)), start, end, until)
    finally:
        scan.close()
    if unmatched:
        manifest["gaps"].append(f"{unmatched} 笔只有收款或退还消息、缺少发起消息，金额和双方未知，未列出")
    data = {
        "range": {"start": fmt_minute(start) if start else "最早", "end": fmt_minute(end) if end else "最新"},
        "chats": "全部会话" if not args.chat else "、".join(scan.name_of(username, "未知会话") for username in dict.fromkeys(chats)),
        "data_until": fmt_minute(until),
        "count": len(rows),
        "totals": transfer_totals(rows),
        "gaps": manifest["gaps"],
        "transfers": rows,
    }
    output(data, args.format, render_transfers_text)


def render_transfers_text(data: dict) -> str:
    totals = data["totals"]
    lines = [
        f"# 微信转账（{data['range']['start']} → {data['range']['end']}，{data['chats']}）",
        f"数据截至 {data['data_until']}，共 {data['count']} 笔",
        f"转入已收 {totals['received']['count']} 笔 {totals['received']['amount']}"
        f"｜转出被收 {totals['paid']['count']} 笔 {totals['paid']['amount']}｜净额 {totals['net']}",
        f"待我收 {totals['pending_in']['count']} 笔 {totals['pending_in']['amount']}"
        f"｜待对方收 {totals['pending_out']['count']} 笔 {totals['pending_out']['amount']}｜退还或过期 {totals['returned']} 笔",
    ]
    unknown = sum(item["unknown_amount"] for key, item in totals.items() if isinstance(item, dict))
    if unknown:
        lines.append(f"{unknown} 笔金额无法识别，未计入合计")
    for gap in data["gaps"]:
        lines.append(f"⚠ {gap}")
    lines.append("")
    for row in data["transfers"]:
        where = "" if row["chat"] == row["counterpart"] else f"（{row['chat']}）"
        memo = f"（备注：{row['memo']}）" if row["memo"] else ""
        status = row["status"] + (f" {row['settled_at']}" if row["settled_at"] else "") + (f"，{row['expires']} 过期" if row["expires"] else "")
        lines.append(f"- {row['time']} {row['direction']} {row['counterpart']}{where} {row['amount']}{memo} · {status}")
    if not data["transfers"]:
        lines.append("这段时间没有转账")
    return "\n".join(lines).rstrip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the local Mac vault or an explicit Windows plaintext snapshot.")
    parser.add_argument("--decrypted-dir", help="覆盖明文 vault 目录")
    parser.add_argument("--include-identifiers", action="store_true", help="显式保留用于本机精确匹配的账号标识；正文 XML 和凭据仍不输出")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="Windows 离线明文快照；snapshot --help 查看用法")
    sub.add_parser("windows", help="Windows 本机只读采集；windows --help 查看用法")

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

    p = sub.add_parser("pending", help="可能漏回/漏看：私聊待回复、@我、引用我、提到我、@所有人、转账、红包、未接来电")
    p.add_argument("--since", default="48h", help="窗口起点：48h、7d、'YYYY-MM-DD HH:MM'，或 last（接 --previous 的终点）；最多回看 14 天")
    p.add_argument("--pending-days", type=int, default=7, help="私聊待回复回看天数")
    p.add_argument("--previous", help="上次的 pending JSON：标记已列出过的私聊，供 --since last 接续")
    p.add_argument("--output", help="完整结果写入此私密文件（权限 600），终端只打印摘要")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_pending)

    p = sub.add_parser("transfers", help="转账记录：金额、方向、备注、状态和合计")
    p.add_argument("--chat", action="append", help="只看这些联系人或群，可重复；不填为全部会话")
    p.add_argument("--start-time", default="", help="起点 YYYY-MM-DD [HH:MM[:SS]]，按发起转账的时间算")
    p.add_argument("--end-time", default="", help="终点 YYYY-MM-DD [HH:MM[:SS]]，只写日期时含当天")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=command_transfers)

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


def main(argv: list[str] | None = None) -> int | None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "windows":
        import windows_live
        return windows_live.main(arguments[1:])
    if arguments and arguments[0] == "snapshot":
        # Route before parsing Mac options or loading any Mac configuration.
        import snapshot_reader
        return snapshot_reader.main(arguments[1:])
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.command in ("snapshot", "windows"):
        parser.error("snapshot/windows 必须是第一个参数，不能与 Mac --decrypted-dir 混用")
    if sys.platform == "win32":
        parser.error("Windows 数据请使用 snapshot --snapshot <目录> 或 windows；Mac 工作流不能在 Windows 自动运行")
    token = INCLUDE_IDENTIFIERS.set(args.include_identifiers)
    try:
        args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            raise SystemExit(redact_text(exc.code, include_identifiers=args.include_identifiers)) from None
        raise
    finally:
        INCLUDE_IDENTIFIERS.reset(token)
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
