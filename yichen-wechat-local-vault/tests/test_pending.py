"""Synthetic checks for `vault_cli.py pending`; no real vault, manifest or configuration is read."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import vault_cli

ARTIFACT_ROOT = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-pending-tests-")).resolve()

ME = "wxid_owner_pending"
CONFIG = {"wxid": ME + "_9f3e"}  # the account's data folder name adds a 4-hex suffix
ALICE, BOB, CAROL, DAVE, ERIN, FRANK = (f"wxid_{name}_pending" for name in ("alice", "bob", "carol", "dave", "erin", "frank"))
GROUP, QUIET, UNNAMED = "pending_team@chatroom", "pending_quiet@chatroom", "pending_unnamed@chatroom"
TRANSFER = (2000 << 32) | 49
RED_PACKET = (2001 << 32) | 49
QUOTE = (57 << 32) | 49
HOUR = 3600
HIDDEN_ID = "[内部标识已隐藏]"

CONTACTS = [
    # username, local_type (1 = friend), nick_name, remark, chat_room_notify (0 = muted)
    (ME, 1, "测试本人", "", 1),
    (ALICE, 1, "阿甲", "客户甲", 1),
    (BOB, 1, "阿乙", "客户乙", 1),
    (CAROL, 1, "阿丙", "客户丙", 1),
    (DAVE, 1, "阿丁", "客户丁", 1),
    (ERIN, 3, "陌生人戊", "", 1),
    (FRANK, 1, "老  朋友 ", "", 1),  # names stay verbatim: `history "<name>"` matches them exactly
    (GROUP, 2, "项目群", "", 1),
    (QUIET, 2, "闲聊群", "", 0),
]
# Each message DB numbers its senders on its own.
SENDER_IDS = [{ME: 1, ALICE: 2, BOB: 3, CAROL: 4, DAVE: 5, ERIN: 6, FRANK: 7}, {ALICE: 1, ME: 9}]
QUOTE_ME = (f"<msg><appmsg><title>好的我看下</title><type>57</type><refermsg><type>1</type><chatusr>{ME}</chatusr>"
            "<displayname>测试本人</displayname><content>方案初稿</content></refermsg></appmsg></msg>")
QUOTE_XML = (f"<msg><appmsg><title>看这个</title><type>57</type><refermsg><type>1</type><chatusr>{BOB}</chatusr>"
             "<displayname>阿乙</displayname><content>&lt;img src='x'/&gt;</content></refermsg></appmsg></msg>")


def transfer(state: int, tid: str, *, receiver: str = ME, invalid: int = 0, memo: str = "") -> str:
    # payer_username is empty, as WeChat usually leaves it: the sender of state 1 pays.
    return (f"<msg><appmsg><title>微信转账</title><type>2000</type><wcpayinfo><paysubtype>{state}</paysubtype>"
            f"<feedesc>￥88.00</feedesc><transferid>{tid}</transferid><invalidtime>{invalid}</invalidtime>"
            f"<payer_username></payer_username><receiver_username>{receiver}</receiver_username>"
            f"<pay_memo>{memo}</pay_memo></wcpayinfo></appmsg></msg>")


def call(status: str) -> str:
    return f'<voipmsg type="VoIPBubbleMsg"><VoIPBubbleMsg><msg><![CDATA[{status}]]></msg></VoIPBubbleMsg></voipmsg>'


def at(*usernames: str) -> str:
    return f"<msgsource><atuserlist><![CDATA[,{','.join(usernames)}]]></atuserlist></msgsource>"


def fixture_messages(ago) -> list[tuple]:
    """(chat, sent at, sender, local_type, content, source, message DB); ("zstd", text) is stored compressed."""
    return [
        # ALICE: my earlier message sits in message_1.db; her question, red packet and transfer wait.
        (ALICE, ago(30), ME, 1, "资料发你了", None, 1),
        (ALICE, ago(5), ALICE, 1, ("zstd", "收到，请问报价多少？"), None, 0),
        (ALICE, ago(4), ALICE, RED_PACKET, "<msg><appmsg><title>恭喜发财，大吉大利</title><type>2001</type></appmsg></msg>", None, 0),
        (ALICE, ago(3), ALICE, TRANSFER, transfer(1, "T-ALICE", invalid=ago(-20), memo="定金"), None, 0),
        # BOB: answered; his older transfer timed out and came back (a refund names the payer as receiver).
        (BOB, ago(50), BOB, TRANSFER, transfer(1, "T-BOB", invalid=ago(26)), None, 0),
        (BOB, ago(26), ME, TRANSFER, transfer(4, "T-BOB", receiver=BOB), None, 0),
        (BOB, ago(6), BOB, 1, "在吗", None, 0),
        (BOB, ago(5), ME, 1, "在的", None, 0),
        # CAROL: I returned her transfer before it expired; only thanks and a sticker follow.
        (CAROL, ago(40), CAROL, TRANSFER, transfer(1, "T-CAROL", invalid=ago(16)), None, 0),
        (CAROL, ago(30), ME, TRANSFER, transfer(4, "T-CAROL", receiver=CAROL), None, 0),
        (CAROL, ago(10), CAROL, 1, "谢谢", None, 0),
        (CAROL, ago(9), CAROL, 47, '<msg><emoji md5="fixture"/></msg>', None, 0),
        # DAVE: a received transfer, my transfer he has not taken, then a connected call.
        (DAVE, ago(20), DAVE, TRANSFER, transfer(1, "T-DAVE-IN", invalid=ago(-4)), None, 0),
        (DAVE, ago(19), ME, TRANSFER, transfer(3, "T-DAVE-IN"), None, 0),
        (DAVE, ago(12), ME, TRANSFER, transfer(1, "T-DAVE-OUT", receiver=DAVE, invalid=ago(-12)), None, 0),
        (DAVE, ago(8), DAVE, 1, "方便电话吗", None, 0),
        (DAVE, ago(7), DAVE, 50, call("通话时长 03:12"), None, 0),
        # ERIN: a stranger; a system notice, a missed call, then a recall.
        (ERIN, ago(4), "", 10000, "你已添加了陌生人戊，现在可以开始聊天了。", None, 0),
        (ERIN, ago(2), ERIN, 50, call("对方已取消"), None, 0),
        (ERIN, ago(1), ERIN, 10002, '<sysmsg type="revokemsg"><revokemsg>"陌生人戊" 撤回了一条消息</revokemsg></sysmsg>', None, 0),
        # FRANK: waiting too, but older than the default 7-day private window.
        (FRANK, ago(9 * 24), FRANK, 1, "好久不见", None, 0),
        # GROUP (notifications on): @me with a compressed source, a quote, my name, @all over the cap.
        (GROUP, ago(60), BOB, 1, "@测试本人 很早的事", at(ME), 0),
        (GROUP, ago(20), ALICE, 1, f"{ALICE}:\n大家看下这个方案", None, 0),
        (GROUP, ago(19), BOB, 1, "@测试本人 你看看", ("zstd", at(ME)), 0),
        (GROUP, ago(18), CAROL, QUOTE, QUOTE_ME, None, 0),
        (GROUP, ago(17), DAVE, 1, "测试本人明天来吗", None, 0),
        (GROUP, ago(16), ME, 1, "收到", None, 0),
        (GROUP, ago(15), ALICE, 1, "@所有人 周五开会", at("notify@all"), 0),
        (GROUP, ago(14), BOB, 1, "@所有人 交材料", None, 0),
        (GROUP, ago(13), CAROL, 1, "@所有人 第三条", at("notify@all"), 0),
        (GROUP, ago(3.5), DAVE, QUOTE, QUOTE_XML, None, 0),
        (GROUP, ago(3), ALICE, 1, "@测试本人 还在吗", at(ME), 0),
        # QUIET (muted): one @all.
        (QUIET, ago(10), BOB, 1, "@所有人 聚餐", at("notify@all"), 0),
        # UNNAMED has no contact row: it is titled by its busiest members.
        (UNNAMED, ago(12), ALICE, 1, "第一条", None, 0),
        (UNNAMED, ago(11), ALICE, 1, "第二条", None, 0),
        (UNNAMED, ago(10.5), BOB, 1, "@测试本人 看群公告", at(ME), 0),
    ]


def stored(value) -> tuple:
    if isinstance(value, tuple):
        return zstandard.ZstdCompressor().compress(value[1].encode("utf-8")), 4
    return value, 0


def write_db(path: Path, statements: list[str], rows: list[tuple[str, tuple]] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for statement in statements:
            con.execute(statement)
        for statement, values in rows:
            con.execute(statement, values)
        con.commit()
    finally:
        con.close()


def build_vault(root: Path, now: int) -> None:
    """Contact, session and two message DBs laid out like a decrypted WeChat 4.x vault."""
    def ago(hours: float) -> int:
        return now - int(hours * HOUR)

    write_db(root / "contact/contact.db", [
        "CREATE TABLE contact(id INTEGER, username TEXT, local_type INTEGER, alias TEXT, remark TEXT, nick_name TEXT, chat_room_notify INTEGER)",
    ], [("INSERT INTO contact VALUES(?,?,?,?,?,?,?)", (index, username, kind, "", remark, nick, notify))
        for index, (username, kind, nick, remark, notify) in enumerate(CONTACTS, 1)])
    sessions = [(ALICE, 3, 3), (BOB, 0, 5), (CAROL, 0, 9), (DAVE, 0, 7), (ERIN, 1, 1), (FRANK, 0, 9 * 24),
                (GROUP, 5, 3), (QUIET, 0, 10), (UNNAMED, 0, 10.5), ("gh_pending_news", 1, 2), ("filehelper", 0, 2)]
    write_db(root / "session/session.db", [
        "CREATE TABLE SessionTable(username TEXT, unread_count INTEGER, summary TEXT, last_timestamp INTEGER, "
        "last_msg_type INTEGER, last_msg_sender TEXT, last_sender_display_name TEXT)",
    ], [("INSERT INTO SessionTable VALUES(?,?,?,?,?,?,?)", (username, unread, "摘要", ago(hours), 1, "", ""))
        for username, unread, hours in sessions])
    by_db: list[list[tuple[str, tuple]]] = [[], []]
    tables: list[set[str]] = [set(), set()]
    for local_id, (chat, ts, sender, local_type, content, source, db) in enumerate(fixture_messages(ago), 1):
        table = "Msg_" + hashlib.md5(chat.encode()).hexdigest()
        if table not in tables[db]:
            tables[db].add(table)
            by_db[db].append((
                f"CREATE TABLE [{table}](local_id INTEGER, server_id INTEGER, local_type INTEGER, real_sender_id INTEGER, "
                "create_time INTEGER, message_content BLOB, compress_content BLOB, WCDB_CT_message_content INTEGER, "
                "source BLOB, WCDB_CT_source INTEGER)", ()))
        body, body_flag = stored(content)
        source_value, source_flag = stored(source) if source else (None, 0)
        by_db[db].append((f"INSERT INTO [{table}] VALUES(?,?,?,?,?,?,NULL,?,?,?)",
                          (local_id, local_id, local_type, SENDER_IDS[db].get(sender, 0), ts, body, body_flag, source_value, source_flag)))
    for db, rows in enumerate(by_db):
        names = [("INSERT INTO Name2Id(rowid, user_name) VALUES(?,?)", (rowid, username)) for username, rowid in SENDER_IDS[db].items()]
        write_db(root / f"message/message_{db}.db", ["CREATE TABLE Name2Id(user_name TEXT)"], names + rows)


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())
        self.vault = ARTIFACT_ROOT / f"{self._testMethodName}-{uuid.uuid4().hex}" / "vault"
        build_vault(self.vault, self.now)

    def run_cli(self, *argv: str, config: dict = CONFIG, vault: Path | None = None) -> str:
        out = io.StringIO()
        with mock.patch.object(vault_cli, "load_config", return_value=dict(config)), redirect_stdout(out):
            code = vault_cli.main(["--decrypted-dir", str(vault or self.vault), *argv]) or 0
        self.assertEqual(code, 0)
        return out.getvalue()

    def pending(self, *argv: str, **kwargs) -> dict:
        return json.loads(self.run_cli("pending", "--since", "2d", *argv, **kwargs))

    def test_counts_cover_every_signal(self):
        data = self.pending()
        self.assertEqual(data["counts"], {
            "private_pending": 3, "private_pending_new": 3, "at_me": 3, "quote_me": 1, "name_mention": 1, "at_all": 3,
            "pending_to_me": 1, "refunded_to_me": 1, "pending_from_me": 1, "red_packets": 1, "missed_calls": 1,
        })
        self.assertEqual(data["window"]["how"], "近 2d")
        self.assertEqual(data["window"]["until"] - data["window"]["since"], 48 * HOUR)
        self.assertEqual(data["manifest"]["gaps"], ["找不到这个明文目录的解密 manifest，无法确认数据新鲜度"])

    def test_private_chat_waits_until_the_owner_replies_or_a_call_connects(self):
        items = {item["chat"]: item for item in self.pending()["private_pending"]}
        # Newest first, low-signal chats last; replied, called back, official and old chats are absent.
        self.assertEqual(list(items), ["陌生人戊", "客户甲", "客户丙"])
        alice = items["客户甲"]
        self.assertEqual((alice["kind"], alice["unread"], alice["waiting_count"]), ("好友", 3, 3))
        self.assertEqual((alice["messages"][0]["from"], alice["messages"][0]["text"]), ("客户甲", "收到，请问报价多少？"))
        self.assertEqual(alice["messages"][-1]["text"], "[转账] ￥88.00（备注：定金）")
        self.assertFalse(alice["low_signal"])
        erin = items["陌生人戊"]
        self.assertEqual((erin["kind"], erin["waiting_count"]), ("非好友", 2))  # notice + missed call; the recall is skipped
        self.assertTrue(items["客户丙"]["low_signal"])
        self.assertTrue(all(item["new_in_window"] and not item["seen_before"] for item in items.values()))

        older = [item["chat"] for item in self.pending("--pending-days", "10")["private_pending"]]
        self.assertEqual(older, ["陌生人戊", "客户甲", "老  朋友 ", "客户丙"])

    def test_group_hits_follow_mutes_caps_and_later_replies(self):
        groups = self.pending()["groups"]
        at_me = groups["at_me"]
        self.assertEqual([(hit["chat"], hit["text"]) for hit in at_me], [
            ("项目群", "@测试本人 还在吗"),
            ("未命名群（客户甲、客户乙 等）", "@测试本人 看群公告"),
            ("项目群", "@测试本人 你看看"),
        ])
        self.assertEqual([hit["you_spoke_after"] for hit in at_me], [False, False, True])
        self.assertEqual([ctx["text"] for ctx in at_me[2]["context"]], ["大家看下这个方案"])
        # Quoted text that is itself XML is shown as a placeholder, never raw.
        self.assertEqual(at_me[0]["context"][-1]["text"], "看这个（引用 阿乙：[消息]）")
        self.assertEqual([(hit["from"], hit["text"]) for hit in groups["quote_me"]], [("客户丙", "好的我看下（引用 测试本人：方案初稿）")])
        self.assertEqual([hit["from"] for hit in groups["name_mention"]], ["客户丁"])
        self.assertEqual([(hit["chat"], hit["text"], hit["muted_group"]) for hit in groups["at_all"]], [
            ("项目群", "@所有人 交材料", False),
            ("项目群", "@所有人 周五开会", False),
            ("闲聊群", "@所有人 聚餐", True),
        ])
        self.assertNotIn("you_spoke_after", groups["at_all"][0])

    def test_money_and_calls(self):
        data = self.pending()
        money = data["money"]
        self.assertEqual([(t["from"], t["chat"], t["amount"], t["memo"], t["maybe_expired"]) for t in money["pending_to_me"]],
                         [("客户甲", "客户甲", "￥88.00", "定金", False)])
        # BOB's transfer expired unreceived; returning CAROL's early was deliberate.
        self.assertEqual([t["from"] for t in money["refunded_to_me"]], ["客户乙"])
        self.assertEqual([t["to"] for t in money["pending_from_me"]], ["客户丁"])
        self.assertEqual([(p["chat"], p["opened_hint"]) for p in money["red_packets"]], [("客户甲", False)])
        self.assertEqual([(c["chat"], c["text"], c["you_contacted_after"]) for c in data["missed_calls"]],
                         [("陌生人戊", "[通话] 对方已取消", False)])

    def test_identifiers_are_hidden_unless_requested(self):
        text = self.run_cli("pending", "--since", "2d")
        for marker in ("wxid_", "@chatroom", "gh_pending"):
            self.assertNotIn(marker, text)
        self.assertEqual(json.loads(text)["private_pending"][0]["username"], HIDDEN_ID)
        shown = json.loads(self.run_cli("--include-identifiers", "pending", "--since", "2d"))
        self.assertEqual(shown["private_pending"][0]["username"], ERIN)
        self.assertEqual(shown["groups"]["at_me"][0]["username"], GROUP)

    def test_text_report_lists_each_section(self):
        text = self.run_cli("pending", "--since", "2d", "--format", "text")
        for expected in (
            "# 待处理消息候选（",
            "- 统计：私聊待回复 3｜其中本期新增 3｜@我 3｜引用我 1｜提到我 1｜@所有人 3｜待收转账 1｜已退还转账 1｜转出未收 1｜私聊红包 1｜未接来电 1",
            "### 客户甲（好友，未读 3，待回 3 条；最后 ",
            "### 客户丙（好友，已读，待回 2 条，疑似客套/表情；最后 ",
            "【项目群】客户甲：@测试本人 还在吗（提醒群，之后我未在该群发言）",
            "上文",
            "看这个（引用 阿乙：[消息]）",
            "- 待我收款：客户甲 在【客户甲】",
            "- 已过期退还（我没收）：客户乙 在【客户乙】",
            "- 我转出、对方未收：给 客户丁（【客户丁】",
            "- 私聊红包：客户甲",
            "：[通话] 对方已取消（之后我未联系对方）",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("<img", text)
        self.assertNotIn("wxid_", text)

    def test_output_file_is_private_and_previous_run_marks_listed_chats(self):
        first = self.vault.parent / "out/first.json"
        summary = json.loads(self.run_cli("pending", "--since", "2d", "--output", str(first)))
        self.assertEqual(summary["output"], str(first))
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        saved = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(saved["counts"], summary["counts"])
        self.assertEqual(saved["private_pending"][0]["username"], HIDDEN_ID)

        again = json.loads(self.run_cli("pending", "--since", "last", "--previous", str(first)))
        self.assertEqual(again["window"]["since"], saved["window"]["until"])
        self.assertEqual(again["window"]["how"], "接上次检查")
        self.assertEqual(again["counts"]["private_pending"], 3)
        self.assertEqual(again["counts"]["private_pending_new"], 0)
        self.assertTrue(all(item["seen_before"] and not item["new_in_window"] for item in again["private_pending"]))

        report = self.vault.parent / "out/report.md"
        summary_text = self.run_cli("pending", "--since", "2d", "--format", "text", "--output", str(report))
        self.assertIn(f"完整结果：{report}", summary_text)
        self.assertTrue(report.read_text(encoding="utf-8").startswith("# 待处理消息候选（"))
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)

    def test_window_options_are_bounded(self):
        data = self.pending("--since", "30d")
        self.assertEqual(data["window"]["until"] - data["window"]["since"], 14 * 86400)
        self.assertTrue(data["window"]["how"].endswith("（超过 14 天，已截断）"))
        for argv, message in [(["--since", "last"], "--previous"), (["--pending-days", "0"], "--pending-days")]:
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as caught:
                self.run_cli("pending", *argv)
            self.assertIn(message, str(caught.exception.code))

    def test_owner_comes_from_the_messages_when_config_disagrees(self):
        expected = self.pending()["counts"]
        for config in ({}, {"wxid": ALICE}):
            with self.subTest(config=config):
                self.assertEqual(self.pending(config=config)["counts"], expected)

    def test_window_ends_at_the_last_successful_decrypt_of_this_vault(self):
        vault = self.vault.parent / "v/decrypted/current"
        build_vault(vault, self.now)
        manifests = vault.parent.parent / "manifests"
        manifests.mkdir()
        made = self.now - 3 * HOUR

        def manifest(name: str, created: int, **extra) -> None:
            data = {"created_at": datetime.fromtimestamp(created).isoformat(timespec="seconds"),
                    "decrypted_dir": str(vault), "records": [], "stale_databases": [], **extra}
            (manifests / name).write_text(json.dumps(data), encoding="utf-8")

        manifest("decrypt-20260101-000001.json", made, stale_databases=["message/message_0.db"], records=[{
            "rel": "message/message_0.db", "status": "miss",
            "reason": "[Errno 1] Operation not permitted: '/x/xwechat_files/wxid_secret_owner_1a2b/db_storage/message/message_0.db'",
        }])
        manifest("decrypt-20260101-000002.json", self.now - HOUR, aborted=True)
        manifest("decrypt-20260101-000003.json", self.now, decrypted_dir=str(self.vault))  # another vault's run

        data = json.loads(self.run_cli("pending", "--since", "2d", vault=vault))
        self.assertEqual(data["window"]["until"], made)
        self.assertEqual(data["manifest"]["name"], "decrypt-20260101-000001.json")
        gaps = data["manifest"]["gaps"]
        self.assertTrue(gaps[0].startswith("最近一次解析被中止（decrypt-20260101-000002.json），数据停留在"))
        self.assertTrue(any(gap.startswith("message/message_0.db: miss [Errno 1]") for gap in gaps))
        self.assertIn("manifest 已超过 2 小时，请先增量解析", gaps)
        self.assertNotIn("wxid_secret_owner", json.dumps(data, ensure_ascii=False))


class TransferTests(PendingTests.__base__):
    setUp = PendingTests.setUp
    run_cli = PendingTests.run_cli

    def transfers(self, *argv: str) -> dict:
        return json.loads(self.run_cli("transfers", *argv))

    def test_every_transfer_with_direction_status_and_totals(self):
        data = self.transfers()
        self.assertEqual([(t["direction"], t["counterpart"], t["amount"], t["memo"], t["status"]) for t in data["transfers"]], [
            ("转入", "客户乙", "￥88.00", "", "超时退还"),
            ("转入", "客户丙", "￥88.00", "", "已退还"),
            ("转入", "客户丁", "￥88.00", "", "已收款"),
            ("转出", "客户丁", "￥88.00", "", "待收款"),
            ("转入", "客户甲", "￥88.00", "定金", "待收款"),
        ])
        totals = data["totals"]
        self.assertEqual((totals["received"]["count"], totals["received"]["amount"]), (1, "￥88.00"))
        self.assertEqual((totals["paid"]["count"], totals["net"], totals["returned"]), (0, "+￥88.00", 2))
        self.assertEqual((totals["pending_in"]["count"], totals["pending_out"]["count"]), (1, 1))
        self.assertTrue(data["transfers"][2]["settled_at"])
        self.assertNotIn("wxid_", json.dumps(data, ensure_ascii=False))

    def test_chat_and_time_filters(self):
        self.assertEqual([t["direction"] for t in self.transfers("--chat", "客户丁")["transfers"]], ["转入", "转出"])
        # BOB's refund falls inside the window, but the payment started before it.
        start = datetime.fromtimestamp(self.now - 45 * HOUR).strftime("%Y-%m-%d %H:%M")
        self.assertEqual([t["counterpart"] for t in self.transfers("--start-time", start)["transfers"]],
                         ["客户丙", "客户丁", "客户丁", "客户甲"])
        with self.assertRaises(SystemExit):
            self.run_cli("transfers", "--chat", "不存在的人")

    def test_text_report_and_chat_display(self):
        report = self.run_cli("transfers", "--format", "text")
        self.assertIn("转入已收 1 笔 ￥88.00｜转出被收 0 笔 ￥0.00｜净额 +￥88.00", report)
        self.assertIn("转入 客户甲 ￥88.00（备注：定金） · 待收款", report)
        history = self.run_cli("history", "客户丁", "--format", "text")
        self.assertIn("[转账] ￥88.00 · 发出", history)
        self.assertIn("[转账] ￥88.00 · 已收款", history)


if __name__ == "__main__":
    unittest.main()
