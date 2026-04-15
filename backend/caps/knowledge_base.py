from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.runtime import dispatch_cli_action


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def list_kb_files() -> dict[str, Any]:
    return dispatch_cli_action("kb.list")


def list_uploaded_kb_files(*, limit: int = 5) -> dict[str, Any]:
    return dispatch_cli_action("kb.list_uploads", limit=limit)


def match_related_kb_files(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    return dispatch_cli_action(
        "kb.match_related",
        query=query,
        limit=limit,
    )


def export_kb_record(record: dict[str, Any]) -> dict[str, Any]:
    return dispatch_cli_action("kb.export", record=record)


def rename_kb_record(record: dict[str, Any], new_file_name: str) -> dict[str, Any]:
    return dispatch_cli_action("kb.rename", record=record, new_file_name=new_file_name)


def delete_kb_record(record: dict[str, Any]) -> dict[str, Any]:
    return dispatch_cli_action("kb.delete", record=record)


def store_uploaded_kb_file(file_bytes: bytes, original_name: str) -> dict[str, Any]:
    return dispatch_cli_action("kb.store_upload", file_bytes=file_bytes, original_name=original_name)


def list_pdf_records() -> list[dict[str, Any]]:
    return list_kb_files()["records"]


def recent_uploaded_records(limit: int = 5) -> list[dict[str, Any]]:
    return list_uploaded_kb_files(limit=limit)["records"]


def match_pdf_records(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    return match_related_kb_files(query, limit=limit)["records"]


def resolve_record_by_index(candidates: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if index < 0 or index >= len(candidates):
        return None
    return candidates[index]


def find_record_by_file_name(file_name: str) -> dict[str, Any] | None:
    normalized = str(file_name or "").strip().lower()
    if not normalized:
        return None
    for record in list_pdf_records():
        if str(record["file_name"]).strip().lower() == normalized:
            return record
    return None


def can_rename_record(record: dict[str, Any]) -> bool:
    _ = record
    return True


def build_recent_upload_fallback_candidates(limit: int = 3) -> list[dict[str, Any]]:
    return recent_uploaded_records(limit=limit)


def export_record_path(record: dict[str, Any]) -> Path:
    result = export_kb_record(record)
    return Path(result["path"])


def delete_record(record: dict[str, Any]) -> None:
    delete_kb_record(record)


def rename_record(record: dict[str, Any], new_file_name: str) -> dict[str, Any]:
    return rename_kb_record(record, new_file_name)["result"]


def store_pdf_in_knowledge_base(file_bytes: bytes, original_name: str) -> dict[str, str | None]:
    return store_uploaded_kb_file(file_bytes, original_name)["result"]
