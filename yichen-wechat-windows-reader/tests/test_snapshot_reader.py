from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from fixture_factory import build

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/snapshot_reader.py"
SPEC = importlib.util.spec_from_file_location("snapshot_reader", CLI)
reader = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(reader)


class SnapshotReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "snapshot"
        self.fixture = build(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), "--snapshot", str(self.root), *args], capture_output=True, text=True)

    def test_complete_contract_and_both_message_families(self):
        report = reader.validate_snapshot(self.root)
        self.assertTrue(report["valid"], report)
        result = self.run_cli("search", self.fixture["group_id"], "星河")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([item["message_id"] for item in data["messages"]], ["103"])

    def test_missing_required_database_fails_closed(self):
        (self.root / "sns/sns.db").unlink()
        result = self.run_cli("history", self.fixture["group_id"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("sns/sns.db", result.stderr)

    def test_input_is_opened_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.db")}
        result = self.run_cli("history", self.fixture["group_id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.db")})
        self.assertFalse(list(self.root.rglob("*-journal")))
        self.assertFalse(list(self.root.rglob("*.db-wal")))

    def test_no_internal_identity_in_output_and_direction_is_manifest_based(self):
        result = self.run_cli("history", self.fixture["group_id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("wxid_", result.stdout)
        messages = json.loads(result.stdout)["messages"]
        self.assertEqual([m["direction"] for m in messages], ["incoming", "outgoing", "unknown"])

    def test_no_manifest_means_unknown_not_guessed(self):
        (self.root / "snapshot-manifest.json").unlink()
        messages = json.loads(self.run_cli("history", self.fixture["group_id"]).stdout)["messages"]
        self.assertEqual({m["direction"] for m in messages}, {"unknown"})

    def test_external_export_needs_separate_confirmation(self):
        outside = Path(self.temp.name) / "report.md"
        denied = self.run_cli("export", self.fixture["group_id"], "--output", str(outside))
        self.assertEqual(denied.returncode, 2)
        allowed = self.run_cli("export", self.fixture["group_id"], "--output", str(outside), "--confirm-external-output")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertTrue(outside.is_file())

    def test_duplicate_display_names_are_listed_not_resolved(self):
        result = self.run_cli("chats", "--query", "客户")
        items = json.loads(result.stdout)
        self.assertEqual(len(items), 2)
        self.assertEqual(len({item["chat_id"] for item in items}), 2)
        rejected = self.run_cli("history", "客户甲")
        self.assertEqual(rejected.returncode, 2)

    def test_sqlite_authorizer_rejects_writes(self):
        with reader.connect_read_only(self.root / "contact/contact.db") as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM contact")

    def test_production_tree_has_no_extraction_or_decryption_modules(self):
        scripts = {path.name for path in (ROOT / "scripts").glob("*.py")}
        self.assertEqual(scripts, {"snapshot_reader.py"})
        source = CLI.read_text(encoding="utf-8").casefold()
        for forbidden in ("openprocess", "readprocessmemory", "dpapi", "sqlcipher", "frida", "wx-cli"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
