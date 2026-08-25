from __future__ import annotations

import ast
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/vault_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))

import vault_cli  # noqa: E402


class QueryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.decrypted = Path(self.temporary.name) / "decrypted"
        (self.decrypted / "contact").mkdir(parents=True)
        (self.decrypted / "session").mkdir(parents=True)
        (self.decrypted / "message").mkdir(parents=True)
        (self.decrypted / "favorite").mkdir(parents=True)
        (self.decrypted / "sns").mkdir(parents=True)
        self.local_app_data = Path(self.temporary.name) / "local-app-data"
        self.username = "fixture-user"
        self.group_username = "fixture-group@chatroom"
        self.member_username = "fixture-member"
        self.timestamp = int(time.time())

        connection = sqlite3.connect(self.decrypted / "contact/contact.db")
        try:
            connection.execute(
                "CREATE TABLE contact(id INTEGER, username TEXT, nick_name TEXT, remark TEXT, alias TEXT)"
            )
            connection.execute(
                "INSERT INTO contact VALUES (1, ?, 'Fixture Nick', 'Fixture Friend', 'fixture')",
                (self.username,),
            )
            connection.execute(
                "INSERT INTO contact VALUES (2, ?, 'Fixture Group', '', '')",
                (self.group_username,),
            )
            connection.execute(
                "INSERT INTO contact VALUES (3, ?, 'Fixture Member', '', '')",
                (self.member_username,),
            )
            connection.execute("CREATE TABLE chat_room(id INTEGER, owner TEXT)")
            connection.execute(
                "INSERT INTO chat_room VALUES (2, ?)",
                (self.username,),
            )
            connection.execute("CREATE TABLE chatroom_member(room_id INTEGER, member_id INTEGER)")
            connection.executemany(
                "INSERT INTO chatroom_member VALUES (2, ?)",
                [(1,), (3,)],
            )
            connection.commit()
        finally:
            connection.close()

        connection = sqlite3.connect(self.decrypted / "session/session.db")
        try:
            connection.execute(
                "CREATE TABLE SessionTable(username TEXT, unread_count INTEGER, summary TEXT, "
                "last_timestamp INTEGER, last_msg_type INTEGER, last_msg_sender TEXT, "
                "last_sender_display_name TEXT)"
            )
            connection.execute(
                "INSERT INTO SessionTable VALUES (?, 1, 'fixture hello', ?, 1, ?, 'Fixture Friend')",
                (self.username, self.timestamp, self.username),
            )
            connection.execute(
                "INSERT INTO SessionTable VALUES (?, 2, 'group fixture hello', ?, 1, ?, 'Fixture Friend')",
                (self.group_username, self.timestamp, self.username),
            )
            connection.commit()
        finally:
            connection.close()

        table = "Msg_" + hashlib.md5(self.username.encode()).hexdigest()
        group_table = "Msg_" + hashlib.md5(self.group_username.encode()).hexdigest()
        connection = sqlite3.connect(self.decrypted / "message/message_0.db")
        try:
            connection.execute("CREATE TABLE Name2Id(user_name TEXT)")
            connection.execute("INSERT INTO Name2Id(rowid, user_name) VALUES (1, ?)", (self.username,))
            connection.execute(
                "INSERT INTO Name2Id(rowid, user_name) VALUES (2, ?)", (self.member_username,)
            )
            connection.execute(
                f"CREATE TABLE [{table}](local_id INTEGER, server_id INTEGER, local_type INTEGER, "
                "create_time INTEGER, real_sender_id INTEGER, message_content TEXT)"
            )
            connection.execute(
                f"INSERT INTO [{table}] VALUES (1, 10, 1, ?, 2, 'fixture hello')",
                (self.timestamp,),
            )
            connection.execute(
                f"CREATE TABLE [{group_table}](local_id INTEGER, server_id INTEGER, local_type INTEGER, "
                "create_time INTEGER, real_sender_id INTEGER, message_content TEXT)"
            )
            connection.execute(
                f"INSERT INTO [{group_table}] VALUES (2, 20, 1, ?, 1, 'group fixture hello')",
                (self.timestamp,),
            )
            connection.commit()
        finally:
            connection.close()

        connection = sqlite3.connect(self.decrypted / "favorite/favorite.db")
        try:
            connection.execute(
                "CREATE TABLE fav_db_item(local_id INTEGER, type INTEGER, update_time INTEGER, "
                "content TEXT, fromusr TEXT, realchatname TEXT)"
            )
            favorite_xml = (
                "<favitem><pagetitle>Fixture Article</pagetitle>"
                "<pagedesc>fixture favorite</pagedesc></favitem>"
            )
            connection.execute(
                "INSERT INTO fav_db_item VALUES (1, 5, ?, ?, ?, ?)",
                (self.timestamp, favorite_xml, self.username, self.group_username),
            )
            connection.commit()
        finally:
            connection.close()

        connection = sqlite3.connect(self.decrypted / "sns/sns.db")
        try:
            connection.execute("CREATE TABLE SnsTimeLine(tid TEXT, user_name TEXT, content TEXT)")
            moment_xml = (
                "<TimelineObject><username>fixture-user</username><nickname>Fixture Nick</nickname>"
                f"<createTime>{self.timestamp}</createTime><contentDesc>fixture moment</contentDesc>"
                "<ContentObject><contentStyle>1</contentStyle></ContentObject></TimelineObject>"
            )
            connection.execute(
                "INSERT INTO SnsTimeLine VALUES ('moment-1', ?, ?)",
                (self.username, moment_xml),
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(self.local_app_data)
        return subprocess.run(
            [sys.executable, str(CLI), "--decrypted-dir", str(self.decrypted), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )

    def test_contacts_sessions_history_and_search(self) -> None:
        contacts = self.run_cli("contacts", "--query", "Friend", "--format", "json")
        self.assertEqual(contacts.returncode, 0, contacts.stderr)
        self.assertEqual(json.loads(contacts.stdout)["count"], 1)

        sessions = self.run_cli("sessions", "--format", "json")
        self.assertEqual(sessions.returncode, 0, sessions.stderr)
        self.assertEqual(json.loads(sessions.stdout)[0]["last_message"], "fixture hello")

        history = self.run_cli("history", "Fixture Friend", "--format", "json")
        self.assertEqual(history.returncode, 0, history.stderr)
        self.assertEqual(json.loads(history.stdout)["messages"][0]["content"], "fixture hello")

        search = self.run_cli(
            "search", "fixture", "--chat", "Fixture Friend", "--format", "json"
        )
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertEqual(json.loads(search.stdout)["count"], 1)

    def test_markdown_export(self) -> None:
        output = Path(self.temporary.name) / "fixture-export.md"
        result = self.run_cli(
            "export",
            "Fixture Friend",
            "--output",
            str(output),
            "--format",
            "markdown",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file())
        self.assertIn("fixture hello", output.read_text(encoding="utf-8"))

        refused = self.run_cli(
            "export", "Fixture Friend", "--output", str(output), "--format", "markdown"
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--overwrite", refused.stderr)
        replaced = self.run_cli(
            "export",
            "Fixture Friend",
            "--output",
            str(output),
            "--format",
            "markdown",
            "--overwrite",
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)

    def test_remaining_mac_equivalent_commands(self) -> None:
        status = self.run_cli("status", "--format", "json")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertTrue(json.loads(status.stdout)["exists"])

        unread = self.run_cli("unread", "--format", "json")
        self.assertEqual(unread.returncode, 0, unread.stderr)
        self.assertEqual(len(json.loads(unread.stdout)), 2)

        first_new = self.run_cli("new-messages", "--format", "json")
        self.assertEqual(first_new.returncode, 0, first_new.stderr)
        self.assertTrue(json.loads(first_new.stdout)["first_call"])
        second_new = self.run_cli("new-messages", "--format", "json")
        self.assertEqual(second_new.returncode, 0, second_new.stderr)
        self.assertEqual(json.loads(second_new.stdout)["new_count"], 0)

        members = self.run_cli("members", "Fixture Group", "--format", "json")
        self.assertEqual(members.returncode, 0, members.stderr)
        self.assertEqual(json.loads(members.stdout)["member_count"], 2)

        stats = self.run_cli("stats", "Fixture Group", "--format", "json")
        self.assertEqual(stats.returncode, 0, stats.stderr)
        self.assertEqual(json.loads(stats.stdout)["total"], 1)

        digest_root = Path(self.temporary.name) / "digests"
        digest = self.run_cli(
            "digest-source",
            "Fixture Group",
            "--data-root",
            str(digest_root),
            "--format",
            "json",
        )
        self.assertEqual(digest.returncode, 0, digest.stderr)
        digest_payload = json.loads(digest.stdout)
        self.assertEqual(digest_payload["message_count"], 1)
        self.assertTrue(Path(digest_payload["source_json"]).is_file())

        favorite = self.run_cli(
            "favorites", "--type", "article", "--query", "Fixture", "--format", "json"
        )
        self.assertEqual(favorite.returncode, 0, favorite.stderr)
        self.assertEqual(json.loads(favorite.stdout)["count"], 1)

        moment = self.run_cli(
            "moments", "--name", "Fixture Friend", "--keyword", "fixture", "--format", "json"
        )
        self.assertEqual(moment.returncode, 0, moment.stderr)
        self.assertEqual(json.loads(moment.stdout)["moments"][0]["content"], "fixture moment")

    def test_command_surface_matches_repository_mac_skill(self) -> None:
        def commands(path: Path) -> set[str]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return {
                node.args[0].value
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            }

        mac_cli = ROOT.parent / "yichen-wechat-local-vault/scripts/vault_cli.py"
        self.assertEqual(commands(CLI), commands(mac_cli))

    def test_snapshot_connection_enforces_read_only_mode(self) -> None:
        with vault_cli.connect(self.decrypted / "contact/contact.db") as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden_write(value TEXT)")


if __name__ == "__main__":
    unittest.main()
