import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SkillPackageTests(unittest.TestCase):
    def test_required_public_package_files_exist(self):
        for relative_path in (
            "SKILL.md",
            "agents/openai.yaml",
            "requirements.txt",
            "pyproject.toml",
            "uv.lock",
            "LICENSE",
            "NOTICE",
            "THIRD_PARTY_NOTICES.md",
            "scripts/doctor.py",
            "scripts/version.py",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_skill_body_is_concise_and_has_only_supported_frontmatter(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 500)
        frontmatter = text.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line
        }
        self.assertEqual({"name", "description"}, keys)

    def test_release_version_is_consistent(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version_module = (ROOT / "scripts/version.py").read_text(encoding="utf-8")
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        project_version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
        module_version = re.search(r'^__version__ = "([^"]+)"$', version_module, re.MULTILINE)

        self.assertIsNotNone(project_version)
        self.assertIsNotNone(module_version)
        self.assertEqual(project_version.group(1), module_version.group(1))
        self.assertIn(project_version.group(1), notice)

    def test_locked_runtime_dependencies_match_pyproject(self):
        requirements = {
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        for requirement in requirements:
            self.assertIn(f'"{requirement}"', pyproject)

    def test_release_uses_apache_2_license(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn('license = "Apache-2.0"', pyproject)
        self.assertIn("Apache License, Version 2.0", notice)

    def test_public_package_contains_no_runtime_secrets_or_generated_media(self):
        forbidden_names = {
            "policy.json",
            "storage-state.json",
            "storage_state.json",
            "视频.mp4",
            "中文口播稿.txt",
        }
        for path in ROOT.rglob("*"):
            self.assertNotIn(path.name, forbidden_names)
            self.assertNotEqual(path.suffix, ".pyc")


if __name__ == "__main__":
    unittest.main()
