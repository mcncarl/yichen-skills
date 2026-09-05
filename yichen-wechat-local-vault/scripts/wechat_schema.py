"""Shared message-table vocabulary; acquisition and validation stay in each backend."""

from __future__ import annotations

import hashlib


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def message_columns(available: set[str], *, legacy_mac: bool = False) -> dict[str, str]:
    """Map known column aliases without claiming compatibility with a WeChat version.

    The Mac backend retains its existing rowid and compressed-column fallbacks.
    The snapshot backend independently validates rowids and compression storage.
    """
    choices = {
        "local_id": ("local_id", "id"),
        "server_id": ("server_id",),
        "local_type": ("local_type", "type"),
        "create_time": ("create_time", "timestamp"),
        "real_sender_id": ("real_sender_id", "sender_id"),
        "message_content": ("message_content", "content"),
        "compress_content": ("compress_content",),
        "compression_flag": ("WCDB_CT_message_content",),
    }
    if legacy_mac:
        choices["local_id"] += ("rowid",)
        choices["compress_content"] += ("WCDB_CT_message_content",)
    result = {}
    for key, aliases in choices.items():
        for name in aliases:
            if name in available or (legacy_mac and name == "rowid"):
                result[key] = name
                break
    return result
