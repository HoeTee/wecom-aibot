from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
GENERIC_QUERY_TOKENS = {
    "pdf",
    "文档",
    "文件",
    "知识库",
    "文章",
    "材料",
    "那篇",
    "某篇",
    "一篇",
    "原文",
    "原文件",
    "导出",
    "删除",
    "删掉",
}
EXPLICIT_PDF_RE = re.compile(r"([0-9A-Za-z._-]+\.pdf)", re.IGNORECASE)
INVALID_FILE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_pdf_filename(filename: str) -> str:
    normalized = str(filename or "").strip()
    normalized = INVALID_FILE_CHARS_RE.sub("_", normalized)
    normalized = normalized.strip().strip(".")
    if not normalized:
        normalized = "uploaded.pdf"
    if not normalized.lower().endswith(".pdf"):
        normalized = f"{normalized or 'uploaded'}.pdf"
    return normalized


def upload_storage_name(filename: str) -> str:
    return normalize_pdf_filename(filename)


def knowledge_base_pdf_paths() -> list[Path]:
    return sorted(
        path
        for path in KNOWLEDGE_BASE_DIR.glob("*.pdf")
        if path.is_file()
    )


def relative_project_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def absolute_project_path(relative_path: str) -> Path:
    candidate = (PROJECT_ROOT / str(relative_path or "").strip()).resolve()
    if PROJECT_ROOT not in [candidate, *candidate.parents]:
        raise ValueError("resolved path escaped project root")
    return candidate


def _display_name(path: Path) -> str:
    return path.name


def _tokenize(value: str) -> set[str]:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", str(value or "").lower()).strip()
    if not text:
        return set()
    return {token for token in text.split() if token and token not in GENERIC_QUERY_TOKENS}


def _explicit_pdf_reference(query: str) -> str | None:
    match = EXPLICIT_PDF_RE.search(str(query or ""))
    if match:
        return match.group(1).strip()
    return None


def _record_from_path(path: Path) -> dict[str, Any]:
    return {
        "file_name": _display_name(path),
        "stored_name": path.name,
        "stored_path": relative_project_path(path),
    }


def _score_record(record: dict[str, Any], query: str) -> tuple[int, str]:
    file_name = str(record["file_name"])
    query_text = str(query or "").strip()
    if not query_text:
        return (0, "")

    file_name_lower = file_name.lower()
    query_lower = query_text.lower()
    score = 0
    reasons: list[str] = []

    if query_lower in file_name_lower:
        score += 100
        reasons.append("文件名直接命中")

    query_tokens = _tokenize(query_text)
    file_tokens = _tokenize(file_name)
    overlap = query_tokens & file_tokens
    if overlap:
        score += 20 * len(overlap)
        reasons.append(f"关键词重合：{'、'.join(sorted(overlap)[:3])}")

    if score <= 0:
        return (0, "")
    return (score, "；".join(reasons))


def _list_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in knowledge_base_pdf_paths():
        records.append(_record_from_path(path))
    return records


def _recent_uploads(limit: int = 5) -> list[dict[str, Any]]:
    if not KNOWLEDGE_BASE_DIR.exists():
        return []
    paths = sorted(
        (path for path in KNOWLEDGE_BASE_DIR.glob("*.pdf") if path.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [_record_from_path(path) for path in paths[:limit]]


def _find_record_by_file_name(file_name: str) -> dict[str, Any] | None:
    normalized = str(file_name or "").strip().lower()
    if not normalized:
        return None
    for record in _list_records():
        if str(record["file_name"]).strip().lower() == normalized:
            return record
    return None


def _load_file_aliases() -> dict[str, list[str]]:
    """Load file aliases from recent assistant conversation turns.

    Scans for patterns like "`2505.12540v4.pdf`（大模型推理优化）" in assistant
    replies and builds a mapping of file_name -> [alias1, alias2, ...].
    """
    alias_map: dict[str, list[str]] = {}
    alias_pattern = re.compile(
        r'`?([0-9A-Za-z._-]+\.pdf)`?\s*[（(]\s*([^）)]+?)\s*[）)]',
        re.IGNORECASE,
    )
    try:
        import sqlite3
        db_path = PROJECT_ROOT / "data" / "memory.sqlite3"
        if not db_path.exists():
            return alias_map
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT content FROM conversation_turns "
            "WHERE role = 'assistant' "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()
        conn.close()
        for row in rows:
            content = str(row["content"] or "")
            for match in alias_pattern.finditer(content):
                fname = match.group(1).strip()
                alias = match.group(2).strip()
                if fname and alias:
                    alias_map.setdefault(fname, [])
                    if alias not in alias_map[fname]:
                        alias_map[fname].append(alias)
    except Exception:
        pass
    return alias_map


def _match_records(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    explicit_name = _explicit_pdf_reference(query)
    if explicit_name:
        exact = _find_record_by_file_name(explicit_name)
        if exact:
            enriched = dict(exact)
            enriched["match_reason"] = "文件名精确匹配"
            enriched["match_score"] = 1000
            return [enriched]

    # Load aliases from conversation history
    alias_map = _load_file_aliases()

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for record in _list_records():
        score, reason = _score_record(record, query)

        # Also check aliases for this file
        file_name = str(record["file_name"])
        aliases = alias_map.get(file_name, [])
        query_lower = str(query or "").strip().lower()
        for alias in aliases:
            if query_lower in alias.lower() or alias.lower() in query_lower:
                score += 200
                reason = f"别名匹配：{alias}" + (f"；{reason}" if reason else "")
                break
            # Partial token overlap with alias
            alias_tokens = _tokenize(alias)
            query_tokens = _tokenize(query)
            overlap = alias_tokens & query_tokens
            if overlap:
                score += 50 * len(overlap)
                reason = f"别名关键词：{'、'.join(sorted(overlap)[:3])}" + (f"；{reason}" if reason else "")
                break

        if score <= 0:
            continue
        enriched = dict(record)
        enriched["match_reason"] = reason
        enriched["match_score"] = score
        scored.append((score, record["file_name"], enriched))

    scored.sort(key=lambda item: (-item[0], item[1].lower()))
    return [item[2] for item in scored[:limit]]


def _resolve_record(
    *,
    record: dict[str, Any] | None = None,
    stored_path: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    if record:
        return dict(record)
    if stored_path:
        path = absolute_project_path(stored_path)
        if not path.exists():
            raise FileNotFoundError(path)
        return _record_from_path(path)
    if file_name:
        resolved = _find_record_by_file_name(file_name)
        if resolved:
            return resolved
    raise FileNotFoundError("knowledge-base record not found")


def _can_rename(record: dict[str, Any]) -> bool:
    _ = record
    return True


def _export_path(record: dict[str, Any]) -> Path:
    return absolute_project_path(str(record["stored_path"]))


def _rename(record: dict[str, Any], new_file_name: str) -> dict[str, Any]:
    if not _can_rename(record):
        raise PermissionError("only uploaded knowledge-base files can be renamed")

    source_path = _export_path(record)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    normalized_new_name = normalize_pdf_filename(new_file_name)
    target_path = KNOWLEDGE_BASE_DIR / upload_storage_name(normalized_new_name)
    if target_path.resolve() == source_path.resolve():
        return {
            "old_file_name": record["file_name"],
            "new_file_name": _display_name(target_path),
            "old_stored_path": record["stored_path"],
            "new_stored_path": relative_project_path(target_path),
            "action": "unchanged",
        }
    if target_path.exists():
        raise FileExistsError(target_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.rename(target_path)
    return {
        "old_file_name": record["file_name"],
        "new_file_name": _display_name(target_path),
        "old_stored_path": record["stored_path"],
        "new_stored_path": relative_project_path(target_path),
        "action": "renamed",
    }


def _delete(record: dict[str, Any]) -> dict[str, Any]:
    path = _export_path(record)
    if not path.exists():
        raise FileNotFoundError(path)
    path.unlink()
    return {"deleted": True, "record": record}


def _store_upload(file_bytes: bytes, original_name: str) -> dict[str, str | None]:
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_BASE_DIR / upload_storage_name(original_name)
    incoming_sha = sha256_bytes(file_bytes)

    if target_path.exists():
        if sha256_bytes(target_path.read_bytes()) == incoming_sha:
            return {
                "file_name": _display_name(target_path),
                "stored_path": relative_project_path(target_path),
                "action": "unchanged",
                "matched_file_name": _display_name(target_path),
                "matched_stored_path": relative_project_path(target_path),
            }
        action = "replaced"
    else:
        action = "added"

    for existing_path in knowledge_base_pdf_paths():
        if existing_path == target_path:
            continue
        if sha256_bytes(existing_path.read_bytes()) != incoming_sha:
            continue
        return {
            "file_name": _display_name(target_path),
            "stored_path": relative_project_path(existing_path),
            "action": "duplicate_content",
            "matched_file_name": _display_name(existing_path),
            "matched_stored_path": relative_project_path(existing_path),
        }

    target_path.write_bytes(file_bytes)
    return {
        "file_name": _display_name(target_path),
        "stored_path": relative_project_path(target_path),
        "action": action,
        "matched_file_name": _display_name(target_path) if action == "replaced" else None,
        "matched_stored_path": relative_project_path(target_path) if action == "replaced" else None,
    }


def execute_kb_action(action: str, **kwargs: Any) -> dict[str, Any]:
    if action == "kb.list":
        records = _list_records()
        return {"ok": True, "action": action, "records": records, "total": len(records)}

    if action == "kb.list_uploads":
        limit = int(kwargs.get("limit") or 5)
        records = _recent_uploads(limit=limit)
        return {"ok": True, "action": action, "scope": "recent", "records": records, "total": len(records)}

    if action == "kb.match_related":
        query = str(kwargs.get("query") or "").strip()
        limit = int(kwargs.get("limit") or 10)
        records = _match_records(query, limit=limit)
        return {
            "ok": True,
            "action": action,
            "query": query,
            "records": records,
            "total": len(records),
        }

    if action == "kb.export":
        record = _resolve_record(
            record=kwargs.get("record"),
            stored_path=kwargs.get("stored_path"),
            file_name=kwargs.get("file_name"),
        )
        path = _export_path(record)
        return {
            "ok": True,
            "action": action,
            "record": record,
            "path": str(path),
            "file_name": record["file_name"],
        }

    if action == "kb.rename":
        record = _resolve_record(
            record=kwargs.get("record"),
            stored_path=kwargs.get("stored_path"),
            file_name=kwargs.get("file_name"),
        )
        new_file_name = str(kwargs.get("new_file_name") or "").strip()
        result = _rename(record, new_file_name)
        return {"ok": True, "action": action, "record": record, "result": result}

    if action == "kb.delete":
        record = _resolve_record(
            record=kwargs.get("record"),
            stored_path=kwargs.get("stored_path"),
            file_name=kwargs.get("file_name"),
        )
        result = _delete(record)
        return {"ok": True, "action": action, "record": record, "result": result}

    if action == "kb.store_upload":
        file_bytes = kwargs.get("file_bytes")
        if isinstance(file_bytes, str):
            file_bytes = base64.b64decode(file_bytes)
        if not isinstance(file_bytes, (bytes, bytearray)):
            raise ValueError("kb.store_upload requires file_bytes")
        original_name = str(kwargs.get("original_name") or "").strip()
        result = _store_upload(bytes(file_bytes), original_name)
        return {"ok": True, "action": action, "result": result}

    raise KeyError(f"Unknown kb action: {action}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    uploads_parser = subparsers.add_parser("list-uploads")
    uploads_parser.add_argument("--limit", type=int, default=5)
    uploads_parser.add_argument("--json", action="store_true")

    match_parser = subparsers.add_parser("match-related")
    match_parser.add_argument("--query", required=True)
    match_parser.add_argument("--limit", type=int, default=10)
    match_parser.add_argument("--json", action="store_true")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--stored-path")
    export_parser.add_argument("--file")
    export_parser.add_argument("--json", action="store_true")

    rename_parser = subparsers.add_parser("rename")
    rename_parser.add_argument("--stored-path")
    rename_parser.add_argument("--file")
    rename_parser.add_argument("--to", required=True)
    rename_parser.add_argument("--json", action="store_true")

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("--stored-path")
    delete_parser.add_argument("--file")
    delete_parser.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            result = execute_kb_action("kb.list")
        elif args.command == "list-uploads":
            result = execute_kb_action("kb.list_uploads", limit=args.limit)
        elif args.command == "match-related":
            result = execute_kb_action(
                "kb.match_related",
                query=args.query,
                limit=args.limit,
            )
        elif args.command == "export":
            result = execute_kb_action("kb.export", stored_path=args.stored_path, file_name=args.file)
        elif args.command == "rename":
            result = execute_kb_action(
                "kb.rename",
                stored_path=args.stored_path,
                file_name=args.file,
                new_file_name=args.to,
            )
        elif args.command == "delete":
            result = execute_kb_action("kb.delete", stored_path=args.stored_path, file_name=args.file)
        else:
            raise KeyError(args.command)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "command": args.command}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
