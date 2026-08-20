from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def create_db(path: Path, statements: list[str], rows: list[tuple[str, tuple]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        for statement in statements:
            con.execute(statement)
        for sql, params in rows:
            con.execute(sql, params)


@pytest.fixture()
def synthetic_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    create_db(
        root / "contact" / "contact.db",
        [
            "CREATE TABLE contact(id INTEGER PRIMARY KEY,username TEXT,local_type INTEGER,alias TEXT,encrypt_username TEXT,flag INTEGER,delete_flag INTEGER,verify_flag INTEGER,remark TEXT,remark_quan_pin TEXT,remark_pin_yin_initial TEXT,nick_name TEXT,pin_yin_initial TEXT,quan_pin TEXT,big_head_url TEXT,small_head_url TEXT,head_img_md5 TEXT,chat_room_notify INTEGER,is_in_chat_room INTEGER,description TEXT,extra_buffer BLOB,chat_room_type INTEGER)",
            "CREATE TABLE chat_room(id INTEGER PRIMARY KEY,username TEXT,owner TEXT,ext_buffer BLOB)",
            "CREATE TABLE chatroom_member(room_id INTEGER,member_id INTEGER)",
        ],
        [
            ("INSERT INTO contact(id,username,alias,remark,nick_name,local_type,delete_flag,is_in_chat_room,chat_room_type) VALUES(?,?,?,?,?,?,?,?,?)", (1,"alice","alice_alias","Alice Remark","Alice",1,0,0,0)),
            ("INSERT INTO contact(id,username,alias,remark,nick_name,local_type,delete_flag,is_in_chat_room,chat_room_type) VALUES(?,?,?,?,?,?,?,?,?)", (2,"group@chatroom","","Synthetic Group","Group",2,0,1,1)),
            ("INSERT INTO chat_room(id,username,owner) VALUES(?,?,?)", (7,"group@chatroom","alice")),
            ("INSERT INTO chatroom_member(room_id,member_id) VALUES(?,?)", (7,1)),
        ],
    )
    create_db(
        root / "session" / "session.db",
        ["CREATE TABLE SessionTable(username TEXT,type INTEGER,unread_count INTEGER,unread_first_msg_srv_id INTEGER,unread_first_pat_msg_local_id INTEGER,unread_first_pat_msg_sort_seq INTEGER,is_hidden INTEGER,summary BLOB,draft TEXT,status INTEGER,last_timestamp INTEGER,sort_timestamp INTEGER,last_clear_unread_timestamp INTEGER,last_msg_locald_id INTEGER,last_msg_type INTEGER,last_msg_sub_type INTEGER,last_msg_sender INTEGER,last_sender_display_name TEXT,last_msg_ext_type INTEGER)"],
        [("INSERT INTO SessionTable(username,unread_count,summary,last_timestamp,sort_timestamp,last_msg_type,last_msg_sub_type,last_sender_display_name) VALUES(?,?,?,?,?,?,?,?)", ("alice",2,"hello",1700000000,1700000000,1,0,"Alice"))],
    )
    table = "Msg_" + hashlib.md5(b"alice").hexdigest()
    create_db(
        root / "message" / "message_0.db",
        [f"CREATE TABLE {table}(local_id INTEGER,server_id INTEGER,local_type INTEGER,sort_seq INTEGER,real_sender_id INTEGER,create_time INTEGER,status INTEGER,upload_status INTEGER,download_status INTEGER,server_seq INTEGER,origin_source BLOB,source BLOB,message_content BLOB,compress_content BLOB,packed_info_data BLOB,WCDB_CT_message_content INTEGER,WCDB_CT_source INTEGER)"],
        [
            (f"INSERT INTO {table}(local_id,server_id,local_type,sort_seq,real_sender_id,create_time,status,message_content) VALUES(?,?,?,?,?,?,?,?)", (1,101,1,1,1,1700000000,0,"hello synthetic")),
            (f"INSERT INTO {table}(local_id,server_id,local_type,sort_seq,real_sender_id,create_time,status,message_content) VALUES(?,?,?,?,?,?,?,?)", (2,102,3,2,1,1700000010,0,"image synthetic")),
        ],
    )
    create_db(
        root / "favorite" / "favorite.db",
        ["CREATE TABLE fav_db_item(local_id INTEGER,server_id INTEGER,type INTEGER,update_seq INTEGER,flag INTEGER,update_time INTEGER,version INTEGER,content BLOB,source_id TEXT,sync_status INTEGER,upload_status INTEGER,upload_error_code INTEGER,trans_res_status INTEGER,trans_res_error_code INTEGER,fromusr TEXT,fromusr_id INTEGER,realchatname TEXT,realchatname_id INTEGER,ext_buf BLOB)"],
        [("INSERT INTO fav_db_item(local_id,server_id,type,update_time,content,fromusr,realchatname) VALUES(?,?,?,?,?,?,?)", (1,2,1,1700000000,"favorite synthetic","alice","alice"))],
    )
    create_db(
        root / "message" / "message_resource.db",
        [
            "CREATE TABLE ChatName2Id(user_name TEXT,update_time INTEGER)",
            "CREATE TABLE MessageResourceInfo(message_id INTEGER,chat_id INTEGER,sender_id INTEGER,message_local_type INTEGER,message_create_time INTEGER,message_local_id INTEGER,message_svr_id INTEGER,message_origin_source BLOB,packed_info BLOB)",
            "CREATE TABLE MessageResourceDetail(resource_id INTEGER,message_id INTEGER,type INTEGER,size INTEGER,create_time INTEGER,access_time INTEGER,status INTEGER,data_index TEXT,packed_info BLOB)",
        ],
        [
            ("INSERT INTO ChatName2Id(rowid,user_name) VALUES(?,?)", (3,"alice")),
            ("INSERT INTO MessageResourceInfo(message_id,chat_id,message_local_type,message_create_time,message_local_id,message_svr_id) VALUES(?,?,?,?,?,?)", (9,3,3,1700000010,2,102)),
            ("INSERT INTO MessageResourceDetail(resource_id,message_id,type,size,status,data_index) VALUES(?,?,?,?,?,?)", (11,9,1,128,0,"synthetic-index")),
        ],
    )
    create_db(
        root / "sns" / "sns.db",
        ["CREATE TABLE SnsTimeLine(tid TEXT,user_name TEXT,content BLOB,pack_info_buf BLOB)"],
        [("INSERT INTO SnsTimeLine(tid,user_name,content) VALUES(?,?,?)", ("t1","alice","<TimelineObject><contentDesc>moment synthetic</contentDesc><createTime>1700000000</createTime></TimelineObject>"))],
    )
    return root
