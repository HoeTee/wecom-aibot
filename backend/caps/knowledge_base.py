from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PAPER_DIR = PROJECT_ROOT / "knowledge_base" / "papers"
KNOWLEDGE_BASE_UPLOAD_DIR = KNOWLEDGE_BASE_PAPER_DIR / "uploads"
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


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_pdf_filename(filename: str) -> str:
    normalized = secure_filename(str(filename or "").strip())
    if not normalized:
        normalized = "uploaded.pdf"
    if not normalized.lower().endswith(".pdf"):
        normalized = f"{Path(normalized).stem or 'uploaded'}.pdf"
    return normalized


def upload_storage_name(filename: str) -> str:
    return f"upload__{normalize_pdf_filename(filename)}"


def knowledge_base_pdf_paths() -> list[Path]:
    return sorted(path for path in KNOWLEDGE_BASE_PAPER_DIR.rglob("*.pdf") if path.is_file())


def relative_project_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def absolute_project_path(relative_path: str) -> Path:
    candidate = (PROJECT_ROOT / str(relative_path or "").strip()).resolve()
    if PROJECT_ROOT not in [candidate, *candidate.parents]:
        raise ValueError("resolved path escaped project root")
    return candidate


def _display_name(path: Path) -> str:
    name = path.name
    if name.startswith("upload__"):
        return name[len("upload__") :]
    return name


def _source_type(path: Path) -> str:
    return "upload" if KNOWLEDGE_BASE_UPLOAD_DIR in path.parents else "base"


def list_pdf_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in knowledge_base_pdf_paths():
        records.append(
            {
                "file_name": _display_name(path),
                "stored_name": path.name,
                "stored_path": relative_project_path(path),
                "source_type": _source_type(path),
            }
        )
    return records


def recent_uploaded_records(limit: int = 5) -> list[dict[str, Any]]:
    upload_dir = KNOWLEDGE_BASE_UPLOAD_DIR
    if not upload_dir.exists():
        return []
    paths = sorted(
        (path for path in upload_dir.glob("*.pdf") if path.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "file_name": _display_name(path),
            "stored_name": path.name,
            "stored_path": relative_project_path(path),
            "source_type": "upload",
        }
        for path in paths[:limit]
    ]


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

    if "刚上传" in query_text and record.get("source_type") == "upload":
        score += 30
        reasons.append("近期上传候选")

    if score <= 0:
        return (0, "")
    return (score, "；".join(reasons))


def match_pdf_records(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    explicit_name = _explicit_pdf_reference(query)
    if explicit_name:
        exact = find_record_by_file_name(explicit_name)
        if exact:
            enriched = dict(exact)
            enriched["match_reason"] = "文件名精确匹配"
            enriched["match_score"] = 1000
            return [enriched]

    scored: list[tuple[int, str, dict[str, Any]]] = []
    for record in list_pdf_records():
        score, reason = _score_record(record, query)
        if score <= 0:
            continue
        enriched = dict(record)
        enriched["match_reason"] = reason
        enriched["match_score"] = score
        scored.append((score, record["file_name"], enriched))

    scored.sort(key=lambda item: (-item[0], item[1].lower()))
    return [item[2] for item in scored[:limit]]


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


def build_recent_upload_fallback_candidates(limit: int = 3) -> list[dict[str, Any]]:
    return recent_uploaded_records(limit=limit)


def export_record_path(record: dict[str, Any]) -> Path:
    return absolute_project_path(str(record["stored_path"]))


def delete_record(record: dict[str, Any]) -> None:
    path = export_record_path(record)
    if not path.exists():
        raise FileNotFoundError(path)
    path.unlink()


def store_pdf_in_knowledge_base(file_bytes: bytes, original_name: str) -> dict[str, str | None]:
    KNOWLEDGE_BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_BASE_UPLOAD_DIR / upload_storage_name(original_name)
    incoming_sha = sha256_bytes(file_bytes)

    if target_path.exists():
        existing_bytes = target_path.read_bytes()
        if sha256_bytes(existing_bytes) == incoming_sha:
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
