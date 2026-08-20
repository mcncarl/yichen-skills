from __future__ import annotations

from pathlib import Path

import pytest

import vault_cli
from vault_common import VaultError, require_explicit_dir


def test_explicit_root_required() -> None:
    with pytest.raises(VaultError, match="automatic folder scanning is disabled"):
        require_explicit_dir(None, "--decrypted-root")


def test_status_contacts_sessions_and_members(synthetic_vault: Path) -> None:
    assert vault_cli.command_status(synthetic_vault)["message_shards"] == 1
    assert vault_cli.command_contacts(synthetic_vault, "remark", 10)[0]["username"] == "alice"
    assert vault_cli.command_sessions(synthetic_vault, True, 10)[0]["unread_count"] == 2
    assert vault_cli.command_members(synthetic_vault, "Synthetic Group")["members"][0]["username"] == "alice"


def test_history_search_stats(synthetic_vault: Path) -> None:
    history = vault_cli.collect_messages(synthetic_vault, "Alice", None, None, None, None, 10, 0)
    assert [row["type"] for row in history] == ["image", "text"]
    search = vault_cli.collect_messages(synthetic_vault, None, None, None, "hello", None, 10, 0)
    assert len(search) == 1 and search[0]["content"] == "hello synthetic"
    stats = vault_cli.command_stats(synthetic_vault, "Alice", None, None)
    assert stats["message_count"] == 2
    assert stats["by_type"] == {"image": 1, "text": 1}


def test_favorites_moments_and_export(synthetic_vault: Path, tmp_path: Path) -> None:
    assert vault_cli.command_favorites(synthetic_vault, "synthetic", 10)[0]["type"] == 1
    assert vault_cli.command_moments(synthetic_vault, ["alice"], "synthetic", 10)[0]["text"] == "moment synthetic"
    output = tmp_path / "export.md"
    args = type("Args", (), {"chat":"Alice", "start_time":None, "end_time":None, "type":None, "limit":10, "output":str(output), "export_format":"markdown"})()
    result = vault_cli.export_messages(synthetic_vault, args)
    assert result["message_count"] == 2
    assert "hello synthetic" in output.read_text(encoding="utf-8")


def test_resource_index_and_digest(synthetic_vault: Path, tmp_path: Path) -> None:
    resources = vault_cli.command_resources(synthetic_vault, "Alice", 2, 10)
    assert resources["resources"][0]["size"] == 128
    output = tmp_path / "digest.md"
    args = type("Args", (), {"group":"Alice", "start":None, "end":None, "limit":10, "output":str(output)})()
    result = vault_cli.command_digest(synthetic_vault, args)
    assert result["message_count"] == 2
    assert "hello synthetic" in output.read_text(encoding="utf-8")
