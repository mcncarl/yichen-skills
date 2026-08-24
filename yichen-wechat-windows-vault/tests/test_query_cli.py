from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/vault_cli.py"


class QueryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.decrypted = Path(self.temporary.name) / "decrypted"
        (self.decrypted / "contact").mkdir(parents=True)
        (self.decrypted / "session").mkdir(parents=True)
        (self.decrypted / "message").mkdir(parents=True)
        self.username = "fixture-user"
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
            connection.commit()
        finally:
            connection.close()

        table = "Msg_" + hashlib.md5(self.username.encode()).hexdigest()
        connection = sqlite3.connect(self.decrypted / "message/message_0.db")
        try:
            connection.execute(
                f"CREATE TABLE [{table}](local_id INTEGER, server_id INTEGER, local_type INTEGER, "
                "create_time INTEGER, real_sender_id INTEGER, message_content TEXT)"
            )
            connection.execute(
                f"INSERT INTO [{table}] VALUES (1, 10, 1, ?, 2, 'fixture hello')",
                (self.timestamp,),
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "--decrypted-dir", str(self.decrypted), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_contacts_sessions_history_and_search(self) -> None:
        contacts = self.run_cli("contacts", "--query", "Fixture", "--format", "json")
        self.assertEqual(contacts.returncode, 0, contacts.stderr)
        self.assertEqual(json.loads(contacts.stdout)["count"], 1)

        sessions = self.run_cli("sessions", "--format", "json")
        self.assertEqual(sessions.returncode, 0, sessions.stderr)
        self.assertEqual(json.loads(sessions.stdout)[0]["last_message"], "fixture hello")

        history = self.run_cli("history", "Fixture Friend", "--format", "json")
        self.assertEqual(history.returncode, 0, history.stderr)
        self.assertEqual(json.loads(history.stdout)["messages"][0]["content"], "fixture hello")

        search = self.run_cli("search", "fixture", "--format", "json")
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


if __name__ == "__main__":
    unittest.main()
