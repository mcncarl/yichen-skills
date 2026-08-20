from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_no_excluded_dependency_names() -> None:
    files = list((ROOT / "scripts").glob("*")) + [ROOT / "requirements.txt", ROOT / "requirements-dev.txt"]
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in files if path.is_file()
    ).casefold()
    assert "wx-cli" not in text
    assert "wxcli" not in text
    assert "jackwener" not in text


def test_repository_files_have_no_personal_absolute_paths() -> None:
    candidates = [path for path in ROOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in candidates)
    assert not re.search(r"C:\\Users\\\d{5,}", text, re.IGNORECASE)
    assert not re.search(r"qq\d{6,}", text, re.IGNORECASE)
