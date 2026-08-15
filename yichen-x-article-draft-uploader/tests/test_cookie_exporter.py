from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_x_cookies_from_chrome.py"
SPEC = importlib.util.spec_from_file_location("x_cookie_exporter", SCRIPT)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class CookieExporterTests(unittest.TestCase):
    def test_export_domains_are_fixed_to_x(self) -> None:
        self.assertEqual(
            exporter.validate_export_domains(["twitter.com", ".x.com"]),
            exporter.ALLOWED_COOKIE_DOMAINS,
        )
        with self.assertRaisesRegex(ValueError, "restricted to x.com and twitter.com"):
            exporter.validate_export_domains(["x.com", "example.com"])

    def test_domain_matching_is_label_bound(self) -> None:
        self.assertTrue(exporter.host_matches_domain(".x.com", "x.com"))
        self.assertTrue(exporter.host_matches_domain("api.x.com", "x.com"))
        self.assertFalse(exporter.host_matches_domain("notx.com", "x.com"))
        self.assertFalse(exporter.host_matches_domain("x.com.example.org", "x.com"))

    def test_private_writer_is_atomic_and_sets_mode_0600(self) -> None:
        cookies = [{"name": "sentinel", "value": "synthetic", "domain": ".x.com"}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cookies.json"
            exporter.write_private_cookie_json(output, cookies)

            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), cookies)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(list(output.parent.glob(f".{output.name}.stage-*")), [])


if __name__ == "__main__":
    unittest.main()
