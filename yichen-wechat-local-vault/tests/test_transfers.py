"""PR30 regressions using synthetic messages and retained fixture-only databases."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import message_display
import vault_cli
import test_pending as fixture


def message(ts=100, state="1", tid="transfer-synthetic", *, amount="￥10.00", payer="partner",
            receiver="owner", sender=None, invalid=0, memo="", db=0, local_id=1):
    fields = {"paysubtype": state, "transferid": tid, "feedesc": amount, "payer_username": payer,
              "receiver_username": receiver, "invalidtime": str(invalid), "pay_memo": memo}
    body = "<msg><appmsg><type>2000</type><wcpayinfo>" + "".join(
        f"<{key}>{escape(value)}</{key}>" for key, value in fields.items()) + "</wcpayinfo></appmsg></msg>"
    return {"ts": ts, "body": body, "sender": payer if sender is None else sender, "db": db, "local_id": local_id}


class Scan:
    name_of = vault_cli.PendingScan.name_of

    def __init__(self, messages, *, me="owner", obey_bounds=True):
        self.messages = messages if isinstance(messages, dict) else {"partner": messages}
        self.me, self.calls, self.obey_bounds = me, [], obey_bounds
        self.contacts = {"partner": {"display_name": "测试对方"}, "owner": {"display_name": "测试本人"}}

    def fetch(self, username, **kwargs):
        self.calls.append((username, kwargs))
        return [m.copy() for m in self.messages.get(username, []) if not self.obey_bounds or (
            (kwargs.get("start") is None or m["ts"] >= kwargs["start"])
            and (kwargs.get("end") is None or m["ts"] <= kwargs["end"]))]


class TransferRegressionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(vault_cli, "load_config", side_effect=AssertionError("Real config prohibited"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self, messages, *, me="owner", start=None, end=None, until=1000):
        scan = Scan(messages, me=me)
        return vault_cli.collect_transfers(scan, list(scan.messages), start, end, until)

    def test_money_requires_a_complete_positive_amount_and_explicit_currency(self):
        for text in ("-5.00", "￥-5.00", "1,2.00", "￥1,2.00", "订单123 ￥10.00", "10.00",
                     "$10.00", "¥10.00", "￥NaN", "￥1e3", "￥1.001", "￥0", "￥12.00 USD",
                     "￥" + "9" * 10000, "￥１２.００", "JPY 1.50"):
            with self.subTest(text=text[:40]):
                self.assertEqual(vault_cli.transfer_money(text), (None, None))
                self.assertIsNone(vault_cli.transfer_amount(text))
        for text, value, currency in (("￥1,234.50", "1234.50", "CNY"), ("10元", "10", "CNY"),
                                      ("RMB 0.10", "0.10", "CNY"), ("USD 10.00", "10.00", "USD"),
                                      ("HK$9.50", "9.50", "HKD"), ("EUR 12", "12", "EUR"),
                                      ("10 GBP", "10", "GBP"), ("JPY 100", "100", "JPY")):
            with self.subTest(text=text):
                self.assertEqual(vault_cli.transfer_money(text), (Decimal(value), currency))
        self.assertIsNone(vault_cli.transfer_amount("USD 10.00"))

    def test_currency_totals_never_convert_or_mix_foreign_amounts(self):
        rows = []
        for i, (amount, payer, receiver) in enumerate((("￥0.10", "partner", "owner"),
                ("￥0.20", "partner", "owner"), ("USD 10.00", "partner", "owner"),
                ("USD 2.00", "owner", "partner"), ("订单123 ￥10.00", "partner", "owner"))):
            part, _ = self.collect([message(tid=str(i), amount=amount, payer=payer, receiver=receiver),
                                   message(200, "3", str(i))])
            rows.extend(part)
        totals = vault_cli.transfer_totals(rows)
        self.assertEqual(totals["received"]["by_currency"], {"CNY": "0.30", "USD": "10.00"})
        self.assertEqual(totals["received"]["unknown_amount"], 1)
        self.assertEqual(totals["net_by_currency"], {"CNY": "0.30", "USD": "8.00"})
        self.assertEqual(totals["net"], "+￥0.30 / +USD 8.00")

    def test_empty_or_partial_identity_is_never_incoming_or_outgoing(self):
        for me, payer, receiver in (("", "partner", ""), ("", "partner", "owner"),
                                    ("owner", "partner", ""), ("owner", "", "owner")):
            with self.subTest(me=me, payer=payer, receiver=receiver):
                rows, _ = self.collect([message(payer=payer, receiver=receiver)], me=me)
                self.assertEqual(rows[0]["direction"], "方向未知")
                self.assertEqual(vault_cli.transfer_totals(rows)["pending_in"]["count"], 0)
                self.assertEqual(vault_cli.transfer_totals(rows)["pending_out"]["count"], 0)
        self.assertEqual(Scan([], me="").name_of("", "未知"), "未知")

    def test_self_and_other_party_transfers_are_not_income(self):
        for payer, receiver, direction in (("owner", "owner", "本人之间"), ("partner", "third", "他人之间")):
            rows, _ = self.collect([message(payer=payer, receiver=receiver), message(200, "3")])
            self.assertEqual(rows[0]["direction"], direction)
            self.assertEqual(vault_cli.transfer_totals(rows)["received"]["count"], 0)

    def test_missing_ids_stay_separate_even_with_same_timestamp_and_payload(self):
        rows, unmatched = self.collect([message(tid=""), message(tid="", local_id=2),
                                       message(tid="", amount="￥20.00", db=1), message(200, "3", "")])
        self.assertEqual(len(rows), 3)
        self.assertEqual(unmatched, 1)
        self.assertEqual([r["amount"] for r in rows], ["￥10.00", "￥10.00", "￥20.00"])
        self.assertTrue(all(r["status"] == "状态未知" and r["issues"] for r in rows))
        self.assertEqual(vault_cli.transfer_totals(rows)["pending_in"]["count"], 0)

    def test_cross_chat_same_id_mirrors_or_collisions_are_one_excluded_row(self):
        for amount in ("￥10.00", "￥20.00"):
            with self.subTest(amount=amount):
                sources = {"partner": [message(), message(200, "3")],
                           "another-chat": [message(amount=amount), message(200, "3")]}
                rows, _ = self.collect(sources)
                self.assertEqual(rows, self.collect(dict(reversed(list(sources.items()))))[0])
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["direction"], rows[0]["status"]), ("方向未知", "状态未知"))
                self.assertEqual(len(rows[0]["source_chats"]), 2)
                self.assertTrue(any("跨会话" in issue for issue in rows[0]["issues"]))
                totals = vault_cli.transfer_totals(rows)
                self.assertEqual((totals["received"]["count"], totals["pending_in"]["count"], totals["unclassified"]), (0, 0, 1))

    def test_cross_chat_receipt_cannot_settle_another_chat_payment(self):
        rows, _ = self.collect({"partner": [message()], "another-chat": [message(200, "3")]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "状态未知")

    def test_cross_chat_conflict_uses_earliest_payload_not_chat_iteration_order(self):
        rows, _ = self.collect({"a-chat": [message(200, amount="￥20.00")], "z-chat": [message(100)]})
        self.assertEqual((rows[0]["ts"], rows[0]["amount"]), (100, "￥10.00"))
        rows, unmatched = self.collect({"a-chat": [message(200, amount="￥20.00")], "z-chat": [message(100)]}, start=150)
        self.assertEqual((rows, unmatched), ([], 1))

    def test_identical_reinitiations_use_earliest_payload_atomically(self):
        messages = [message(100, invalid=900, memo="首笔"), message(300, invalid=900, memo="首笔"), message(400, "3")]
        for ordering in itertools.permutations(messages):
            rows, _ = self.collect(list(ordering))
            self.assertEqual((rows[0]["ts"], rows[0]["amount"], rows[0]["memo"], rows[0]["status"]),
                             (100, "￥10.00", "首笔", "已收款"))
            self.assertFalse(rows[0]["issues"])

    def test_reinitiation_cannot_move_old_transfer_into_date_window(self):
        rows, _ = self.collect([message(1), message(1000000)], start=999999, until=1000001)
        self.assertEqual(rows, [])

    def test_conflicting_reinitiations_are_excluded_and_order_independent(self):
        for change in ({"amount": "￥20.00"}, {"receiver": "third"}, {"payer": "third"},
                       {"memo": "不同备注"}, {"invalid": 900}):
            with self.subTest(change=change):
                records = [message(100), message(200, **change), message(300, "3")]
                forward, _ = self.collect(records)
                backward, _ = self.collect(list(reversed(records)))
                self.assertEqual(forward, backward)
                row = forward[0]
                self.assertEqual((row["ts"], row["amount"], row["status"], row["direction"]),
                                 (100, "￥10.00", "状态未知", "方向未知"))
                self.assertTrue(any("冲突" in issue for issue in row["issues"]))
                self.assertEqual(vault_cli.transfer_totals(forward)["received"]["count"], 0)

    def test_latest_settlement_wins_and_acceptance_then_refund_is_not_timeout(self):
        rows, _ = self.collect([message(invalid=250), message(200, "3"), message(300, "4")])
        self.assertEqual((rows[0]["status"], rows[0]["settled_at"]), ("已退还", vault_cli.fmt_minute(300)))
        totals = vault_cli.transfer_totals(rows)
        self.assertEqual((totals["received"]["count"], totals["returned"]), (0, 1))
        rows, _ = self.collect([message(), message(200, "4"), message(300, "3")])
        self.assertEqual(rows[0]["status"], "已收款")

    def test_refund_without_deadline_or_actor_is_not_called_timeout(self):
        rows, _ = self.collect([message(), message(200, "4", sender="")])
        self.assertEqual(rows[0]["status"], "已退还")
        rows, _ = self.collect([message(invalid=200), message(200, "4", sender="")])
        self.assertEqual(rows[0]["status"], "超时退还")

    def test_latest_same_second_conflict_and_unknown_state_are_uncertain(self):
        for terminal in ([message(200, "3"), message(200, "4")], [message(200, "99")],
                         [message(200, "3"), message(300, "99")]):
            rows, _ = self.collect([message(), *terminal])
            self.assertEqual(rows[0]["status"], "状态未知")
            self.assertTrue(rows[0]["issues"])
            self.assertEqual(vault_cli.transfer_totals(rows)["received"]["count"], 0)

    def test_receipt_before_initiation_is_not_applied(self):
        rows, _ = self.collect([message(), message(50, "3")])
        self.assertEqual(rows[0]["status"], "待收款")

    def test_later_receipts_are_not_anchored_to_first_duplicate(self):
        rows, _ = self.collect([message(), message(200, "3"), message(300, "3")])
        self.assertEqual(rows[0]["settled_at"], vault_cli.fmt_minute(300))

    def test_snapshot_caps_fetch_and_state_even_if_adapter_returns_future_rows(self):
        for end in (None, 110):
            scan = Scan([message(), message(300, "3"), message(400, tid="future")], obey_bounds=False)
            rows, _ = vault_cli.collect_transfers(scan, ["partner"], 90, end, 200)
            self.assertEqual(scan.calls[0][1]["end"], 200)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "待收款")
            self.assertEqual(rows[0]["status_until"], vault_cli.fmt_minute(200))

    def test_state_inference_stops_at_actual_settlement_horizon(self):
        rows, _ = self.collect([message(invalid=500000)], end=110, until=1000000)
        self.assertEqual(rows[0]["status"], "待收款")
        self.assertEqual(rows[0]["status_until"], vault_cli.fmt_minute(110 + 3 * 86400))

    def test_expiry_boundary_is_inclusive_and_malformed_timestamp_is_bounded(self):
        rows, _ = self.collect([message(invalid=1000)])
        self.assertEqual(rows[0]["status"], "已过期未收")
        for invalid in ("9" * 5000, "１２３", "n/a"):
            rows, _ = self.collect([message(invalid=invalid)])
            self.assertEqual(rows[0]["status"], "待收款")

    def test_structured_parser_ignores_tags_inside_memo(self):
        row, _ = self.collect([message(memo="<feedesc>￥999.00</feedesc><transferid>other</transferid>")])
        self.assertEqual(row[0]["amount_value"], "10.00")
        self.assertEqual(row[0]["memo"], "[内嵌内容已隐藏]")

    def test_malformed_duplicate_and_entity_xml_fail_closed(self):
        for body in ("<msg><appmsg>", '<!DOCTYPE msg [<!ENTITY x "payload">]>' + message()["body"],
                     message()["body"].replace("</wcpayinfo>", "<feedesc>￥999</feedesc></wcpayinfo>"),
                     message()["body"].replace("￥10.00", "<secret>hidden</secret>")):
            record = message()
            record["body"] = body
            rows, unmatched = self.collect([record])
            self.assertEqual((rows, unmatched), ([], 1))

    def test_transfer_pii_and_credentials_never_escape_in_json_text_or_history(self):
        memo = "payer-alias receiver-alias private-transfer-id wxid_secret_fixture token=synthetic-secret"
        record = message(tid="private-transfer-id", payer="payer-alias", receiver="receiver-alias", memo=memo)
        rows, _ = self.collect([record], me="receiver-alias")
        history = message_display.format_message_content(vault_cli.TRANSFER_TYPE, record["body"])
        for output in (json.dumps(rows, ensure_ascii=False), history):
            for marker in ("payer-alias", "receiver-alias", "private-transfer-id", "wxid_secret_fixture", "synthetic-secret"):
                self.assertNotIn(marker, output)
        structured = message_display.public_value({"payer_username": "payer-alias", "receiver_username": "receiver-alias", "transferid": "private-transfer-id"})
        self.assertTrue(all(v == message_display.HIDDEN_ID for v in structured.values()))

    def test_unknown_identity_mode_is_opt_in_and_ambiguous_speakers_do_not_guess(self):
        scan = vault_cli.PendingScan.__new__(vault_cli.PendingScan)
        scan.me, scan.contacts, scan.my_names = "", {}, set()
        with mock.patch.object(vault_cli, "load_config", return_value={}):
            scan.identify_self({}, allow_unknown=True)
            self.assertEqual(scan.me, "")
            scan.identify_self({"chat": [{"sender": "one"}, {"sender": "two"}]}, allow_unknown=True)
            self.assertEqual(scan.me, "")
            with self.assertRaises(SystemExit):
                scan.identify_self({})


class TransferCLIRegressionTests(unittest.TestCase):
    setUp = fixture.PendingTests.setUp
    run_cli = fixture.PendingTests.run_cli

    def fingerprint(self):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.vault.rglob("*") if p.is_file()}

    def test_cli_snapshot_cutoff_and_source_immutability(self):
        before = self.fingerprint()
        cutoff = self.now - int(19.5 * fixture.HOUR)
        manifest = {"created_ts": cutoff, "gaps": []}
        with mock.patch.object(vault_cli, "pending_manifest", return_value=manifest):
            data = json.loads(self.run_cli("transfers", "--chat", "客户丁"))
        self.assertEqual(data["data_until"], vault_cli.fmt_minute(cutoff))
        self.assertEqual(data["status_until"], data["data_until"])
        self.assertEqual([(r["direction"], r["status"]) for r in data["transfers"]], [("转入", "待收款")])
        self.assertEqual(before, self.fingerprint())

    def test_cli_unknown_owner_returns_rows_and_gap_without_false_totals(self):
        with mock.patch.object(vault_cli.PendingScan, "identify_self", return_value=None):
            data = json.loads(self.run_cli("transfers"))
        self.assertTrue(data["transfers"])
        self.assertTrue(all(row["direction"] == "方向未知" for row in data["transfers"]))
        self.assertTrue(any("无法确认本账号" in gap for gap in data["gaps"]))
        self.assertEqual(data["totals"]["received"]["count"], 0)

    def test_cli_json_text_include_identifiers_and_history_keep_secrets_hidden(self):
        record = message(tid="private-transfer-id", payer="payer-alias", receiver=fixture.ME,
                         amount="USD 10.00", memo="payer-alias private-transfer-id token=synthetic-secret")
        table = vault_cli.message_table(fixture.ALICE)
        with sqlite3.connect(self.vault / "message/message_0.db") as con:
            con.execute(f"INSERT INTO [{table}] VALUES(?,?,?,?,?,?,NULL,?,?,?)",
                        (1000, 1000, fixture.TRANSFER, 2, self.now - 10, record["body"], 0, None, 0))
        before = self.fingerprint()
        for prefix in ([], ["--include-identifiers"]):
            for args in (("transfers",), ("transfers", "--format", "text"), ("history", "客户甲", "--format", "text")):
                output = self.run_cli(*prefix, *args)
                for marker in ("payer-alias", "private-transfer-id", "synthetic-secret", "<wcpayinfo>"):
                    self.assertNotIn(marker, output)
                self.assertIn("USD 10.00", output)
        hidden = json.loads(self.run_cli("transfers"))
        shown = json.loads(self.run_cli("--include-identifiers", "transfers"))
        self.assertEqual(hidden["transfers"][-1]["username"], message_display.HIDDEN_ID)
        self.assertEqual(shown["transfers"][-1]["username"], fixture.ALICE)
        self.assertEqual(hidden["totals"]["pending_in"]["by_currency"], {"CNY": "88.00", "USD": "10.00"})
        self.assertEqual(before, self.fingerprint())


if __name__ == "__main__":
    unittest.main()
