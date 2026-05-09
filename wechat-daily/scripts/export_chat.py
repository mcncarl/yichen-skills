#!/usr/bin/env python3
"""
Export one WeChat conversation from the decrypted local vault.

This script never reads WeChat UI. It only reads decrypted SQLite files under:
  ~/Library/Application Support/wechat-daily/decrypted/current

Examples:
  python3 export_chat.py --contact "联系人备注"
  python3 export_chat.py --contact "联系人备注" --mode incremental
  python3 export_chat.py --chat-id contact_username --since 2025-01-01
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
import zstandard as zstd

CONFIG_FILE = Path("~/.config/wechat-daily.json").expanduser()
DEFAULT_VAULT_DIR = Path("~/Library/Application Support/wechat-daily").expanduser()
DEFAULT_DECRYPTED_DIR = DEFAULT_VAULT_DIR / "decrypted/current"
DEFAULT_EXPORTS_DIR = Path("~/Documents/wechat-daily/exports").expanduser()
EXPORT_STATE_FILE = DEFAULT_VAULT_DIR / "state/export_chat_state.json"

MESSAGE_DBS = [
    "message/message_0.db",
    "message/message_1.db",
    "message/message_2.db",
    "message/message_3.db",
]

TYPE_LABELS = {
    1: "文字",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "卡片/链接",
    10000: "系统",
}

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZSTD_DECODER = zstd.ZstdDecompressor()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if str(path).startswith(str(DEFAULT_VAULT_DIR)):
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def resolve_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    config = load_json(CONFIG_FILE)
    decrypted = Path(args.decrypted_dir or config.get("decrypted_dir") or DEFAULT_DECRYPTED_DIR).expanduser()
    exports = Path(args.exports_dir or config.get("exports_dir") or DEFAULT_EXPORTS_DIR).expanduser()
    return decrypted, exports


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.text_factory = bytes
    return con


def decode_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    data = bytes(value)
    if data.startswith(ZSTD_MAGIC):
        try:
            data = ZSTD_DECODER.decompress(data, max_output_size=500000)
        except Exception:
            return "[压缩消息解码失败]"
    return data.decode("utf-8", errors="replace")


def load_contacts(decrypted_dir: Path) -> list[dict]:
    contact_db = decrypted_dir / "contact/contact.db"
    if not contact_db.exists():
        raise SystemExit(f"contact DB not found: {contact_db}. Run decrypt_all_dbs.py first.")
    con = sqlite3.connect(contact_db)
    con.row_factory = sqlite3.Row
    columns = {row["name"] for row in con.execute("PRAGMA table_info(contact)")}
    wanted = [col for col in ["username", "userName", "remark", "nick_name", "alias", "type"] if col in columns]
    rows = [dict(row) for row in con.execute(f"SELECT {','.join(wanted)} FROM contact")]
    con.close()
    return rows


def contact_display(contact: dict) -> str:
    for field in ["remark", "nick_name", "alias", "username", "userName"]:
        value = contact.get(field)
        if value:
            return str(value)
    return "unknown"


def find_contact(contacts: list[dict], query: str) -> dict:
    q = query.lower()
    exact = []
    fuzzy = []
    for contact in contacts:
        fields = [str(contact.get(field) or "") for field in ["username", "userName", "remark", "nick_name", "alias"]]
        lowered = [field.lower() for field in fields]
        if q in lowered:
            exact.append(contact)
        elif any(q in field for field in lowered):
            fuzzy.append(contact)
    matches = exact or fuzzy
    if not matches:
        raise SystemExit(f"No contact matched: {query}")
    if len(matches) > 1:
        print("Multiple contacts matched; using the first one:")
        for item in matches[:10]:
            print(f"  - {item.get('username') or item.get('userName')} | {contact_display(item)}")
    return matches[0]


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value[:80] or "chat"


def parse_since(value: str | None) -> int | None:
    if not value:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    raise SystemExit(f"Unsupported --since value: {value}")


def message_table_for(chat_id: str) -> str:
    return "Msg_" + hashlib.md5(chat_id.encode()).hexdigest()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def normalize_content(local_type: int, content: str) -> str:
    if local_type == 34:
        match = re.search(r'voicelength="(\d+)"', content)
        if match:
            seconds = int(match.group(1)) / 1000
            return f"[语音消息，约 {seconds:.1f} 秒]"
        return "[语音消息]"
    if local_type == 3:
        return "[图片]"
    if local_type == 43:
        return "[视频]"
    if local_type == 47:
        return "[表情]"
    if local_type == 48:
        return "[位置]"
    if local_type == 42:
        return "[名片]"
    if local_type not in (1, 49, 10000):
        return f"[{TYPE_LABELS.get(local_type, f'类型{local_type}')}] {content}".strip()
    return content.strip()


def collect_messages(decrypted_dir: Path, chat_id: str, display: str, since_ts: int | None) -> list[dict]:
    table = message_table_for(chat_id)
    rows: list[dict] = []
    for rel in MESSAGE_DBS:
        db_path = decrypted_dir / rel
        if not db_path.exists():
            continue
        con = connect(db_path)
        try:
            if not table_exists(con, table):
                continue
            sql = (
                f"SELECT local_id, server_id, local_type, real_sender_id, create_time, "
                f"message_content, compress_content FROM [{table}]"
            )
            params: tuple = ()
            if since_ts is not None:
                sql += " WHERE create_time > ?"
                params = (since_ts,)
            sql += " ORDER BY create_time, local_id"
            for local_id, server_id, local_type, sender_id, ts, content, compressed in con.execute(sql, params):
                decoded = decode_value(content) or decode_value(compressed)
                sender = "我" if sender_id == 2 else display
                if local_type == 10000:
                    sender = "系统"
                rows.append({
                    "db": db_path.name,
                    "local_id": local_id,
                    "server_id": server_id,
                    "type": local_type,
                    "label": TYPE_LABELS.get(local_type, f"类型{local_type}"),
                    "sender": sender,
                    "ts": int(ts),
                    "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                    "content": normalize_content(local_type, decoded),
                })
        finally:
            con.close()
    rows.sort(key=lambda item: (item["ts"], item["db"], item["local_id"]))
    deduped = []
    seen = set()
    for item in rows:
        key = (item["ts"], item["sender"], item["type"], item["content"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def render_markdown(chat_id: str, display: str, rows: list[dict], mode: str, since_ts: int | None) -> str:
    if rows:
        time_range = f"{rows[0]['time']} 至 {rows[-1]['time']}"
    else:
        time_range = "无新增消息"
    lines = [
        f"# {display} 聊天记录导出",
        "",
        "## 导出信息",
        "",
        f"- 会话 ID：{chat_id}",
        f"- 模式：{mode}",
        f"- 起始时间：{datetime.fromtimestamp(since_ts).strftime('%Y-%m-%d %H:%M:%S') if since_ts else '全部'}",
        f"- 消息数：{len(rows)}",
        f"- 时间范围：{time_range}",
        "",
        "## 时间线",
        "",
    ]
    for index, item in enumerate(rows, 1):
        content = item["content"].replace("\n", "\n    ")
        lines.append(f"{index:02d}. {item['time']} [{item['sender']}｜{item['label']}] {content}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one decrypted WeChat conversation.")
    parser.add_argument("--contact", help="contact remark/nickname/userName fuzzy query")
    parser.add_argument("--chat-id", help="exact WeChat userName/chatroom id")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--since", help="start time, e.g. 2025-01-01 or '2025-01-01 12:00:00'")
    parser.add_argument("--decrypted-dir", help="override decrypted DB directory")
    parser.add_argument("--exports-dir", help="override export directory")
    parser.add_argument("--output", help="explicit output markdown path")
    parser.add_argument("--write-empty", action="store_true", help="write a report even if no new messages")
    args = parser.parse_args()

    if not args.contact and not args.chat_id:
        raise SystemExit("Use --contact or --chat-id")

    decrypted_dir, exports_dir = resolve_dirs(args)
    contacts = load_contacts(decrypted_dir)
    contact = {"username": args.chat_id} if args.chat_id else find_contact(contacts, args.contact)
    chat_id = str(contact.get("username") or contact.get("userName"))
    display = contact_display(contact)

    state = load_json(EXPORT_STATE_FILE)
    state_key = f"chat:{chat_id}"
    since_ts = parse_since(args.since)
    if args.mode == "incremental" and since_ts is None:
        since_ts = state.get(state_key, {}).get("last_ts")

    rows = collect_messages(decrypted_dir, chat_id, display, since_ts)
    if not rows and not args.write_empty:
        print(f"No messages to export for {display}.")
        return

    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = exports_dir / "chats" / safe_name(display) / f"{stamp}-{args.mode}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(chat_id, display, rows, args.mode, since_ts), encoding="utf-8")

    if rows:
        state[state_key] = {"last_ts": max(item["ts"] for item in rows), "display": display}
        save_json(EXPORT_STATE_FILE, state)
    print(out_path)
    print(f"Exported {len(rows)} messages for {display}.")


if __name__ == "__main__":
    main()
