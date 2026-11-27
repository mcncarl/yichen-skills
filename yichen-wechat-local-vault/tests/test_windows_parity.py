"""Comprehensive synthetic tests for Windows snapshot Mac-granularity parity.

Every fixture is synthetic; no real WeChat database, config, account, or client is touched.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import ctypes as c
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import snapshot_reader as reader
import snapshot_workflows as wf
import vault_cli
import windows_crypto
from fixture_factory import ACCOUNT, ALICE, BOB, GROUP, database, fixture_chat_id

ARTIFACT_ROOT = Path(
    os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-windows-parity-tests-")
).resolve()

HOUR = 3600
DAY = 86400
CHARLIE = "wxid_charlie_fixture"
GROUP_MUTED = "fixture_muted_group@chatroom"


def _transfer_xml(
    state: str,
    tid: str,
    *,
    amount: str = "￥88.00",
    payer: str = ALICE,
    receiver: str = ACCOUNT,
    memo: str = "",
    invalid: int = 0,
) -> str:
    return (
        "<msg><appmsg><type>2000</type><wcpayinfo>"
        f"<paysubtype>{state}</paysubtype>"
        f"<transferid>{tid}</transferid>"
        f"<feedesc>{amount}</feedesc>"
        f"<payer_username>{payer}</payer_username>"
        f"<receiver_username>{receiver}</receiver_username>"
        f"<pay_memo>{memo}</pay_memo>"
        f"<invalidtime>{invalid}</invalidtime>"
        "</wcpayinfo></appmsg></msg>"
    )


def _aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    if sys.platform == "win32":
        from ctypes import wintypes as w
        aes = windows_crypto.CngAES(key, chaining_mode="ChainingModeECB")
        try:
            api = aes.api.BCryptEncrypt
            api.argtypes = aes.api.BCryptDecrypt.argtypes
            api.restype = w.LONG
            src = c.create_string_buffer(data, len(data))
            out = c.create_string_buffer(len(data))
            written = w.ULONG()
            windows_crypto.CngAES._check(api(aes.key, src, len(data), None, None, 0, out, len(data), c.byref(written), 0))
            if written.value != len(data):
                raise ValueError("Incomplete synthetic ECB encryption")
            return out.raw
        finally:
            aes.close()
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(data)


def _encrypted_v2_dat(clear: bytes, aes_key: bytes, xor_key: int) -> bytes:
    head, middle, tail = clear[:8], clear[8:-2], clear[-2:]
    payload = b"\x07\x08V2\x08\x07" + struct.pack("<I", 8) + struct.pack("<I", 2) + b"\x00"
    return payload + _aes_ecb_encrypt(aes_key, head + bytes([8]) * 8) + middle + bytes(v ^ xor_key for v in tail)


def build_rich_snapshot(
    root: Path,
    *,
    snapshot_id: str = "22222222-3333-4444-8555-666666666666",
    account_username: str | None = ACCOUNT,
    profile: str = "full-snapshot-v1",
    now_ts: int | None = None,
    include_extra_msg: bool = False,
) -> dict:
    now = int(now_ts or datetime(2026, 11, 27, 12, 0, 0).timestamp())
    captured_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    database(root / "contact/contact.db", [
        "CREATE TABLE contact(id INTEGER, username TEXT, nick_name TEXT, remark TEXT, alias TEXT, local_type INTEGER, chat_room_notify INTEGER)",
        f"INSERT INTO contact VALUES(1,'{ALICE}','爱丽丝','客户甲','alice',1,1)",
        f"INSERT INTO contact VALUES(2,'{BOB}','鲍勃','客户乙','bob',1,1)",
        f"INSERT INTO contact VALUES(3,'{CHARLIE}','查理','客户丙','charlie',1,1)",
        f"INSERT INTO contact VALUES(4,'{GROUP}','项目讨论群','','',0,1)",
        f"INSERT INTO contact VALUES(5,'{GROUP_MUTED}','免打扰大群','','',0,0)",
        f"INSERT INTO contact VALUES(6,'{ACCOUNT}','逸尘本人','','owner',1,1)",
        "CREATE TABLE chat_room(id INTEGER, owner TEXT)",
        f"INSERT INTO chat_room VALUES(4,'{ALICE}')",
        "CREATE TABLE chatroom_member(room_id INTEGER, member_id INTEGER)",
        "INSERT INTO chatroom_member VALUES(4,1),(4,2),(4,6)",
    ])

    compressed_summary = zstandard.ZstdCompressor().compress("压缩摘要：合同已发".encode())
    database(root / "session/session.db", [
        "CREATE TABLE SessionTable(username TEXT, unread_count INTEGER, summary BLOB, last_timestamp INTEGER, last_msg_type INTEGER, last_msg_sender TEXT, last_sender_display_name TEXT)",
    ])
    con = sqlite3.connect(root / "session/session.db")
    try:
        alice_last = now - 300 if include_extra_msg else now - 2 * HOUR
        con.executemany(
            "INSERT INTO SessionTable VALUES(?,?,?,?,?,?,?)",
            [
                (ALICE, 2, compressed_summary, alice_last, 1, ALICE, "客户甲"),
                (BOB, 0, "好的", now - 3 * HOUR, 1, BOB, "客户乙"),
                (CHARLIE, 1, "待收转账", now - 4 * HOUR, wf.TRANSFER_TYPE, CHARLIE, "客户丙"),
                (GROUP, 3, "@你 请看方案", now - HOUR, 1, ALICE, "客户甲"),
                (GROUP_MUTED, 5, "@所有人 通知", now - 2 * HOUR, 1, BOB, "客户乙"),
            ],
        )
        con.commit()
    finally:
        con.close()

    if profile == "full-snapshot-v1":
        database(root / "favorite/favorite.db", [
            "CREATE TABLE fav_db_item(local_id INTEGER, type INTEGER, update_time INTEGER, content TEXT, fromusr TEXT, realchatname TEXT)",
            f"INSERT INTO fav_db_item VALUES(1,5,{now - DAY},'<favitem><weburlitem><pagetitle>SQLite 规范</pagetitle><pagedesc>锁字节页说明</pagedesc></weburlitem></favitem>','{ALICE}','{GROUP}')",
            f"INSERT INTO fav_db_item VALUES(2,1,{now - 2*DAY},'<favitem><desc>纯文本收藏笔记</desc></favitem>','{BOB}','{BOB}')",
            f"INSERT INTO fav_db_item VALUES(3,1,{now - 3*DAY},'<!DOCTYPE foo [<!ENTITY xxe \"secret\">]><favitem><desc>&xxe;</desc></favitem>','{ALICE}','{ALICE}')",
        ])
        database(root / "sns/sns.db", [
            "CREATE TABLE SnsTimeLine(tid TEXT, user_name TEXT, content TEXT)",
            f"INSERT INTO SnsTimeLine VALUES('tid-1','{ALICE}','<TimelineObject><username>{ALICE}</username><nickname>爱丽丝</nickname><createTime>{now - DAY}</createTime><contentDesc>今天上线新版本</contentDesc><ContentObject><contentStyle>1</contentStyle><contentUrl>https://example.invalid/post</contentUrl></ContentObject></TimelineObject>')",
            f"INSERT INTO SnsTimeLine VALUES('tid-2','{BOB}','<!DOCTYPE bad><TimelineObject><contentDesc>evil</contentDesc></TimelineObject>')",
        ])
        database(root / "message/message_resource.db", ["CREATE TABLE Resource(id INTEGER)"])

    t_alice = reader.message_table(ALICE)
    t_bob = reader.message_table(BOB)
    t_charlie = reader.message_table(CHARLIE)
    t_group = reader.message_table(GROUP)
    t_muted = reader.message_table(GROUP_MUTED)

    img_hash_v2 = "a" * 32
    img_hash_xor = "b" * 32
    packed_v2 = b"\x08\x03\x12\x20" + img_hash_v2.encode() + b"\x18\x01"
    packed_xor = b"\x08\x03\x12\x20" + img_hash_xor.encode() + b"\x18\x01"

    database(root / "message/message_0.db", [
        "CREATE TABLE Name2Id(user_name TEXT)",
        f"INSERT INTO Name2Id(rowid,user_name) VALUES(1,'{ACCOUNT}'),(2,'{ALICE}'),(3,'{BOB}'),(4,'{CHARLIE}')",
        *[
            f"CREATE TABLE [{t}](local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB,compress_content BLOB,WCDB_CT_message_content INTEGER,source TEXT,WCDB_CT_source INTEGER,packed_info_data BLOB)"
            for t in (t_alice, t_bob, t_charlie, t_group, t_muted)
        ],
    ])
    con = sqlite3.connect(root / "message/message_0.db")
    try:
        alice_rows = [
            (1, 1, 1, now - 10 * HOUR, 1, "我先打个招呼", None, 0, "", 0, None),
            (2, 2, 1, now - 5 * HOUR, 2, "合同方案请确认一下", None, 0, "", 0, None),
            (3, 3, (6 << 32) | 49, now - 4 * HOUR, 2, "<msg><appmsg><type>6</type><title>报价单.pdf</title></appmsg></msg>", None, 0, "", 0, None),
            (4, 4, 3, now - 3 * HOUR, 2, '<msg><img md5="ffffffffffffffffffffffffffffffff"/></msg>', None, 0, "", 0, packed_v2),
            (5, 5, 3, now - 3 * HOUR + 10, 2, '<msg><img md5="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"/></msg>', None, 0, "", 0, packed_xor),
            (6, 6, wf.TRANSFER_TYPE, now - 6 * HOUR, 2, _transfer_xml("1", "t-ok-cny", amount="￥100.00", payer=ALICE, receiver=ACCOUNT, memo="定金"), None, 0, "", 0, None),
            (7, 7, wf.TRANSFER_TYPE, now - 5 * HOUR, 1, _transfer_xml("3", "t-ok-cny", amount="￥100.00", payer=ALICE, receiver=ACCOUNT), None, 0, "", 0, None),
            (8, 8, wf.TRANSFER_TYPE, now - 4 * HOUR, 1, _transfer_xml("1", "t-usd", amount="USD 25.50", payer=ACCOUNT, receiver=ALICE, memo="tool"), None, 0, "", 0, None),
            (9, 9, wf.TRANSFER_TYPE, now - 3 * HOUR, 2, _transfer_xml("3", "t-usd", amount="USD 25.50", payer=ACCOUNT, receiver=ALICE), None, 0, "", 0, None),
            (10, 10, wf.TRANSFER_TYPE, now - 3 * HOUR, 2, _transfer_xml("1", "t-cross", amount="￥50.00", payer=ALICE, receiver=ACCOUNT), None, 0, "", 0, None),
            (11, 11, wf.RED_PACKET_TYPE, now - 2 * HOUR - 60, 2, "<msg><appmsg><type>2001</type><title>恭喜发财</title></appmsg></msg>", None, 0, "", 0, None),
            (12, 12, wf.CALL_TYPE, now - 2 * HOUR - 30, 2, '<voipmsg><VoIPBubbleMsg><msg>对方已取消</msg></VoIPBubbleMsg></voipmsg>', None, 0, "", 0, None),
            (13, 13, 1, now - 2 * HOUR, 2, "什么时候可以签字？", None, 0, "", 0, None),
        ]
        if include_extra_msg:
            alice_rows.append((14, 14, 1, now - 300, 2, "最新补充：今天下午三点开会", None, 0, "", 0, None))
        con.executemany(f"INSERT INTO [{t_alice}] VALUES(?,?,?,?,?,?,?,?,?,?,?)", alice_rows)

        # Bob: low-signal "好的" + cross-chat duplicate transfer ID
        con.executemany(
            f"INSERT INTO [{t_bob}] VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 21, 1, now - 6 * HOUR, 1, "麻烦查收", None, 0, "", 0, None),
                (2, 22, 1, now - 3 * HOUR, 3, "好的", None, 0, "", 0, None),
                (3, 23, wf.TRANSFER_TYPE, now - 3 * HOUR, 3, _transfer_xml("1", "t-cross", amount="￥50.00", payer=BOB, receiver=ACCOUNT), None, 0, "", 0, None),
            ],
        )

        # Charlie: pending transfer to me + ambiguous currency "$"
        con.executemany(
            f"INSERT INTO [{t_charlie}] VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 31, 1, now - 8 * HOUR, 1, "发你账单", None, 0, "", 0, None),
                (2, 32, wf.TRANSFER_TYPE, now - 4 * HOUR, 4, _transfer_xml("1", "t-pending", amount="￥88.00", payer=CHARLIE, receiver=ACCOUNT, memo="尾款", invalid=now + DAY), None, 0, "", 0, None),
                (3, 33, wf.TRANSFER_TYPE, now - 4 * HOUR + 5, 4, _transfer_xml("1", "t-ambig", amount="$20.00", payer=CHARLIE, receiver=ACCOUNT), None, 0, "", 0, None),
            ],
        )

        # Group: @me, quote_me, name_mention, normal messages for stats & digest
        con.executemany(
            f"INSERT INTO [{t_group}] VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 41, 1, now - 3 * HOUR, 1, "这是我发的方案初稿", None, 0, "", 0, None),
                (2, 42, 1, now - 2 * HOUR, 2, "@逸尘本人 请看方案细节", None, 0, f"<msgsource><atuserlist>{ACCOUNT}</atuserlist></msgsource>", 0, None),
                (3, 43, (57 << 32) | 49, now - 90 * 60, 3, f"<msg><appmsg><type>57</type><title>赞同这个方向</title><refermsg><type>1</type><chatusr>{ACCOUNT}</chatusr><displayname>我</displayname><content>初稿</content></refermsg></appmsg></msg>", None, 0, "", 0, None),
                (4, 44, 1, now - HOUR, 2, "逸尘本人明天有空吗", None, 0, "", 0, None),
                (5, 45, 1, now - 50 * 60, 2, "再补充一条消息凑三条活跃度", None, 0, "", 0, None),
            ],
        )

        # Muted group: @all
        con.executemany(
            f"INSERT INTO [{t_muted}] VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 51, 1, now - 2 * HOUR, 3, "@所有人 明早发布", None, 0, "<msgsource><atuserlist>notify@all</atuserlist></msgsource>", 0, None),
            ],
        )
        con.commit()
    finally:
        con.close()

    manifest: dict = {"snapshot_id": snapshot_id, "profile": profile, "captured_at": captured_iso}
    if account_username is not None:
        manifest["account_username"] = account_username
    (root / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return {
        "now": now,
        "alice_id": fixture_chat_id(snapshot_id, ALICE),
        "bob_id": fixture_chat_id(snapshot_id, BOB),
        "charlie_id": fixture_chat_id(snapshot_id, CHARLIE),
        "group_id": fixture_chat_id(snapshot_id, GROUP),
        "muted_id": fixture_chat_id(snapshot_id, GROUP_MUTED),
        "img_hash_v2": img_hash_v2,
        "img_hash_xor": img_hash_xor,
    }


class WindowsParityTests(unittest.TestCase):
    def setUp(self):
        self.case = ARTIFACT_ROOT / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.case.mkdir(parents=True)
        self.snap = self.case / "snap"
        self.fx = build_rich_snapshot(self.snap)

    def run_snap(self, *args: str, snap: Path | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(vault_cli, "load_config", side_effect=AssertionError("Mac config accessed")), redirect_stdout(stdout), redirect_stderr(stderr):
            code = vault_cli.main(["snapshot", "--snapshot", str(snap or self.snap), *args]) or 0
        return code, stdout.getvalue(), stderr.getvalue()

    def test_status_sessions_unread_contacts_and_members(self):
        code, out, err = self.run_snap("status")
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertTrue(st["ready"])
        self.assertEqual(st["profile"], "full-snapshot-v1")
        self.assertNotIn("wxid_", out)

        code, out, err = self.run_snap("sessions", "--limit", "10")
        self.assertEqual(code, 0, err)
        sess = json.loads(out)
        self.assertEqual(sess["count"], 5)
        self.assertNotIn("wxid_", out)
        alice_sess = next(s for s in sess["sessions"] if s["chat_id"] == self.fx["alice_id"])
        self.assertIn("合同已发", alice_sess["last_message"])

        code, out_json, err = self.run_snap("unread")
        self.assertEqual(code, 0, err)
        unread_ids = {s["chat_id"] for s in json.loads(out_json)["sessions"]}
        self.assertIn(self.fx["alice_id"], unread_ids)
        self.assertNotIn(self.fx["bob_id"], unread_ids)
        code, out, err = self.run_snap("unread", "--format", "text")
        self.assertEqual(code, 0, err)
        self.assertIn("客户甲", out)

        code, out, err = self.run_snap("contacts", "--query", "客户")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["count"], 3)
        self.assertNotIn("wxid_", out)

        code, out, err = self.run_snap("contacts", "--chat-id", self.fx["alice_id"], "--format", "text")
        self.assertEqual(code, 0, err)
        self.assertIn("客户甲", out)

        code, out, err = self.run_snap("members", self.fx["group_id"])
        self.assertEqual(code, 0, err)
        mem = json.loads(out)
        self.assertEqual(mem["member_count"], 3)
        self.assertEqual(mem["owner"], "客户甲")
        self.assertNotIn("wxid_", out)

    def test_new_messages_diff_across_two_snapshots(self):
        snap2 = self.case / "snap2"
        fx2 = build_rich_snapshot(
            snap2,
            snapshot_id="33333333-4444-4555-8666-777777777777",
            now_ts=self.fx["now"],
            include_extra_msg=True,
        )
        code, out, err = self.run_snap("new-messages", "--previous-snapshot", str(self.snap), snap=snap2)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["chats"][0]["chat_id"], fx2["alice_id"])
        self.assertEqual(data["chats"][0]["new_count"], 1)
        self.assertIn("今天下午三点开会", data["chats"][0]["messages"][0]["content"])
        self.assertNotIn("wxid_", out)

    def test_history_type_filter_global_search_stats_and_txt_export(self):
        code, out, err = self.run_snap("history", self.fx["alice_id"], "--type", "file")
        self.assertEqual(code, 0, err)
        msgs = json.loads(out)["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertIn("报价单.pdf", msgs[0]["content"])

        code, out, err = self.run_snap("search", "--all", "明早发布")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["messages"][0]["chat_id"], self.fx["muted_id"])
        self.assertNotIn("wxid_", out)

        code, out, err = self.run_snap("stats", self.fx["group_id"])
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertEqual(st["total"], 5)
        self.assertEqual(st["top_senders"][0]["name"], "客户甲")
        self.assertNotIn("wxid_", out)

        txt_out = self.case / "alice.txt"
        code, out, err = self.run_snap(
            "export", self.fx["alice_id"], "--format", "txt", "--type", "text",
            "--output", str(txt_out), "--confirm-external-output",
        )
        self.assertEqual(code, 0, err)
        text = txt_out.read_text(encoding="utf-8")
        self.assertIn("什么时候可以签字", text)
        self.assertNotIn("报价单.pdf", text)

    def test_favorites_and_moments_reject_unsafe_xml_and_handle_chat_only_profile(self):
        code, out, err = self.run_snap("favorites")
        self.assertEqual(code, 0, err)
        favs = json.loads(out)["favorites"]
        self.assertEqual(len(favs), 3)
        summaries = [f["summary"] for f in favs]
        self.assertTrue(any("SQLite 规范" in s for s in summaries))
        self.assertIn("[已跳过不安全 XML]", summaries)
        self.assertNotIn("ENTITY", out)
        self.assertNotIn("wxid_", out)

        code, out, err = self.run_snap("moments", "--all")
        self.assertEqual(code, 0, err)
        posts = json.loads(out)["moments"]
        self.assertEqual(len(posts), 2)
        by_tid = {p["tid"]: p for p in posts}
        self.assertIn("今天上线新版本", by_tid["tid-1"]["content"])
        self.assertEqual(by_tid["tid-2"]["content"], "[已跳过不安全 XML]")
        self.assertNotIn("wxid_", out)

        chat_only = self.case / "chat-only"
        build_rich_snapshot(chat_only, profile="windows-chat-capture-v1")
        code, _, err = self.run_snap("favorites", snap=chat_only)
        self.assertEqual(code, 2)
        self.assertIn("--scope all", err)
        code, _, err = self.run_snap("moments", "--all", snap=chat_only)
        self.assertEqual(code, 2)
        self.assertIn("--scope all", err)

    def test_pending_all_signals_owner_inference_previous_and_private_output(self):
        # Test without account_username in manifest: should infer owner cleanly from private chats.
        inferred_snap = self.case / "inferred"
        build_rich_snapshot(inferred_snap, account_username=None, now_ts=self.fx["now"])
        out_file = self.case / "pending.json"
        denied, _, _ = self.run_snap("pending", "--since", "48h", "--output", str(out_file), snap=inferred_snap)
        self.assertEqual(denied, 2)
        self.assertFalse(out_file.exists())

        code, out, err = self.run_snap(
            "pending", "--since", "48h", "--output", str(out_file), "--confirm-external-output", snap=inferred_snap
        )
        self.assertEqual(code, 0, err)
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE(out_file.stat().st_mode), 0o600)
        data = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(data["owner_source"], "inferred_from_private_chats")
        self.assertEqual(data["trust"], "untrusted_snapshot_data")
        self.assertNotIn("wxid_", json.dumps(data, ensure_ascii=False))
        counts = data["counts"]
        self.assertGreaterEqual(counts["private_pending"], 2)  # Alice + Bob (low_signal)
        self.assertEqual(counts["at_me"], 1)
        self.assertEqual(counts["quote_me"], 1)
        self.assertEqual(counts["name_mention"], 1)
        self.assertEqual(counts["at_all"], 1)
        self.assertEqual(counts["pending_to_me"], 3)  # t-pending, t-ambig, t-cross
        self.assertEqual(counts["red_packets"], 1)
        self.assertEqual(counts["missed_calls"], 1)

        # Second run with --previous marks Alice as seen_before.
        code, out2, err2 = self.run_snap("pending", "--since", "48h", "--previous", str(out_file), snap=inferred_snap)
        self.assertEqual(code, 0, err2)
        second = json.loads(out2)
        self.assertTrue(all(item["seen_before"] for item in second["private_pending"]))

    def test_transfers_multi_currency_and_cross_chat_collision(self):
        code, out, err = self.run_snap("transfers")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertNotIn("wxid_", out)
        totals = data["totals"]
        self.assertEqual(totals["received"]["by_currency"], {"CNY": "100.00"})
        self.assertEqual(totals["paid"]["by_currency"], {"USD": "25.50"})
        self.assertEqual(totals["pending_in"]["by_currency"], {"CNY": "88.00"})
        self.assertEqual(totals["pending_in"]["unknown_amount"], 1)  # t-ambig ($20.00)
        self.assertEqual(totals["unclassified"], 1)  # t-cross (cross-chat collision)
        cross = next(r for r in data["transfers"] if len(r["source_chats"]) == 2)
        self.assertEqual(cross["direction"], "方向未知")
        self.assertEqual(cross["status"], "状态未知")

        code, txt, err = self.run_snap("transfers", "--format", "text")
        self.assertEqual(code, 0, err)
        self.assertIn("￥100.00", txt)
        self.assertIn("USD 25.50", txt)

    def test_digest_source_security_and_outputs(self):
        inside = self.snap / "digests"
        code, _, err = self.run_snap("digest-source", self.fx["group_id"], "--data-root", str(inside), "--confirm-external-output")
        self.assertEqual(code, 2)
        self.assertIn("inside the snapshot root", err)

        out_root = self.case / "digests"
        denied, _, _ = self.run_snap("digest-source", self.fx["group_id"], "--data-root", str(out_root))
        self.assertEqual(denied, 2)

        code, out, err = self.run_snap(
            "digest-source", self.fx["group_id"], "--data-root", str(out_root), "--confirm-external-output"
        )
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        folder = Path(res["folder"])
        for sub in ("profiles", "profiles-roast", "imgs", "sources"):
            self.assertTrue((folder / sub).is_dir())
        self.assertTrue(Path(res["source_json"]).is_file())
        self.assertTrue(Path(res["source_markdown"]).is_file())
        self.assertNotIn("wxid_", Path(res["source_json"]).read_text(encoding="utf-8"))

    def test_images_locate_and_decode_v2_and_xor_dat(self):
        attach = self.case / "attach"
        month = attach / hashlib.md5(ALICE.encode()).hexdigest() / "2026-11/Img"
        month.mkdir(parents=True)
        aes_key = b"0123456789abcdef"
        clear_png = b"\x89PNG\r\n\x1a\n" + b"synthetic-windows-png"
        clear_jpg = b"\xff\xd8\xff\xe0" + b"synthetic-xor-jpeg"
        (month / f"{self.fx['img_hash_v2']}_h.dat").write_bytes(_encrypted_v2_dat(clear_png, aes_key, 42))
        (month / f"{self.fx['img_hash_xor']}.dat").write_bytes(bytes(b ^ 0x5A for b in clear_jpg))

        cache = self.case / "img-cache"
        code, out, err = self.run_snap(
            "images", self.fx["alice_id"],
            "--attach-dir", str(attach),
            "--decode",
            "--aes-key-hex", aes_key.hex(),
            "--xor-key", "42",
            "--cache-dir", str(cache),
            "--confirm-external-output",
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["found"], 2)
        self.assertEqual(data["decoded"], 2)
        self.assertNotIn("wxid_", out)
        previews = [Path(img["preview_path"]).read_bytes() for img in data["images"]]
        self.assertIn(clear_png, previews)
        self.assertIn(clear_jpg, previews)

    def test_workflows_module_contains_no_forbidden_live_extraction_symbols(self):
        source = (ROOT / "scripts/snapshot_workflows.py").read_text(encoding="utf-8").casefold()
        for forbidden in ("openprocess", "readprocessmemory", "dpapi", "sqlcipher", "frida", "wx-cli"):
            self.assertNotIn(forbidden, source)

    def test_real_subprocess_e2e_all_parity_subcommands_under_cp1252(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        base_cmd = [sys.executable, str(ROOT / "scripts/vault_cli.py"), "snapshot", "--snapshot", str(self.snap)]
        cases = [
            ["validate"],
            ["status", "--format", "text"],
            ["sessions", "--format", "text"],
            ["unread", "--format", "text"],
            ["chats", "--query", "客户"],
            ["contacts", "--query", "客户", "--format", "text"],
            ["members", self.fx["group_id"], "--format", "text"],
            ["history", self.fx["alice_id"], "--type", "file", "--format", "text"],
            ["search", "--all", "明早发布", "--format", "text"],
            ["stats", self.fx["group_id"], "--format", "text"],
            ["favorites", "--format", "text"],
            ["moments", "--all", "--format", "text"],
            ["pending", "--since", "48h", "--format", "text"],
            ["transfers", "--format", "text"],
        ]
        for sub_args in cases:
            with self.subTest(cmd=sub_args[0]):
                proc = subprocess.run(base_cmd + sub_args, capture_output=True, text=True, encoding="utf-8", env=env)
                self.assertEqual(proc.returncode, 0, f"{sub_args}: stderr={proc.stderr}")
                self.assertTrue(proc.stdout.strip(), f"{sub_args}: empty stdout")
                self.assertNotIn("wxid_", proc.stdout)


if __name__ == "__main__":
    unittest.main()
