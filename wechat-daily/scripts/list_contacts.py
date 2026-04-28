#!/usr/bin/env python3
"""
列出所有群聊和联系人，供用户选择监控对象
用法: python3 list_contacts.py [--config CONFIG_PATH]
"""
import sqlite3, struct, os, json, hashlib, argparse
from datetime import datetime, timedelta
from Crypto.Cipher import AES
import zstandard as zstd

PAGE_SIZE = 4096
RESERVE = 80
IV_SIZE = 16
KEYS_FILE = os.path.expanduser("~/.config/wechat-keys.json")
CONFIG_FILE = os.path.expanduser("~/.config/wechat-daily.json")

ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
_zstd_decompressor = zstd.ZstdDecompressor()


def load_config(config_path=None):
    path = config_path or CONFIG_FILE
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def get_db_base(config):
    if config.get("db_base_path"):
        return os.path.expanduser(config["db_base_path"])
    if config.get("wxid"):
        return os.path.expanduser(
            f"~/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
            f"xwechat_files/{config['wxid']}/db_storage"
        )
    return None


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


def main(config_path=None):
    config = load_config(config_path)
    db_base = get_db_base(config)
    if not db_base:
        print("[ERROR] 未配置 wxid 或 db_base_path")
        print("请先运行 extract_keys.py 或配置 ~/.config/wechat-daily.json")
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

    groups.sort(key=lambda x: x["msg_count_7d"], reverse=True)
    contacts_list.sort(key=lambda x: x["msg_count_7d"], reverse=True)

    print("=" * 60)
    print("群聊列表（最近7天消息数）")
    print("=" * 60)
    for i, g in enumerate(groups, 1):
        print(f"  {i}. {g['name']} — {g['msg_count_7d']}条")

    print(f"\n共 {len(groups)} 个群聊\n")

    print("=" * 60)
    print("联系人列表（最近7天消息数）")
    print("=" * 60)
    for i, c in enumerate(contacts_list[:50], 1):
        print(f"  {i}. {c['name']} — {c['msg_count_7d']}条")
    if len(contacts_list) > 50:
        print(f"  ... 还有 {len(contacts_list) - 50} 个联系人")

    print(f"\n共 {len(contacts_list)} 个联系人")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="列出微信所有群聊和联系人")
    parser.add_argument("--config", help="配置文件路径", default=None)
    args = parser.parse_args()
    main(args.config)
