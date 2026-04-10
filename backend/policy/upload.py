from __future__ import annotations

from typing import Any

from backend.policy.routing import build_route_payload, build_selected_target


PDF_HEADER = b"%PDF-"


class UploadValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_pdf_upload(uploaded_file: Any) -> tuple[str, bytes]:
    if uploaded_file is None:
        raise UploadValidationError("file is required")

    original_name = str(uploaded_file.filename or "").strip()
    if not original_name:
        raise UploadValidationError("filename is required")

    file_bytes = uploaded_file.read()
    if not file_bytes:
        raise UploadValidationError("uploaded file is empty")

    if not original_name.lower().endswith(".pdf"):
        raise UploadValidationError("only PDF files are supported")

    if not file_bytes.startswith(PDF_HEADER):
        raise UploadValidationError("uploaded file is not a valid PDF")

    return original_name, file_bytes


def build_upload_guard_hits(action: str) -> list[dict[str, str]]:
    if action == "unchanged":
        return [{"code": "duplicate_upload_guard", "detail": "same_name_same_content"}]
    if action == "duplicate_content":
        return [{"code": "duplicate_upload_guard", "detail": "same_content_different_name"}]
    if action == "replaced":
        return [{"code": "upload_update_guard", "detail": "same_name_content_updated"}]
    return []


def build_upload_route_payload(file_name: str, action: str) -> dict[str, Any]:
    return build_route_payload(
        route_code="upload_ingest",
        route_detail="pdf_upload_to_knowledge_base",
        reasons=["pdf_file_message"],
        selected_target=build_selected_target("uploaded_file", file_name, file_name),
        guard_hits=build_upload_guard_hits(action),
        clarify_needed=False,
    )


def build_upload_user_marker(file_name: str) -> str:
    return f"[上传PDF] {file_name}"


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
