"""Fixture-only integration checks; no real vault/configuration is accessed."""

from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import vault_cli
import snapshot_reader
from fixture_factory import build, GROUP

ARTIFACT_ROOT = Path(os.environ.get("YICHEN_WECHAT_TEST_ROOT") or tempfile.mkdtemp(prefix="wechat-integration-tests-")).resolve()


def invoke(module, argv, *, forbid_config=False):
    stdout, stderr = io.StringIO(), io.StringIO()
    configuration = mock.patch.object(module, "load_config", side_effect=AssertionError("Mac configuration accessed")) if forbid_config else mock.patch.object(module, "load_config", return_value={})
    with configuration, redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = module.main(argv) or 0
        except SystemExit as exc:
            code = exc.code
    return code, stdout.getvalue(), stderr.getvalue()


def fingerprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


class UnifiedVaultTests(unittest.TestCase):
    def setUp(self):
        self.case = ARTIFACT_ROOT / (self._testMethodName + "-" + uuid.uuid4().hex)
        self.case.mkdir(parents=True)
        self.snapshot = self.case / "snapshot"
        self.fixture = build(self.snapshot)

    def routed(self, *arguments):
        return invoke(vault_cli, ["snapshot", "--snapshot", str(self.snapshot), *arguments], forbid_config=True)

    def test_root_help_exposes_snapshot_without_reading_configuration(self):
        code, out, _ = invoke(vault_cli, ["--help"], forbid_config=True)
        self.assertEqual(code, 0)
        self.assertIn("snapshot", out)

    def test_snapshot_help_preserves_required_path(self):
        code, out, _ = invoke(vault_cli, ["snapshot", "--help"], forbid_config=True)
        self.assertEqual(code, 0)
        self.assertIn("--snapshot", out)
        self.assertIn("validate", out)

    def test_routed_validation_history_search_and_export_preserve_inputs(self):
        before = fingerprint(self.snapshot)
        with mock.patch.object(vault_cli, "command_history", side_effect=AssertionError("Mac backend entered")):
            code, out, err = self.routed("validate")
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["valid"])
            code, out, err = self.routed("chats", "--query", "测试群")
            self.assertEqual(code, 0, err)
            chat_id = json.loads(out)["chats"][0]["chat_id"]
            self.assertEqual(chat_id, self.fixture["group_id"])
            code, out, err = self.routed("history", chat_id)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["messages"]), 3)
            code, out, err = self.routed("search", chat_id, "星河")
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["messages"]), 1)
            destination = self.case / "export.md"
            code, _, err = self.routed("export", chat_id, "--output", str(destination), "--confirm-external-output")
            self.assertEqual(code, 0, err)
            self.assertIn("星河", destination.read_text())
        self.assertEqual(fingerprint(self.snapshot), before)

    def test_missing_snapshot_or_manifest_never_falls_back_to_mac(self):
        code, _, _ = invoke(vault_cli, ["snapshot", "validate"], forbid_config=True)
        self.assertEqual(code, 2)
        incomplete = self.case / "incomplete"
        build(incomplete, include_manifest=False)
        code, out, _ = invoke(vault_cli, ["snapshot", "--snapshot", str(incomplete), "validate"], forbid_config=True)
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["valid"])

    def test_rejected_snapshot_errors_reach_unified_cli_exit_code(self):
        (self.snapshot / "message/message_0.db-wal").write_bytes(b"synthetic WAL")
        code, _, err = self.routed("history", self.fixture["group_id"])
        self.assertEqual(code, 2)
        self.assertIn("sidecar", err)

    def test_export_outside_default_still_requires_explicit_flag(self):
        destination = self.case / "denied.md"
        code, _, err = self.routed("export", self.fixture["group_id"], "--output", str(destination))
        self.assertEqual(code, 2)
        self.assertIn("--confirm-external-output", err)
        self.assertFalse(destination.exists())

    def test_mac_directory_and_snapshot_mode_cannot_be_combined(self):
        code, _, _ = invoke(vault_cli, ["--decrypted-dir", str(self.snapshot), "snapshot"], forbid_config=True)
        self.assertEqual(code, 2)

    def test_windows_host_does_not_run_mac_workflows(self):
        with mock.patch.object(sys, "platform", "win32"):
            code, _, err = invoke(vault_cli, ["status"], forbid_config=True)
        self.assertEqual(code, 2)
        self.assertIn("snapshot", err)

    def test_real_cli_process_preserves_unicode_and_exit_codes(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        command = [sys.executable, str(ROOT / "scripts/vault_cli.py"), "snapshot", "--snapshot", str(self.snapshot)]
        ok = subprocess.run(command + ["search", self.fixture["group_id"], "星河"], capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("星河", json.loads(ok.stdout)["messages"][0]["content"])
        bad = subprocess.run(command + ["history", "not-an-id"], capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")

    def test_shared_schema_does_not_merge_backend_specific_fallbacks(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        try:
            con.execute("CREATE TABLE [Msg_test](timestamp INTEGER, WCDB_CT_message_content INTEGER)")
            mac = vault_cli.message_columns(con, "Msg_test")
            win = snapshot_reader.table_mapping(con, "Msg_test")
            self.assertEqual(mac["local_id"], "rowid")
            self.assertEqual(mac["compress_content"], "WCDB_CT_message_content")
            self.assertEqual(win["local_id"], "")
            self.assertEqual(win["compressed"], "")
            self.assertFalse(snapshot_reader._compatible_message_mapping(win))
            self.assertEqual(vault_cli.message_table(GROUP), snapshot_reader.message_table(GROUP))
        finally:
            con.close()


@unittest.skipUnless(os.environ.get("WECHAT_VAULT_BASELINE_DIR"), "optional before-integration source comparison")
class MacBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ["WECHAT_VAULT_BASELINE_DIR"]) / "scripts/vault_cli.py"
        spec = importlib.util.spec_from_file_location("before_vault_cli", source)
        cls.before = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.before)
        cls.case = ARTIFACT_ROOT / ("mac-baseline-" + uuid.uuid4().hex)
        cls.case.mkdir(parents=True)
        cls.snapshot = cls.case / "snapshot"
        build(cls.snapshot)

    def test_mac_query_results_match_before_integration(self):
        before = fingerprint(self.snapshot)
        commands = [
            ["contacts", "--query", "客户"],
            ["history", GROUP],
            ["history", GROUP, "--limit", "1", "--type", "text"],
            ["history", GROUP, "--start-time", "2026-03-01", "--end-time", "2026-03-02", "--format", "text"],
            ["search", "普通", "--chat", GROUP],
            ["stats", GROUP],
        ]
        for command in commands:
            with self.subTest(command=command):
                argv = ["--decrypted-dir", str(self.snapshot), *command]
                old = invoke(self.before, argv)
                new = invoke(vault_cli, argv)
                self.assertEqual(old[0], 0)
                self.assertEqual(new, old)
        self.assertEqual(fingerprint(self.snapshot), before)

    def test_mac_export_and_column_aliases_match_before_integration(self):
        old_path, new_path = self.case / "before.md", self.case / "after.md"
        for module, path in [(self.before, old_path), (vault_cli, new_path)]:
            code, _, err = invoke(module, ["--decrypted-dir", str(self.snapshot), "export", GROUP, "--output", str(path)])
            self.assertEqual(code, 0, err)
        self.assertEqual(old_path.read_bytes(), new_path.read_bytes())
        for schema in ["id INTEGER, timestamp INTEGER, sender_id INTEGER, content TEXT", "local_id INTEGER, create_time INTEGER, compress_content BLOB, WCDB_CT_message_content INTEGER", "timestamp INTEGER, WCDB_CT_message_content INTEGER"]:
            with self.subTest(schema=schema):
                con = sqlite3.connect(":memory:")
                con.row_factory = sqlite3.Row
                try:
                    con.execute("CREATE TABLE sample(" + schema + ")")
                    self.assertEqual(self.before.message_columns(con, "sample"), vault_cli.message_columns(con, "sample"))
                finally:
                    con.close()


if __name__ == "__main__":
    unittest.main()
