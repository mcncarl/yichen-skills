"""Independent synthetic fixture builder; it does not import production code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import zstandard


ALICE = "wxid_alice_fixture"
BOB = "wxid_bob_fixture"
GROUP = "fixture_group@chatroom"
ACCOUNT = "wxid_owner_fixture"
DEFAULT_SNAPSHOT_ID = "11111111-2222-4333-8444-555555555555"
CHAT_ID_DOMAIN = b"yichen-wechat-windows-reader/chat-id/v1\0"


def database(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for statement in statements:
            con.execute(statement)
        con.commit()
    finally:
        con.close()


def fixture_chat_id(snapshot_id: str, username: str) -> str:
    material = CHAT_ID_DOMAIN + uuid.UUID(snapshot_id).bytes + b"\0" + username.encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def build(
    root: Path,
    *,
    snapshot_id: str = DEFAULT_SNAPSHOT_ID,
    include_manifest: bool = True,
    include_sns: bool = True,
    contact_schema: str = "valid",
    message_mode: str = "valid",
    account_username: str | None = ACCOUNT,
    first_message: str = "普通消息",
) -> dict:
    if contact_schema == "valid":
        database(root / "contact/contact.db", [
            "CREATE TABLE contact(id INTEGER, username TEXT, nick_name TEXT, remark TEXT, alias TEXT)",
            f"INSERT INTO contact VALUES(1,'{ALICE}','同名','客户甲','alice')",
            f"INSERT INTO contact VALUES(2,'{BOB}','同名','客户乙','bob')",
            f"INSERT INTO contact VALUES(3,'{GROUP}','测试群','','')",
            f"INSERT INTO contact VALUES(4,'{ACCOUNT}','我','','')",
        ])
    elif contact_schema == "invalid":
        database(root / "contact/contact.db", [
            "CREATE TABLE contact(id INTEGER, nick_name TEXT)",
            "INSERT INTO contact VALUES(1,'缺少 username')",
        ])
    else:
        raise ValueError(f"unsupported contact_schema: {contact_schema}")
    database(root / "session/session.db", ["CREATE TABLE SessionTable(username TEXT, unread_count INTEGER)"])
    database(root / "favorite/favorite.db", ["CREATE TABLE FavoriteItem(id INTEGER)"])
    if include_sns:
        database(root / "sns/sns.db", ["CREATE TABLE SnsTimeLine(id INTEGER)"])
    database(root / "message/message_resource.db", ["CREATE TABLE Resource(id INTEGER)"])

    table = "Msg_" + hashlib.md5(GROUP.encode()).hexdigest()
    if message_mode == "valid":
        database(root / "message/message_0.db", [
            "CREATE TABLE Name2Id(user_name TEXT)",
            f"INSERT INTO Name2Id(rowid,user_name) VALUES(1,'{ACCOUNT}')",
            f"INSERT INTO Name2Id(rowid,user_name) VALUES(2,'{ALICE}')",
            f"CREATE TABLE [{table}](local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB,compress_content BLOB,WCDB_CT_message_content INTEGER)",
        ])
        con = sqlite3.connect(root / "message/message_0.db")
        try:
            con.execute(f"INSERT INTO [{table}] VALUES(1,101,1,1772323200,2,?,NULL,0)", (first_message,))
            con.execute(f"INSERT INTO [{table}] VALUES(2,102,1,1772323260,1,'主人回复',NULL,0)")
            con.commit()
        finally:
            con.close()
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
    elif message_mode == "invalid_schema":
        database(root / "message/message_0.db", [
            f"CREATE TABLE [{table}](created TEXT, payload BLOB)",
        ])
    elif message_mode == "without_rowid":
        database(root / "message/message_0.db", [
            f"CREATE TABLE [{table}](create_time INTEGER PRIMARY KEY, message_content TEXT) WITHOUT ROWID",
            f"INSERT INTO [{table}] VALUES(1772323200,'synthetic row without rowid')",
        ])
    elif message_mode != "resource_only":
        raise ValueError(f"unsupported message_mode: {message_mode}")

    if include_manifest:
        manifest: dict[str, str] = {"snapshot_id": snapshot_id}
        if account_username is not None:
            manifest["account_username"] = account_username
        (root / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {"group_id": fixture_chat_id(snapshot_id, GROUP), "snapshot_id": snapshot_id, "table": table}
