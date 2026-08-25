"""Independent synthetic fixture builder; it does not import production code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import zstandard


ALICE = "wxid_alice_fixture"
BOB = "wxid_bob_fixture"
GROUP = "fixture_group@chatroom"
ACCOUNT = "wxid_owner_fixture"


def database(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for statement in statements:
            con.execute(statement)
        con.commit()
    finally:
        con.close()


def build(root: Path) -> dict:
    database(root / "contact/contact.db", [
        "CREATE TABLE contact(id INTEGER, username TEXT, nick_name TEXT, remark TEXT, alias TEXT)",
        f"INSERT INTO contact VALUES(1,'{ALICE}','同名','客户甲','alice')",
        f"INSERT INTO contact VALUES(2,'{BOB}','同名','客户乙','bob')",
        f"INSERT INTO contact VALUES(3,'{GROUP}','测试群','','')",
        f"INSERT INTO contact VALUES(4,'{ACCOUNT}','我','','')",
    ])
    database(root / "session/session.db", ["CREATE TABLE SessionTable(username TEXT, unread_count INTEGER)"])
    database(root / "favorite/favorite.db", ["CREATE TABLE FavoriteItem(id INTEGER)"])
    database(root / "sns/sns.db", ["CREATE TABLE SnsTimeLine(id INTEGER)"])
    database(root / "message/message_resource.db", ["CREATE TABLE Resource(id INTEGER)"])

    table = "Msg_" + hashlib.md5(GROUP.encode()).hexdigest()
    common = [
        "CREATE TABLE Name2Id(user_name TEXT)",
        f"INSERT INTO Name2Id(rowid,user_name) VALUES(1,'{ACCOUNT}')",
        f"INSERT INTO Name2Id(rowid,user_name) VALUES(2,'{ALICE}')",
        f"CREATE TABLE [{table}](local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB,compress_content BLOB,WCDB_CT_message_content INTEGER)",
    ]
    database(root / "message/message_0.db", common + [
        f"INSERT INTO [{table}] VALUES(1,101,1,1772323200,2,'普通消息',NULL,0)",
        f"INSERT INTO [{table}] VALUES(2,102,1,1772323260,1,'主人回复',NULL,0)",
    ])
    database(root / "message/biz_message_0.db", [
        f"CREATE TABLE [{table}](local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB)",
    ])
    con = sqlite3.connect(root / "message/biz_message_0.db")
    try:
        packed = zstandard.ZstdCompressor().compress("来自 biz_message 的压缩关键词：星河".encode())
        con.execute(f"INSERT INTO [{table}] VALUES(3,103,1,1772323320,2,?)", (packed,))
        con.commit()
    finally:
        con.close()
    (root / "snapshot-manifest.json").write_text(json.dumps({"account_username": ACCOUNT}), encoding="utf-8")
    return {"group_id": hashlib.sha256(GROUP.encode()).hexdigest()[:24]}
