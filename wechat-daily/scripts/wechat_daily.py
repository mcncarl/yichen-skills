#!/usr/bin/env python3
"""
微信日报生成器 - 从加密数据库提取聊天记录生成日报
支持配置文件驱动，适配不同用户
"""
import sqlite3, struct, os, json, hashlib, argparse
from datetime import datetime, timedelta
from Crypto.Cipher import AES
import zstandard as zstd

# === 常量 ===
PAGE_SIZE = 4096
RESERVE = 80
IV_SIZE = 16
KEYS_FILE = os.path.expanduser("~/.config/wechat-keys.json")
CONFIG_FILE = os.path.expanduser("~/.config/wechat-daily.json")

MSG_TYPE_LABELS = {
    1: None,           # 文本
    3: "[图片]",
    34: "[语音]",
    42: "[名片]",
    43: "[视频]",
    47: "[表情]",
    48: "[位置]",
    10000: None,       # 系统消息
}

ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
_zstd_decompressor = zstd.ZstdDecompressor()


# === 配置加载 ===

def load_config(config_path=None):
    """加载用户配置，兼容旧版硬编码路径"""
    path = config_path or CONFIG_FILE
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    # Fallback: 尝试从现有脚本路径推断
    return {
        "wxid": None,
        "db_base_path": None,
        "monitor_groups": [],
        "monitor_contacts": [],
        "report_dir": os.path.expanduser("~/Documents/wechat-daily"),
        "time_mode": "8am_to_8am",
    }


def get_db_base(config):
    """获取数据库基础路径"""
    if config.get("db_base_path"):
        return os.path.expanduser(config["db_base_path"])
    if config.get("wxid"):
        return os.path.expanduser(
            f"~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
            f"xwechat_files/{config['wxid']}/db_storage"
        )
    print("[ERROR] 未配置 wxid 或 db_base_path，请先运行 extract_keys.py 或配置 ~/.config/wechat-daily.json")
    return None


def get_report_dir(config):
    """获取报告输出目录"""
    return os.path.expanduser(config.get("report_dir", "~/Documents/wechat-daily"))


# === 基础工具 ===

def load_keys():
    with open(KEYS_FILE) as f:
        return json.load(f)


def decrypt_db(db_path, key_hex, out_path):
    key = bytes.fromhex(key_hex)
    with open(db_path, "rb") as f:
        data = f.read()
    total_pages = len(data) // PAGE_SIZE
    result = bytearray()
    for pn in range(total_pages):
        page = data[pn * PAGE_SIZE:(pn + 1) * PAGE_SIZE]
        enc_start = 16 if pn == 0 else 0
        enc_size = PAGE_SIZE - RESERVE - enc_start
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_SIZE]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(page[enc_start:enc_start + enc_size])
        dp = bytearray(PAGE_SIZE)
        if pn == 0:
            dp[:16] = page[:16]
            dp[16:16 + len(dec)] = dec
        else:
            dp[:len(dec)] = dec
        result.extend(dp)
    result[:16] = b"SQLite format 3\x00"
    result[16:18] = struct.pack(">H", PAGE_SIZE)
    with open(out_path, "wb") as f:
        f.write(result)


def get_contact_map(db_path):
    db = sqlite3.connect(db_path)
    contacts = {}
    for row in db.execute("SELECT userName, remark, nick_name FROM contact"):
        contacts[row[0]] = row[1] or row[2] or row[0]
    db.close()
    return contacts


def get_hash_map(db_path):
    db = sqlite3.connect(db_path)
    mapping = {}
    for row in db.execute("SELECT user_name FROM Name2Id"):
        mapping[hashlib.md5(row[0].encode()).hexdigest()] = row[0]
    db.close()
    return mapping


def decode_content(content):
    if isinstance(content, bytes):
        if content[:4] == ZSTD_MAGIC:
            try:
                content = _zstd_decompressor.decompress(content, max_output_size=100000)
            except:
                return "[压缩消息]"
        try:
            content = content.decode("utf-8", errors="replace")
        except:
            return "[二进制内容]"
    if not content or len(content.strip()) == 0:
        return None
    return content


def resolve_sender(content, contacts):
    if ':\n' in content:
        sender_id, text = content.split(':\n', 1)
        name = contacts.get(sender_id, sender_id)
        return f"{name}: {text}"
    return content


# === 消息收集 ===

def collect_messages(db, contacts, hash_map, since_ts=None, start_ts=None, end_ts=None):
    tables = [t[0] for t in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
    ).fetchall()]
    chat_stats = {}
    max_ts = since_ts or 0

    for t in tables:
        try:
            if since_ts is not None:
                rows = db.execute(
                    f"SELECT create_time, local_type, message_content, source FROM [{t}] WHERE create_time > ? ORDER BY create_time",
                    (since_ts,)
                ).fetchall()
            else:
                rows = db.execute(
                    f"SELECT create_time, local_type, message_content, source FROM [{t}] WHERE create_time BETWEEN ? AND ? ORDER BY create_time",
                    (start_ts, end_ts)
                ).fetchall()
        except:
            continue

        if not rows:
            continue

        hash_id = t.replace("Msg_", "")
        uname = hash_map.get(hash_id, hash_id)
        display = contacts.get(uname, uname)
        is_group = "@chatroom" in uname

        messages = []
        for ct, local_type, content, source in rows:
            if ct > max_ts:
                max_ts = ct
            label = MSG_TYPE_LABELS.get(local_type, "[其他消息]")
            if label is None:
                content = decode_content(content)
                if content is None:
                    continue
                if is_group:
                    content = resolve_sender(content, contacts)
                messages.append({
                    "time": datetime.fromtimestamp(ct).strftime("%H:%M"),
                    "content": content[:200],
                })
            else:
                messages.append({
                    "time": datetime.fromtimestamp(ct).strftime("%H:%M"),
                    "content": label,
                })

        if messages:
            chat_stats[uname] = {
                "count": len(rows),
                "text_count": len(messages),
                "display": display,
                "is_group": is_group,
                "messages": messages
            }

    return chat_stats, max_ts


# === 列表模式 ===

def list_all_chats(config):
    """列出所有群聊和联系人，供用户选择监控对象"""
    db_base = get_db_base(config)
    if not db_base:
        return

    keys = load_keys()
    tmp_dir = os.path.expanduser("~/tmp/wechat_daily")
    os.makedirs(tmp_dir, exist_ok=True)

    paths = {
        "message_0": os.path.join(db_base, "message", "message_0.db"),
        "contact": os.path.join(db_base, "contact", "contact.db"),
    }

    for name, path in paths.items():
        if name in keys and os.path.exists(path):
            decrypt_db(path, keys[name], os.path.join(tmp_dir, f"{name}.db"))

    contacts = get_contact_map(os.path.join(tmp_dir, "contact.db"))
    hash_map = get_hash_map(os.path.join(tmp_dir, "message_0.db"))
    db = sqlite3.connect(os.path.join(tmp_dir, "message_0.db"))

    # Count messages per chat (last 7 days for relevance)
    week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
    tables = [t[0] for t in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
    ).fetchall()]

    groups = []
    contacts_list = []

    for t in tables:
        hash_id = t.replace("Msg_", "")
        uname = hash_map.get(hash_id, hash_id)
        display = contacts.get(uname, uname)
        is_group = "@chatroom" in uname

        try:
            count = db.execute(
                f"SELECT COUNT(*) FROM [{t}] WHERE create_time > ?", (week_ago,)
            ).fetchone()[0]
        except:
            count = 0

        entry = {"name": display, "id": uname, "msg_count_7d": count}
        if is_group:
            groups.append(entry)
        else:
            contacts_list.append(entry)

    db.close()

    # Sort by message count
    groups.sort(key=lambda x: x["msg_count_7d"], reverse=True)
    contacts_list.sort(key=lambda x: x["msg_count_7d"], reverse=True)

    print("=" * 50)
    print("群聊列表（最近7天消息数）")
    print("=" * 50)
    for i, g in enumerate(groups, 1):
        print(f"  {i}. {g['name']} — {g['msg_count_7d']}条")

    print(f"\n共 {len(groups)} 个群聊\n")

    print("=" * 50)
    print("联系人列表（最近7天消息数）")
    print("=" * 50)
    for i, c in enumerate(contacts_list[:50], 1):
        print(f"  {i}. {c['name']} — {c['msg_count_7d']}条")
    if len(contacts_list) > 50:
        print(f"  ... 还有 {len(contacts_list) - 50} 个联系人")

    print(f"\n共 {len(contacts_list)} 个联系人")


# === 报告生成 ===

def generate_report(chat_stats, config, target_date=None):
    """生成 Markdown 原始报告"""
    if target_date is None:
        target_date = datetime.now()

    monitor_groups = set(config.get("monitor_groups", []))
    monitor_contacts = set(config.get("monitor_contacts", []))

    # Filter by monitor list if configured
    if monitor_groups or monitor_contacts:
        filtered = {}
        for uname, data in chat_stats.items():
            display = data["display"]
            is_group = data.get("is_group", "@chatroom" in uname)
            if is_group and (not monitor_groups or display in monitor_groups):
                filtered[uname] = data
            elif not is_group and (not monitor_contacts or display in monitor_contacts):
                filtered[uname] = data
        chat_stats = filtered

    date_display = target_date.strftime("%Y-%m-%d %A")
    report = f"# 微信日报 {date_display}\n\n"
    report += f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    total_msgs = sum(v["text_count"] for v in chat_stats.values())
    total_chats = len(chat_stats)
    report += f"## 概览\n\n"
    report += f"| 指标 | 数值 |\n|---|---|\n"
    report += f"| 活跃会话数 | {total_chats} |\n"
    report += f"| 文字消息总数 | {total_msgs} |\n\n"

    sorted_chats = sorted(chat_stats.items(), key=lambda x: x[1]["text_count"], reverse=True)

    report += f"## 活跃排行\n\n"
    for i, (uname, data) in enumerate(sorted_chats[:15]):
        is_group = data.get("is_group", "@chatroom" in uname)
        icon = "👥" if is_group else "👤"
        report += f"{i+1}. {icon} **{data['display']}** — {data['text_count']}条消息\n"
    report += "\n"

    report += f"## 聊天详情\n\n"
    for uname, data in sorted_chats:
        report += f"### {data['display']} ({data['text_count']}条)\n\n"
        for msg in data["messages"]:
            report += f"- `{msg['time']}` {msg['content'][:100]}\n"
        report += "\n"

    return report


# === 解密入口 ===

def decrypt_databases(db_base, tmp_dir):
    """解密所有需要的数据库"""
    keys = load_keys()
    os.makedirs(tmp_dir, exist_ok=True)

    paths = {
        "message_0": os.path.join(db_base, "message", "message_0.db"),
        "contact": os.path.join(db_base, "contact", "contact.db"),
        "session": os.path.join(db_base, "session", "session.db"),
    }

    for name, key_hex in keys.items():
        if name in paths and os.path.exists(paths[name]):
            decrypt_db(paths[name], key_hex, os.path.join(tmp_dir, f"{name}.db"))


# === 主入口 ===

def run_daily(config_path=None):
    """默认模式：昨天 08:00 到今天 08:00"""
    config = load_config(config_path)
    db_base = get_db_base(config)
    if not db_base:
        return None

    tmp_dir = os.path.expanduser("~/tmp/wechat_daily")
    decrypt_databases(db_base, tmp_dir)

    contacts = get_contact_map(os.path.join(tmp_dir, "contact.db"))
    hash_map = get_hash_map(os.path.join(tmp_dir, "message_0.db"))
    db = sqlite3.connect(os.path.join(tmp_dir, "message_0.db"))

    today = datetime.now()
    start = today.replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=1)
    end = today.replace(hour=8, minute=0, second=0, microsecond=0)
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())

    print(f"日报模式：{start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')}")

    chat_stats, _ = collect_messages(db, contacts, hash_map, start_ts=start_ts, end_ts=end_ts)
    db.close()

    if not chat_stats:
        print("没有新消息")
        return None

    report = generate_report(chat_stats, config, target_date=start)

    report_dir = get_report_dir(config)
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"{start.strftime('%Y-%m-%d')}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    total_msgs = sum(v["text_count"] for v in chat_stats.values())
    total_chats = len(chat_stats)
    print(f"日报已生成: {report_path}")
    print(f"  {total_chats} 个活跃会话, {total_msgs} 条文字消息")
    return report_path


def run_date(date_str, config_path=None):
    """日期模式：生成指定日期的完整报告"""
    config = load_config(config_path)
    db_base = get_db_base(config)
    if not db_base:
        return None

    tmp_dir = os.path.expanduser("~/tmp/wechat_daily")
    decrypt_databases(db_base, tmp_dir)

    contacts = get_contact_map(os.path.join(tmp_dir, "contact.db"))
    hash_map = get_hash_map(os.path.join(tmp_dir, "message_0.db"))
    db = sqlite3.connect(os.path.join(tmp_dir, "message_0.db"))

    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp())
    end_ts = int(target_date.replace(hour=23, minute=59, second=59).timestamp())

    chat_stats, _ = collect_messages(db, contacts, hash_map, start_ts=start_ts, end_ts=end_ts)
    db.close()

    report = generate_report(chat_stats, config, target_date=target_date)

    report_dir = get_report_dir(config)
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"{target_date.strftime('%Y-%m-%d')}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    total_msgs = sum(v["text_count"] for v in chat_stats.values())
    total_chats = len(chat_stats)
    print(f"日报已生成: {report_path}")
    print(f"  {total_chats} 个活跃会话, {total_msgs} 条文字消息")
    return report_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="微信日报生成器")
    parser.add_argument("date", nargs="?", help="指定日期 (YYYY-MM-DD)，默认昨天8点到今天8点")
    parser.add_argument("--config", help="配置文件路径", default=None)
    parser.add_argument("--list", action="store_true", help="列出所有群聊和联系人")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.list:
        list_all_chats(config)
    elif args.date:
        run_date(args.date, args.config)
    else:
        run_daily(args.config)
