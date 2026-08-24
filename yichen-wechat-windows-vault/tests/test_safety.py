from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import windows_vault  # noqa: E402


class SafetyTests(unittest.TestCase):
    def test_capture_requires_explicit_consent_before_process_access(self) -> None:
        with self.assertRaises(PermissionError):
            windows_vault.capture(
                Path("unused"),
                "all",
                0,
                Path("unused.json"),
                consent=False,
            )

    def test_scripts_contain_no_process_control_or_injection_apis(self) -> None:
        forbidden = (
            "createremotethread",
            "writeprocessmemory",
            "virtualallocex",
            "debugactiveprocess",
            "terminateprocess",
            "suspendthread",
            "resumethread",
            "frida",
            "wx-cli",
            "wx_cli",
        )
        combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in SCRIPTS.glob("*.py"))
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_cli_help_smoke(self) -> None:
        for script in ("windows_vault.py", "vault_cli.py"):
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / script), "--help"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_outputs_cannot_overlap_source_account_tree(self) -> None:
        account = Path("account").resolve()
        with self.assertRaises(ValueError):
            windows_vault.ensure_paths_separate(account / "vault", account, "vault")
        with self.assertRaises(ValueError):
            windows_vault.ensure_paths_separate(account.parent, account, "vault")


if __name__ == "__main__":
    unittest.main()
