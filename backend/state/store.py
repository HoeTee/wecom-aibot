from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "memory.sqlite3"

DOC_ID_PATTERN = re.compile(r'(?i)(?:docid|doc_id)\b["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]+)')
DOC_NAME_PATTERN = re.compile(r'(?i)(?:doc_name|docname)\b["\']?\s*[:=]\s*["\']?([^\n,"\'}]+)')
DOC_URL_PATTERN = re.compile(r"(https?://[^\s'\"]+)")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
                request_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT,
                tool_name TEXT NOT NULL,
                args_json TEXT NOT NULL,
                result_excerpt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS session_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT,
                doc_id TEXT NOT NULL,
                doc_url TEXT,
                doc_name TEXT,
                last_tool_name TEXT NOT NULL,
                last_user_text TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, doc_id)
            );

            CREATE TABLE IF NOT EXISTS session_uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT,
                file_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_sha256 TEXT NOT NULL,
                upload_action TEXT NOT NULL,
                matched_file_name TEXT,
                matched_stored_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS flow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                layer_at_event TEXT NOT NULL,
                event_name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _ensure_column(conn, "conversation_turns", "request_id", "TEXT")
        _ensure_column(conn, "tool_calls", "request_id", "TEXT")
        _ensure_column(conn, "session_docs", "request_id", "TEXT")
        _ensure_column(conn, "session_uploaded_files", "request_id", "TEXT")
        _ensure_column(conn, "session_uploaded_files", "matched_file_name", "TEXT")
        _ensure_column(conn, "session_uploaded_files", "matched_stored_path", "TEXT")
        conn.commit()


def generate_request_id() -> str:
    return uuid4().hex


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


def save_turn(session_id: str, role: str, content: str, request_id: str | None = None) -> None:
    session_id = str(session_id or "").strip()
    role = str(role or "").strip()
    content = str(content or "").strip()
    request_id = str(request_id or "").strip() or None
    if not session_id or not role or not content:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_turns (session_id, request_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, request_id, role, content),
        )
        conn.commit()


def save_tool_call(
    session_id: str,
    tool_name: str,
    args_dict: dict[str, Any],
    result_text: str,
    request_id: str | None = None,
) -> None:
    session_id = str(session_id or "").strip()
    tool_name = str(tool_name or "").strip()
    request_id = str(request_id or "").strip() or None
    if not session_id or not tool_name:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tool_calls (session_id, request_id, tool_name, args_json, result_excerpt)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                request_id,
                tool_name,
                _json_dumps(args_dict),
                _short_text(result_text),
            ),
        )
        conn.commit()


def save_flow_event(
    session_id: str,
    request_id: str,
    layer_at_event: str,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    session_id = str(session_id or "").strip()
    request_id = str(request_id or "").strip()
    layer_at_event = str(layer_at_event or "").strip()
    event_name = str(event_name or "").strip()
    if not session_id or not request_id or not layer_at_event or not event_name:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO flow_events (session_id, request_id, layer_at_event, event_name, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                request_id,
                layer_at_event,
                event_name,
                _json_dumps(payload),
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


def persist_doc_binding_from_tool_result(
    session_id: str,
    request_id: str,
    tool_name: str,
    args_dict: dict[str, Any],
    result_text: str,
    last_user_text: str,
) -> dict[str, str | None] | None:
    binding = extract_doc_binding(tool_name, args_dict, result_text)
    if not binding:
        return None

    upsert_session_doc(
        session_id=session_id,
        doc_id=str(binding["doc_id"] or ""),
        doc_url=binding["doc_url"],
        doc_name=binding["doc_name"],
        last_tool_name=tool_name,
        last_user_text=last_user_text,
        request_id=request_id,
    )
    return binding


def upsert_session_doc(
    session_id: str,
    doc_id: str,
    doc_url: str | None,
    doc_name: str | None,
    last_tool_name: str,
    last_user_text: str,
    request_id: str | None = None,
) -> None:
    session_id = str(session_id or "").strip()
    doc_id = str(doc_id or "").strip()
    last_tool_name = str(last_tool_name or "").strip()
    last_user_text = str(last_user_text or "").strip()
    request_id = str(request_id or "").strip() or None
    if not session_id or not doc_id or not last_tool_name:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO session_docs (
                session_id,
                request_id,
                doc_id,
                doc_url,
                doc_name,
                last_tool_name,
                last_user_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, doc_id) DO UPDATE SET
                request_id = excluded.request_id,
                doc_url = COALESCE(excluded.doc_url, session_docs.doc_url),
                doc_name = COALESCE(excluded.doc_name, session_docs.doc_name),
                last_tool_name = excluded.last_tool_name,
                last_user_text = excluded.last_user_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                request_id,
                doc_id,
                doc_url,
                doc_name,
                last_tool_name,
                _short_text(last_user_text, limit=300),
            ),
        )
        conn.commit()


def save_uploaded_file(
    session_id: str,
    file_name: str,
    stored_path: str,
    file_sha256: str,
    upload_action: str,
    matched_file_name: str | None = None,
    matched_stored_path: str | None = None,
    request_id: str | None = None,
) -> None:
    session_id = str(session_id or "").strip()
    file_name = str(file_name or "").strip()
    stored_path = str(stored_path or "").strip()
    file_sha256 = str(file_sha256 or "").strip()
    upload_action = str(upload_action or "").strip()
    request_id = str(request_id or "").strip() or None
    if not session_id or not file_name or not stored_path or not file_sha256 or not upload_action:
        return

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO session_uploaded_files (
                session_id,
                request_id,
                file_name,
                stored_path,
                file_sha256,
                upload_action,
                matched_file_name,
                matched_stored_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                request_id,
                file_name,
                stored_path,
                file_sha256,
                upload_action,
                str(matched_file_name or "").strip() or None,
                str(matched_stored_path or "").strip() or None,
            ),
        )
        conn.commit()


def latest_uploaded_file(session_id: str, within_minutes: int = 30) -> dict[str, Any] | None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return None

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                request_id,
                file_name,
                stored_path,
                file_sha256,
                upload_action,
                matched_file_name,
                matched_stored_path,
                created_at
            FROM session_uploaded_files
            WHERE session_id = ?
              AND created_at >= datetime('now', ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, f"-{int(within_minutes)} minute"),
        ).fetchone()

    return dict(row) if row else None


def load_memory_context(session_id: str, include_bound_doc: bool = True) -> str:
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

        user_turns = conn.execute(
            """
            SELECT content
            FROM conversation_turns
            WHERE session_id = ?
              AND role = 'user'
              AND created_at >= datetime('now', '-7 day')
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (session_id,),
        ).fetchall()

        uploaded_files = conn.execute(
            """
            SELECT file_name, stored_path, upload_action, created_at,
                   matched_file_name, matched_stored_path
            FROM session_uploaded_files
            WHERE session_id = ?
              AND created_at >= datetime('now', '-7 day')
            ORDER BY id DESC
            LIMIT 3
            """,
            (session_id,),
        ).fetchall()

    sections: list[str] = []

    if docs and include_bound_doc:
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

    if user_turns:
        turn_lines = ["Recent user requests:"]
        for row in reversed(user_turns):
            turn_lines.append(f"- user: {_short_text(row['content'], limit=300)}")
        sections.append("\n".join(turn_lines))

    if uploaded_files:
        upload_lines = ["Recent uploaded files:"]
        for row in reversed(uploaded_files):
            upload_lines.append(
                f"- file_name={row['file_name']}; "
                f"stored_path={row['stored_path']}; "
                f"action={row['upload_action']}; "
                f"matched_file_name={row['matched_file_name'] or ''}; "
                f"matched_stored_path={row['matched_stored_path'] or ''}"
            )
        sections.append("\n".join(upload_lines))

    if not sections:
        return ""

    return (
        "Session memory from this same WeCom conversation.\n"
        "Rule: when the user refers to the previous or last document, prefer the currently bound doc_id recorded here unless the user explicitly asks for a new document.\n\n"
        + "\n\n".join(sections)
    )
