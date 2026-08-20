#!/usr/bin/env python3
"""Build a fictional, already-decrypted Vault for local tests."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path


CONTACTS = (
    (1, "synthetic_alex_one", "Alex", "Alex", "alex-one"),
    (2, "synthetic_alex_two", "Alex", "Alex", "alex-two"),
    (3, "synthetic_casey", "Casey", "Casey", "casey"),
    (4, "synthetic_project@chatroom", "Project Lantern", "Project Lantern", ""),
    (5, "synthetic_morgan", "Morgan", "Morgan", "morgan"),
)


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def create_contact_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE contact (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                nick_name TEXT,
                remark TEXT,
                alias TEXT,
                description TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO contact (id, username, nick_name, remark, alias, description) VALUES (?, ?, ?, ?, ?, '')",
            CONTACTS,
        )


def create_session_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE SessionTable (
                username TEXT NOT NULL,
                unread_count INTEGER NOT NULL,
                summary TEXT,
                last_timestamp INTEGER NOT NULL,
                last_msg_type INTEGER NOT NULL,
                last_msg_sender TEXT,
                last_sender_display_name TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO SessionTable (
                username, unread_count, summary, last_timestamp,
                last_msg_type, last_msg_sender, last_sender_display_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ("synthetic_casey", 1, "Quarterly review is ready", 1735689720, 1, "synthetic_casey", "Casey"),
                (
                    "synthetic_project@chatroom",
                    0,
                    "synthetic_morgan:\nDraft approved",
                    1735689840,
                    1,
                    "synthetic_morgan",
                    "Morgan",
                ),
            ),
        )


def create_message_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE Name2Id (user_name TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)",
            ((3, "synthetic_casey"), (5, "synthetic_morgan")),
        )

        for username in ("synthetic_casey", "synthetic_project@chatroom"):
            table = message_table(username)
            connection.execute(
                f"""
                CREATE TABLE [{table}] (
                    local_id INTEGER PRIMARY KEY,
                    server_id INTEGER,
                    local_type INTEGER NOT NULL,
                    create_time INTEGER NOT NULL,
                    real_sender_id INTEGER,
                    message_content TEXT,
                    compress_content BLOB,
                    WCDB_CT_message_content INTEGER
                )
                """
            )

        direct_table = message_table("synthetic_casey")
        connection.executemany(
            f"""
            INSERT INTO [{direct_table}] (
                local_id, server_id, local_type, create_time,
                real_sender_id, message_content, compress_content,
                WCDB_CT_message_content
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
            """,
            (
                (1, 101, 1, 1735689600, 3, "Quarterly review starts Monday",),
                (2, 102, 1, 1735689720, 3, "Quarterly review is ready",),
            ),
        )

        group_table = message_table("synthetic_project@chatroom")
        connection.executemany(
            f"""
            INSERT INTO [{group_table}] (
                local_id, server_id, local_type, create_time,
                real_sender_id, message_content, compress_content,
                WCDB_CT_message_content
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
            """,
            (
                (3, 103, 1, 1735689780, 5, "synthetic_morgan:\nDraft is ready",),
                (4, 104, 3, 1735689840, 5, "<synthetic-image-payload>must-not-leak</synthetic-image-payload>",),
            ),
        )


def build(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    contact_dir = output / "contact"
    session_dir = output / "session"
    message_dir = output / "message"
    contact_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    message_dir.mkdir(parents=True, exist_ok=True)
    create_contact_database(contact_dir / "contact.db")
    create_session_database(session_dir / "session.db")
    create_message_database(message_dir / "message_0.db")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.output.resolve())
    print("Synthetic Vault created.")


if __name__ == "__main__":
    main()
