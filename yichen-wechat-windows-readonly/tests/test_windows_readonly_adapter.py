from __future__ import annotations

import ast
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "windows_readonly_adapter.py"
FIXTURE_DIR = SKILL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(FIXTURE_DIR))
adapter = importlib.import_module("windows_readonly_adapter")
fixture_builder = importlib.import_module("build_synthetic_vault")


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="readonly-adapter-tests-")
        self.root = Path(self.temporary.name)
        self.vault = self.root / "vault"
        fixture_builder.build(self.vault)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(
        self,
        *arguments: str,
        consent: bool = False,
        root: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        selected_root = root or self.vault
        command = [sys.executable, str(SCRIPT), "--vault-root", str(selected_root)]
        if consent:
            command.append("--allow-private-content")
        command.extend(arguments)
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        payload = json.loads(completed.stdout)
        combined = completed.stdout + completed.stderr
        self.assertNotIn(str(selected_root), combined)
        return completed, payload

    def contact_id(self, display_name: str) -> str:
        completed, payload = self.run_cli("contacts", consent=True)
        self.assertEqual(0, completed.returncode)
        return next(
            item["contact_id"]
            for item in payload["result"]["contacts"]
            if item["display_name"] == display_name
        )

    def test_vault_root_is_required_and_must_be_absolute(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(SCRIPT), "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(2, missing.returncode)
        relative = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault-root", "relative-vault", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(3, relative.returncode)
        self.assertEqual("invalid_vault_root", json.loads(relative.stdout)["error"]["code"])

    def test_status_is_metadata_only_and_redacted(self) -> None:
        completed, payload = self.run_cli("status")
        self.assertEqual(0, completed.returncode)
        result = payload["result"]
        self.assertTrue(result["metadata_only"])
        self.assertTrue(result["contacts"]["healthy"])
        self.assertTrue(result["sessions"]["healthy"])
        self.assertEqual(1, result["messages"]["healthy_count"])
        output = completed.stdout
        self.assertNotIn("synthetic_casey", output)
        self.assertNotIn("Quarterly review", output)

    def test_every_content_command_requires_current_invocation_consent(self) -> None:
        commands = (
            ("contacts",),
            ("sessions",),
            ("history", "Casey"),
            ("search", "review"),
            ("stats", "Casey"),
        )
        for command in commands:
            with self.subTest(command=command[0]):
                completed, payload = self.run_cli(*command)
                self.assertEqual(3, completed.returncode)
                self.assertEqual("consent_required", payload["error"]["code"])

    def test_contacts_use_opaque_ids_and_ambiguous_names_fail(self) -> None:
        completed, payload = self.run_cli("contacts", consent=True)
        self.assertEqual(0, completed.returncode)
        self.assertEqual(5, payload["result"]["count"])
        self.assertTrue(all(item["contact_id"].startswith("contact-") for item in payload["result"]["contacts"]))
        self.assertNotIn("synthetic_", completed.stdout)

        ambiguous, error = self.run_cli("history", "Alex", consent=True)
        self.assertEqual(3, ambiguous.returncode)
        self.assertEqual("ambiguous_contact", error["error"]["code"])
        self.assertEqual(2, len(error["error"]["details"]["candidates"]))
        self.assertNotIn("synthetic_alex", ambiguous.stdout)

    def test_sessions_history_search_and_stats_are_read_only_and_redacted(self) -> None:
        sessions, sessions_payload = self.run_cli("sessions", consent=True)
        self.assertEqual(0, sessions.returncode)
        self.assertEqual(2, sessions_payload["result"]["count"])
        self.assertNotIn("synthetic_", sessions.stdout)
        self.assertIn("Draft approved", sessions.stdout)

        casey_id = self.contact_id("Casey")
        history, history_payload = self.run_cli("history", casey_id, consent=True)
        self.assertEqual(0, history.returncode)
        self.assertEqual(2, history_payload["result"]["count"])
        self.assertEqual(
            ["Quarterly review starts Monday", "Quarterly review is ready"],
            [item["content"] for item in history_payload["result"]["messages"]],
        )
        self.assertNotIn("synthetic_casey", history.stdout)

        search, search_payload = self.run_cli("search", "review", consent=True)
        self.assertEqual(0, search.returncode)
        self.assertEqual(2, search_payload["result"]["count"])
        self.assertNotIn("synthetic_casey", search.stdout)

        stats, stats_payload = self.run_cli("stats", "Project Lantern", consent=True)
        self.assertEqual(0, stats.returncode)
        self.assertEqual(2, stats_payload["result"]["total"])
        self.assertEqual({"image": 1, "text": 1}, stats_payload["result"]["type_breakdown"])
        self.assertNotIn("synthetic_morgan", stats.stdout)

    def test_non_text_payload_is_never_returned(self) -> None:
        completed, payload = self.run_cli("history", "Project Lantern", consent=True)
        self.assertEqual(0, completed.returncode)
        messages = payload["result"]["messages"]
        image = next(item for item in messages if item["message_type"] == "image")
        self.assertIsNone(image["content"])
        self.assertTrue(image["content_omitted"])
        self.assertNotIn("must-not-leak", completed.stdout)

    def test_corruption_fails_closed_without_cached_results(self) -> None:
        first, first_payload = self.run_cli("contacts", consent=True)
        self.assertEqual(0, first.returncode)
        self.assertGreater(first_payload["result"]["count"], 0)

        contact_db = self.vault / "contact" / "contact.db"
        contact_db.write_bytes(b"not a sqlite database")
        second, second_payload = self.run_cli("contacts", consent=True)
        self.assertEqual(3, second.returncode)
        self.assertEqual("corrupt_database", second_payload["error"]["code"])
        self.assertNotIn("Casey", second.stdout)

        status, status_payload = self.run_cli("status")
        self.assertEqual(0, status.returncode)
        self.assertFalse(status_payload["result"]["contacts"]["healthy"])

    def test_wrong_root_and_unsupported_schema_fail_without_path_disclosure(self) -> None:
        missing_root = self.root / "private-owner-name" / "missing-vault"
        completed, payload = self.run_cli("status", root=missing_root)
        self.assertEqual(3, completed.returncode)
        self.assertEqual("invalid_vault_root", payload["error"]["code"])
        self.assertNotIn("private-owner-name", completed.stdout + completed.stderr)

        unsupported = self.root / "unsupported"
        (unsupported / "contact").mkdir(parents=True)
        with closing(sqlite3.connect(unsupported / "contact" / "contact.db")) as connection, connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        failed, failed_payload = self.run_cli("contacts", consent=True, root=unsupported)
        self.assertEqual(3, failed.returncode)
        self.assertEqual("unsupported_schema", failed_payload["error"]["code"])

    def test_source_files_are_not_modified_or_given_sidecars(self) -> None:
        contact_dir = self.vault / "contact"

        def state() -> dict[str, tuple[int, int]]:
            return {
                item.name: (item.stat().st_size, item.stat().st_mtime_ns)
                for item in contact_dir.iterdir()
            }

        before = state()
        completed, _ = self.run_cli("contacts", consent=True)
        self.assertEqual(0, completed.returncode)
        self.assertEqual(before, state())

    def test_wal_commits_are_visible_without_source_writes(self) -> None:
        contact_db = self.vault / "contact" / "contact.db"
        connection = sqlite3.connect(contact_db)
        try:
            self.assertEqual("wal", connection.execute("PRAGMA journal_mode=WAL").fetchone()[0])
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute(
                """
                INSERT INTO contact (id, username, nick_name, remark, alias, description)
                VALUES (6, 'synthetic_taylor', 'Taylor', 'Taylor', 'taylor', '')
                """
            )
            connection.commit()
            wal = Path(f"{contact_db}-wal")
            self.assertTrue(wal.exists())

            def source_state() -> dict[str, tuple[int, int]]:
                return {
                    item.name: (item.stat().st_size, item.stat().st_mtime_ns)
                    for item in contact_db.parent.iterdir()
                }

            before = source_state()
            completed, payload = self.run_cli("contacts", consent=True)
            self.assertEqual(0, completed.returncode)
            self.assertIn("Taylor", [item["display_name"] for item in payload["result"]["contacts"]])
            self.assertEqual(before, source_state())
        finally:
            connection.close()

    def test_concurrent_source_change_fails_closed(self) -> None:
        root = adapter.resolve_vault_root(str(self.vault))
        source = adapter._validate_database(root, Path("contact/contact.db"))
        original_copy = adapter.shutil.copyfile
        changed = False

        def changing_copy(source_value: str | os.PathLike, destination_value: str | os.PathLike):
            nonlocal changed
            result = original_copy(source_value, destination_value)
            if Path(source_value) == source and not changed:
                changed = True
                with source.open("ab") as handle:
                    handle.write(b"changed-during-snapshot")
            return result

        with mock.patch.object(adapter.shutil, "copyfile", side_effect=changing_copy):
            with self.assertRaises(adapter.AdapterError) as raised:
                with adapter.snapshot_databases([source]):
                    self.fail("an unstable source must not yield a snapshot")
        self.assertEqual("source_changed", raised.exception.code)

    def test_reparse_points_are_rejected(self) -> None:
        with mock.patch.object(adapter, "_is_reparse_point", side_effect=lambda path: path == self.vault):
            with self.assertRaises(adapter.AdapterError) as raised:
                adapter.resolve_vault_root(str(self.vault))
        self.assertEqual("reparse_point_rejected", raised.exception.code)

    def test_implementation_uses_only_standard_library_and_no_prohibited_runtime(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertTrue(imported.issubset(sys.stdlib_module_names))
        lowered = source.casefold()
        for prohibited in (
            "frida",
            "jackwener",
            "wx-cli",
            "openprocess",
            "writeprocessmemory",
            "virtualallocex",
            "create_remote_thread",
            "ctypes",
            "win32api",
            "psutil",
            "requests",
            "subprocess",
            "socket",
        ):
            self.assertNotIn(prohibited, lowered)


if __name__ == "__main__":
    unittest.main()
