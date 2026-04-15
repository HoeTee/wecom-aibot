from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "memory.sqlite3"
FLOW_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "flow"
FLOW_LOG_PATH = FLOW_LOG_DIR / "flow_runtime.log"
RECENT_USER_TURN_LIMIT = 10
RECENT_UPLOADED_FILE_LIMIT = 3

DOC_ID_PATTERN = re.compile(r'(?i)(?:docid|doc_id)\b["\']?\s*[:=]\s*["\']?([A-Za-z0-9_-]+)')
DOC_NAME_PATTERN = re.compile(r'(?i)(?:doc_name|docname)\b["\']?\s*[:=]\s*["\']?([^\n,"\'}]+)')
DOC_URL_PATTERN = re.compile(r"(https?://[^\s'\"]+)")
DOC_URL_HOSTS = {"doc.weixin.qq.com"}
DOC_URL_PATH_PREFIXES = ("/doc/", "/smartsheet/")


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


def _summarize_tool_args_dict(args_dict: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in args_dict.items():
        if key == "content":
            text = str(value or "").strip()
            summary["content_preview"] = _short_text(text, limit=120)
            summary["content_length"] = len(text)
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        else:
            summary[key] = _short_text(_json_dumps(value), limit=120)
    return summary


def _tool_result_status(result_excerpt: str) -> str:
    text = str(result_excerpt or "")
    lowered = text.lower()
    if any(token in lowered for token in ("error", "failed", "traceback")):
        return "failure"
    if '"errcode":' in text and '"errcode": 0' not in text:
        return "failure"
    return "success"


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


def _parse_json_payload(text: str) -> dict[str, Any]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start == -1 or end <= start:
            return {}
        try:
            payload = json.loads(raw_text[start:end])
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_doc_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in DOC_URL_HOSTS:
        return None
    if not parsed.path.startswith(DOC_URL_PATH_PREFIXES):
        return None
    return text


def _extract_doc_url_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("doc_url", "docUrl", "url"):
        doc_url = _normalize_doc_url(payload.get(key))
        if doc_url:
            return doc_url

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("doc_url", "docUrl", "url"):
            doc_url = _normalize_doc_url(data.get(key))
            if doc_url:
                return doc_url
    return None


def _extract_doc_url(tool_name: str, args_dict: dict[str, Any], result_text: str) -> str | None:
    for key in ("docurl", "doc_url", "docUrl", "url"):
        doc_url = _normalize_doc_url(args_dict.get(key))
        if doc_url:
            return doc_url

    doc_url = _extract_doc_url_from_payload(_parse_json_payload(result_text))
    if doc_url:
        return doc_url

    if str(tool_name or "").strip().endswith("create_doc"):
        return _normalize_doc_url(_extract_with_pattern(DOC_URL_PATTERN, result_text))
    return None


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

    FLOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
    with FLOW_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            _json_dumps(
                {
                    "session_id": session_id,
                    "request_id": request_id,
                    "layer_at_event": layer_at_event,
                    "event_name": event_name,
                    "payload": payload,
                }
            )
            + "\n"
        )


def extract_doc_binding(tool_name: str, args_dict: dict[str, Any], result_text: str) -> dict[str, str | None] | None:
    doc_id = _find_first_value(args_dict, ("docid", "doc_id", "docId"))
    doc_url = _extract_doc_url(tool_name, args_dict, result_text)
    doc_name = _find_first_value(args_dict, ("doc_name", "docName", "docname", "doc_name_or_title"))

    if not doc_id:
        doc_id = _extract_with_pattern(DOC_ID_PATTERN, result_text)
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


def current_bound_doc(session_id: str) -> dict[str, Any] | None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return None

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT request_id, doc_id, doc_url, doc_name, last_tool_name, last_user_text, updated_at
            FROM session_docs
            WHERE session_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    return dict(row) if row else None


def _load_recent_turn_states(conn: sqlite3.Connection, session_id: str, *, limit: int) -> list[dict[str, Any]]:
    user_rows = conn.execute(
        """
        SELECT id, request_id, content, created_at
        FROM conversation_turns
        WHERE session_id = ?
          AND role = 'user'
          AND created_at >= datetime('now', '-7 day')
        ORDER BY id DESC, created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()

    turn_states: list[dict[str, Any]] = []
    for row in reversed(user_rows):
        request_id = str(row["request_id"] or "").strip() or None
        assistant_reply: str | None = None
        tool_entries: list[str] = []

        if request_id:
            assistant_row = conn.execute(
                """
                SELECT content
                FROM conversation_turns
                WHERE session_id = ?
                  AND request_id = ?
                  AND role = 'assistant'
                ORDER BY id DESC, created_at DESC
                LIMIT 1
                """,
                (session_id, request_id),
            ).fetchone()
            if assistant_row:
                assistant_reply = str(assistant_row["content"] or "").strip() or None

            tool_rows = conn.execute(
                """
                SELECT tool_name, result_excerpt
                FROM tool_calls
                WHERE session_id = ?
                  AND request_id = ?
                ORDER BY id ASC, created_at ASC
                LIMIT 10
                """,
                (session_id, request_id),
            ).fetchall()
            for tool_row in tool_rows:
                status = _tool_result_status(str(tool_row['result_excerpt'] or ''))
                tool_entries.append(f"{tool_row['tool_name']}({status})")

        turn_states.append(
            {
                "request_id": request_id,
                "user": str(row["content"] or "").strip(),
                "assistant": assistant_reply,
                "tools": tool_entries,
            }
        )

    return turn_states


def load_recent_chat_history(session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Load recent conversation turns with tool calls as proper chat messages.

    Reconstructs the full message chain per request:
      1. {"role": "user", "content": ...}
      2. {"role": "assistant", "content": null, "tool_calls": [...]}  (if tools were used)
      3. {"role": "tool", "tool_call_id": ..., "content": ...}       (per tool call)
      4. {"role": "assistant", "content": ...}                        (final reply)

    Returns messages in chronological order.
    """
    session_id = str(session_id or "").strip()
    if not session_id:
        return []

    with _connect() as conn:
        user_rows = conn.execute(
            """
            SELECT request_id, content
            FROM conversation_turns
            WHERE session_id = ?
              AND role = 'user'
              AND created_at >= datetime('now', '-7 day')
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()

        if not user_rows:
            return []

        messages: list[dict[str, Any]] = []
        for row in reversed(user_rows):
            request_id = str(row["request_id"] or "").strip() or None
            user_content = str(row["content"] or "").strip()
            if not user_content:
                continue

            messages.append({"role": "user", "content": user_content})

            if not request_id:
                continue

            tool_rows = conn.execute(
                """
                SELECT tool_name, args_json, result_excerpt
                FROM tool_calls
                WHERE session_id = ? AND request_id = ?
                ORDER BY id ASC
                LIMIT 10
                """,
                (session_id, request_id),
            ).fetchall()

            if tool_rows:
                tool_calls_list = []
                tool_results = []
                for idx, tool_row in enumerate(tool_rows):
                    call_id = f"hist_{request_id[:8]}_{idx}"
                    tool_name = str(tool_row["tool_name"] or "")
                    args_raw = str(tool_row["args_json"] or "{}")
                    result_raw = str(tool_row["result_excerpt"] or "")

                    tool_calls_list.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": args_raw,
                        },
                    })
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_raw,
                    })

                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls_list,
                })
                messages.extend(tool_results)

            assistant_row = conn.execute(
                """
                SELECT content
                FROM conversation_turns
                WHERE session_id = ? AND request_id = ? AND role = 'assistant'
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id, request_id),
            ).fetchone()
            if assistant_row:
                reply = str(assistant_row["content"] or "").strip()
                if reply:
                    messages.append({"role": "assistant", "content": reply})

    return messages


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

        turn_states = _load_recent_turn_states(conn, session_id, limit=RECENT_USER_TURN_LIMIT)

        uploaded_files = conn.execute(
            """
            SELECT file_name, stored_path, upload_action, created_at,
                   matched_file_name, matched_stored_path
            FROM session_uploaded_files
            WHERE session_id = ?
              AND created_at >= datetime('now', '-7 day')
            ORDER BY id DESC, created_at DESC
            LIMIT ?
            """,
            (session_id, RECENT_UPLOADED_FILE_LIMIT),
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

    if turn_states:
        turn_lines = [
            "Recent conversation turns (historical, not source-of-truth):",
        ]
        for turn in turn_states:
            user_text = _short_text(turn['user'], limit=120)
            tools = list(turn.get("tools") or [])
            assistant_reply = _short_text(str(turn.get("assistant") or ""), limit=100)
            tool_summary = "; ".join(tools[:5]) if tools else "no tools"
            line = f"- user: {user_text} → [{tool_summary}]"
            if assistant_reply:
                line += f" → reply: {assistant_reply}"
            turn_lines.append(line)
        sections.append("\n".join(turn_lines))

    if uploaded_files:
        upload_lines = ["Recent uploads to knowledge base:"]
        for row in reversed(uploaded_files):
            entry = f"- {row['file_name']} ({row['upload_action']})"
            matched = str(row['matched_file_name'] or '').strip()
            if matched:
                entry += f" matched={matched}"
            upload_lines.append(entry)
        sections.append("\n".join(upload_lines))

    if not sections:
        return ""

    return (
        "Session memory (internal context only — never cite this data in replies).\n"
        "Use this to understand conversation history and resolve references like '上一个文档'.\n"
        "Do NOT mention tool names, request IDs, file paths, or other internal details from this memory in your reply to the user.\n\n"
        + "\n\n".join(sections)
    )


