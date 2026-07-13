#!/usr/bin/env python3
"""
查询微信 Mac 4.x 本地朋友圈数据库。

用法示例：
  python3 search_sns.py --name "好友备注" --start 2026-04-01 --end 2026-05-03
  python3 search_sns.py --name "好友备注" --keyword "招聘" --limit 20
  python3 search_sns.py --list "张三"
"""
import argparse
import json
import os
import re
import sqlite3
import struct
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from Crypto.Cipher import AES


PAGE_SIZE = 4096
RESERVE = 80
IV_SIZE = 16
KEYS_FILE = os.path.expanduser("~/.config/wechat-keys.json")
CONFIG_FILE = os.path.expanduser("~/.config/wechat-local-vault.json")
TMP_DIR = os.path.expanduser("~/Library/Application Support/wechat-local-vault/tmp")


def load_json(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path=None):
    path = config_path or CONFIG_FILE
    if os.path.exists(path):
        return load_json(path)
    return {}


def get_db_base(config):
    if config.get("db_base_path"):
        return os.path.expanduser(config["db_base_path"])
    if config.get("wxid"):
        return os.path.expanduser(
            f"~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
            f"xwechat_files/{config['wxid']}/db_storage"
        )
    raise SystemExit("[ERROR] 未配置 wxid 或 db_base_path，请先运行 extract_keys.py")


def decrypt_db(db_path, key_hex, out_path):
    key = bytes.fromhex(key_hex)
    with open(db_path, "rb") as f:
        data = f.read()

    result = bytearray()
    for pn in range(len(data) // PAGE_SIZE):
        page = data[pn * PAGE_SIZE:(pn + 1) * PAGE_SIZE]
        enc_start = 16 if pn == 0 else 0
        enc_size = PAGE_SIZE - RESERVE - enc_start
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_SIZE]
        dec = AES.new(key, AES.MODE_CBC, iv).decrypt(page[enc_start:enc_start + enc_size])
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


def ensure_decrypted(config):
    keys = load_json(KEYS_FILE)
    db_base = get_db_base(config)
    tmp_dir = TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)

    paths = {
        "contact": os.path.join(db_base, "contact", "contact.db"),
        "sns": os.path.join(db_base, "sns", "sns.db"),
    }
    for name, path in paths.items():
        if not os.path.exists(path):
            raise SystemExit(f"[ERROR] 数据库不存在: {path}")
        key_hex = keys.get(name)
        if not key_hex:
            raise SystemExit(f"[ERROR] 缺少 {name} 密钥，请先运行 extract_keys.py --targets {name}")
        decrypt_db(path, key_hex, os.path.join(tmp_dir, f"{name}.db"))

    return os.path.join(tmp_dir, "contact.db"), os.path.join(tmp_dir, "sns.db")


def contact_rows(contact_db):
    db = sqlite3.connect(contact_db)
    rows = db.execute(
        """
        SELECT username, alias, remark, nick_name, quan_pin, remark_quan_pin
        FROM contact
        WHERE username IS NOT NULL AND username != ''
        """
    ).fetchall()
    db.close()
    return rows


def display_name(row):
    username, alias, remark, nick_name, quan_pin, remark_quan_pin = row
    return remark or nick_name or alias or username


def row_matches(row, query):
    query = query.lower()
    return any(query in str(value or "").lower() for value in row)


def find_contacts(contact_db, query):
    rows = [row for row in contact_rows(contact_db) if row_matches(row, query)]
    rows.sort(key=lambda row: (display_name(row).lower(), row[0]))
    return rows


def parse_date(value, end_of_day=False):
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
    raise SystemExit(f"[ERROR] 无法解析日期: {value}")


def text_of(root, path):
    node = root.find(path)
    return (node.text or "").strip() if node is not None else ""


def parse_content(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        root = ET.fromstring(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text))

    timeline = root.find("TimelineObject") if root.tag != "TimelineObject" else root
    if timeline is None:
        timeline = root

    create_time = text_of(timeline, "createTime")
    content = text_of(timeline, "contentDesc")
    post_id = text_of(timeline, "id")
    username = text_of(timeline, "username")
    nickname = text_of(timeline, "nickname")
    post_type = text_of(timeline, "ContentObject/contentStyle") or text_of(timeline, "ContentObject/contentSubStyle")

    media = []
    for item in timeline.findall(".//media"):
        media_type = text_of(item, "type")
        url = text_of(item, "url")
        thumb = text_of(item, "thumb")
        media.append({"type": media_type, "url": url, "thumb": thumb})

    links = []
    for path in ("ContentObject/contentUrl", ".//url"):
        for node in timeline.findall(path):
            if node.text and node.text.strip():
                links.append(node.text.strip())

    return {
        "id": post_id,
        "username": username,
        "nickname": nickname,
        "create_time": int(create_time) if create_time.isdigit() else None,
        "content": content,
        "type": post_type,
        "media": media,
        "links": sorted(set(links)),
    }


def query_posts(sns_db, usernames, start_ts=None, end_ts=None, keyword=None, limit=50):
    db = sqlite3.connect(sns_db)
    placeholders = ",".join("?" for _ in usernames)
    sql = f"SELECT tid, user_name, content FROM SnsTimeLine WHERE user_name IN ({placeholders})"
    rows = db.execute(sql, list(usernames)).fetchall()
    db.close()

    posts = []
    for tid, user_name, content in rows:
        if not content:
            continue
        try:
            post = parse_content(content)
        except Exception as exc:
            post = {
                "id": str(tid),
                "username": user_name,
                "nickname": "",
                "create_time": None,
                "content": f"[无法解析 XML: {exc}]",
                "type": "",
                "media": [],
                "links": [],
            }
        post["db_user_name"] = user_name
        post["tid"] = tid
        ct = post.get("create_time")
        if start_ts and (ct is None or ct < start_ts):
            continue
        if end_ts and (ct is None or ct > end_ts):
            continue
        if keyword and keyword.lower() not in post.get("content", "").lower() and keyword.lower() not in json.dumps(post.get("links", []), ensure_ascii=False).lower():
            continue
        posts.append(post)

    posts.sort(key=lambda post: post.get("create_time") or 0, reverse=True)
    return posts[:limit]


def print_contacts(rows):
    if not rows:
        print("没有找到匹配联系人")
        return
    for index, row in enumerate(rows, 1):
        username, alias, remark, nick_name, _, _ = row
        print(f"{index}. {display_name(row)}")
        print(f"   username: {username}")
        if remark:
            print(f"   remark: {remark}")
        if nick_name and nick_name != remark:
            print(f"   nick: {nick_name}")
        if alias:
            print(f"   alias: {alias}")


def print_posts(posts, name_map):
    if not posts:
        print("没有找到匹配朋友圈")
        return
    for index, post in enumerate(posts, 1):
        ts = post.get("create_time")
        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "未知时间"
        user = name_map.get(post["db_user_name"], post["db_user_name"])
        media_count = len(post.get("media") or [])
        link_count = len(post.get("links") or [])
        suffix = []
        if media_count:
            suffix.append(f"{media_count}个媒体")
        if link_count:
            suffix.append(f"{link_count}个链接")
        print(f"\n{index}. {when} | {user} | tid={post['tid']}")
        if suffix:
            print(f"   [{'，'.join(suffix)}]")
        content = post.get("content") or "[无文字内容]"
        print("   " + content.replace("\n", "\n   "))
        for url in post.get("links", [])[:5]:
            print(f"   link: {url}")


def main():
    parser = argparse.ArgumentParser(description="查询微信本地朋友圈")
    parser.add_argument("--name", help="联系人备注、昵称、微信号、wxid 的一部分")
    parser.add_argument("--username", action="append", help="直接指定朋友圈 user_name / wxid，可重复传入")
    parser.add_argument("--list", dest="list_query", help="只列出匹配联系人，不查询朋友圈")
    parser.add_argument("--start", help="开始时间，如 2026-04-01 或 '2026-04-01 08:00'")
    parser.add_argument("--end", help="结束时间，如 2026-05-03 或 '2026-05-03 23:59'")
    parser.add_argument("--keyword", help="按正文或链接关键词过滤")
    parser.add_argument("--limit", type=int, default=50, help="最多输出条数，默认 50")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    contact_db, sns_db = ensure_decrypted(config)

    if args.list_query:
        print_contacts(find_contacts(contact_db, args.list_query))
        return

    usernames = args.username or []
    if args.name:
        matches = find_contacts(contact_db, args.name)
        usernames.extend(row[0] for row in matches)
        if not matches and not usernames:
            raise SystemExit("没有找到匹配联系人。可以先用 --list 确认备注/昵称，或用 --username 直接传 wxid。")

    if not usernames:
        raise SystemExit("请传 --name、--username，或用 --list 搜索联系人。")

    usernames = sorted(set(usernames))
    name_map = {row[0]: display_name(row) for row in contact_rows(contact_db)}
    posts = query_posts(
        sns_db,
        usernames,
        start_ts=parse_date(args.start),
        end_ts=parse_date(args.end, end_of_day=True),
        keyword=args.keyword,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(posts, ensure_ascii=False, indent=2))
    else:
        print_posts(posts, name_map)


if __name__ == "__main__":
    main()
