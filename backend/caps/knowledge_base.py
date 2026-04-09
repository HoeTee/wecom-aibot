from __future__ import annotations

import hashlib
from pathlib import Path

from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PAPER_DIR = PROJECT_ROOT / "knowledge_base" / "papers"
KNOWLEDGE_BASE_UPLOAD_DIR = KNOWLEDGE_BASE_PAPER_DIR / "uploads"
PDF_HEADER = b"%PDF-"


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


def store_pdf_in_knowledge_base(file_bytes: bytes, original_name: str) -> dict[str, str | None]:
    KNOWLEDGE_BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_BASE_UPLOAD_DIR / upload_storage_name(original_name)
    incoming_sha = sha256_bytes(file_bytes)

    if target_path.exists():
        existing_bytes = target_path.read_bytes()
        if sha256_bytes(existing_bytes) == incoming_sha:
            return {
                "file_name": target_path.name,
                "stored_path": relative_project_path(target_path),
                "action": "unchanged",
                "matched_file_name": target_path.name,
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
            "file_name": target_path.name,
            "stored_path": relative_project_path(existing_path),
            "action": "duplicate_content",
            "matched_file_name": existing_path.name,
            "matched_stored_path": relative_project_path(existing_path),
        }

    target_path.write_bytes(file_bytes)
    return {
        "file_name": target_path.name,
        "stored_path": relative_project_path(target_path),
        "action": action,
        "matched_file_name": target_path.name if action == "replaced" else None,
        "matched_stored_path": relative_project_path(target_path) if action == "replaced" else None,
    }


def build_upload_reply(file_name: str, action: str, matched_file_name: str | None = None) -> str:
    if action == "unchanged":
        return f"PDF `{file_name}` 已经在知识库里了，文件名和内容都重复，未再次写入。"
    if action == "duplicate_content":
        if matched_file_name:
            return f"PDF `{file_name}` 与知识库中的 `{matched_file_name}` 内容完全一致，未重复加入知识库。"
        return f"PDF `{file_name}` 与知识库中的现有文件内容完全一致，未重复加入知识库。"
    if action == "replaced":
        return f"检测到同名 PDF `{file_name}` 已存在，已用新上传内容更新知识库中的同名文件。"
    return f"PDF `{file_name}` 已加入知识库。后续检索会自动纳入它。"
