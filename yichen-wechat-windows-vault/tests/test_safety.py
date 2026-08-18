"""Offline safety tests; no WeChat process, key, or user database is accessed."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

class PrivateStorageTests(unittest.TestCase):
    def test_digest_source_defaults_to_private_vault_directory(self):
        from vault_cli import DEFAULT_VAULT_DIR, resolve_digest_data_root

        self.assertEqual(resolve_digest_data_root(), DEFAULT_VAULT_DIR / "digests")
        self.assertNotEqual(resolve_digest_data_root(), Path.cwd() / "wechat")


class KeyBindingTests(unittest.TestCase):
    def test_keys_for_other_database_root_are_not_reused(self):
        from vault_common import keys_for_db_root

        existing = {
            "contact/contact.db": {"enc_key": "00" * 32, "salt": "11" * 16},
            "_db_dir": "C:/Users/example/Documents/xwechat_files/old/db_storage",
        }
        selected = keys_for_db_root(existing, Path("C:/Users/example/Documents/xwechat_files/new/db_storage"))
        self.assertEqual(selected, {})

    def test_keys_for_same_database_root_are_reused(self):
        from vault_common import keys_for_db_root

        root = Path("C:/Users/example/Documents/xwechat_files/current/db_storage")
        existing = {
            "contact/contact.db": {"enc_key": "00" * 32, "salt": "11" * 16},
            "_db_dir": str(root),
        }
        self.assertEqual(keys_for_db_root(existing, root), {"contact/contact.db": existing["contact/contact.db"]})


class DocumentationSafetyTests(unittest.TestCase):
    def test_repository_indexes_do_not_promise_that_mcp_results_never_leave_the_machine(self):
        english = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (REPOSITORY_ROOT / "README.zh.md").read_text(encoding="utf-8")
        self.assertNotIn("without uploading it", english)
        self.assertIn("MCP client", english)
        self.assertIn("MCP 客户端", chinese)

    def test_readme_uses_powershell_environment_syntax_and_discloses_mcp_boundary(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("$env:LOCALAPPDATA", text)
        self.assertNotIn('"%LOCALAPPDATA%', text)
        self.assertIn("MCP 客户端可能", text)
        self.assertIn("调用前确认", text)

    def test_skill_requires_explicit_consent_before_returning_private_content(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("explicitly consents", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
