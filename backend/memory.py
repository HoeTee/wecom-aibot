from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "memory.sqlite3"

DOC_ID_PATTERN = re.compile(r'(?i)(?:docid|doc_id)\b["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]+)')
DOC_NAME_PATTERN = re.compile(r'(?i)(?:doc_name|docname)\b["\']?\s*[:=]\s*["\']?([^\n,"\'}]+)')
DOC_URL_PATTERN = re.compile(r"(https?://[^\s'\"]+)")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _short_text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _find_first_value(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_with_pattern(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text or "")
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_json TEXT NOT NULL,
                result_excerpt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS session_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                doc_url TEXT,
                doc_name TEXT,
                last_tool_name TEXT NOT NULL,
                last_user_text TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, doc_id)
            );
            """
        )
        conn.commit()


def build_session_id(chat_type: str, chat_id: str | None, user_id: str) -> str:
    chat_type = str(chat_type or "").strip().lower()
    chat_id = str(chat_id or "").strip()
    user_id = str(user_id or "").strip()

    if chat_type == "group" and chat_id:
        return f"group:{chat_id}"
    if user_id:
        return f"dm:{user_id}"
    if chat_id:
        return f"chat:{chat_id}"
    return "anonymous"


def save_turn(session_id: str, role: str, content: str) -> None:
    session_id = str(session_id or "").strip()
    role = str(role or "").strip()
    content = str(content or "").strip()
    if not session_id or not role or not content:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_turns (session_id, role, content)
            VALUES (?, ?, ?)
            """,
            (session_id, role, content),
        )
        conn.commit()


def save_tool_call(session_id: str, tool_name: str, args_dict: dict[str, Any], result_text: str) -> None:
    session_id = str(session_id or "").strip()
    tool_name = str(tool_name or "").strip()
    if not session_id or not tool_name:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tool_calls (session_id, tool_name, args_json, result_excerpt)
            VALUES (?, ?, ?, ?)
            """,
            (
                session_id,
                tool_name,
                _short_text(_json_dumps(args_dict)),
                _short_text(result_text),
            ),
        )
        conn.commit()


def extract_doc_binding(tool_name: str, args_dict: dict[str, Any], result_text: str) -> dict[str, str | None] | None:
    doc_id = _find_first_value(args_dict, ("docid", "doc_id", "docId"))
    doc_url = _find_first_value(args_dict, ("docurl", "doc_url", "docUrl"))
    doc_name = _find_first_value(args_dict, ("doc_name", "docName", "docname", "doc_name_or_title"))

    if not doc_id:
        doc_id = _extract_with_pattern(DOC_ID_PATTERN, result_text)
    if not doc_url:
        doc_url = _extract_with_pattern(DOC_URL_PATTERN, result_text)
    if not doc_name:
        doc_name = _extract_with_pattern(DOC_NAME_PATTERN, result_text)

    if not doc_id:
        return None

    if tool_name.endswith("create_doc") and not doc_name:
        doc_name = _find_first_value(args_dict, ("doc_name", "name", "title"))

    return {
        "doc_id": doc_id,
        "doc_url": doc_url,
        "doc_name": doc_name,
    }


def upsert_session_doc(
    session_id: str,
    doc_id: str,
    doc_url: str | None,
    doc_name: str | None,
    last_tool_name: str,
    last_user_text: str,
) -> None:
    session_id = str(session_id or "").strip()
    doc_id = str(doc_id or "").strip()
    last_tool_name = str(last_tool_name or "").strip()
    last_user_text = str(last_user_text or "").strip()
    if not session_id or not doc_id or not last_tool_name:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO session_docs (
                session_id,
                doc_id,
                doc_url,
                doc_name,
                last_tool_name,
                last_user_text
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, doc_id) DO UPDATE SET
                doc_url = COALESCE(excluded.doc_url, session_docs.doc_url),
                doc_name = COALESCE(excluded.doc_name, session_docs.doc_name),
                last_tool_name = excluded.last_tool_name,
                last_user_text = excluded.last_user_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                doc_id,
                doc_url,
                doc_name,
                last_tool_name,
                _short_text(last_user_text, limit=300),
            ),
        )
        conn.commit()


def load_memory_context(session_id: str) -> str:
    session_id = str(session_id or "").strip()
    if not session_id:
        return ""

    with _connect() as conn:
        docs = conn.execute(
            """
            SELECT doc_id, doc_url, doc_name, last_tool_name, updated_at
            FROM session_docs
            WHERE session_id = ?
              AND updated_at >= datetime('now', '-30 day')
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (session_id,),
        ).fetchall()

        turns = conn.execute(
            """
            SELECT role, content
            FROM conversation_turns
            WHERE session_id = ?
              AND created_at >= datetime('now', '-7 day')
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (session_id,),
        ).fetchall()

    sections: list[str] = []

    if docs:
        latest = docs[0]
        doc_lines = [
            "Current bound document:",
            f"- doc_id={latest['doc_id']}",
            f"- doc_name={latest['doc_name'] or ''}",
            f"- doc_url={latest['doc_url'] or ''}",
            f"- last_tool={latest['last_tool_name']}",
        ]
        if len(docs) > 1:
            doc_lines.append("Other recent docs:")
        for row in docs[1:]:
            doc_lines.append(
                f"- doc_id={row['doc_id']}; "
                f"doc_name={row['doc_name'] or ''}; "
                f"doc_url={row['doc_url'] or ''}; "
                f"last_tool={row['last_tool_name']}"
            )
        sections.append("\n".join(doc_lines))

    if turns:
        turn_lines = ["Recent dialogue:"]
        for row in reversed(turns):
            turn_lines.append(f"- {row['role']}: {_short_text(row['content'], limit=300)}")
        sections.append("\n".join(turn_lines))

    if not sections:
        return ""

    return (
        "Session memory from this same WeCom conversation.\n"
        "Rule: when the user refers to the previous or last document, prefer the currently bound doc_id recorded here unless the user explicitly asks for a new document.\n\n"
        + "\n\n".join(sections)
    )
