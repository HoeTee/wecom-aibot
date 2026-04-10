from __future__ import annotations

from typing import Any

from backend.caps.knowledge_base import sha256_bytes, store_pdf_in_knowledge_base
from backend.policy.chat import build_reply_generated_payload, build_request_received_payload, build_stop_reason_payload
from backend.policy.upload import (
    UploadValidationError,
    build_upload_reply,
    build_upload_route_payload,
    build_upload_user_marker,
    validate_pdf_upload,
)
from backend.state.store import build_session_id, generate_request_id, save_flow_event, save_turn, save_uploaded_file


def process_upload(form: Any, uploaded_file: Any) -> tuple[dict[str, Any], int]:
    try:
        original_name, file_bytes = validate_pdf_upload(uploaded_file)
    except UploadValidationError as exc:
        return {"error": str(exc)}, exc.status_code

    request_id = generate_request_id()
    session_id = build_session_id(
        chat_type=str(form.get("chatType", "")),
        chat_id=form.get("chatId"),
        user_id=str(form.get("userId", "")),
    )

    def emit_flow(layer_at_event: str, event_name: str, event_payload: dict[str, Any]) -> None:
        save_flow_event(session_id, request_id, layer_at_event, event_name, event_payload)

    emit_flow(
        "entry",
        "request_received",
        build_request_received_payload("file", content_preview=original_name),
    )

    store_result = store_pdf_in_knowledge_base(file_bytes, original_name)
    file_name = str(store_result["file_name"] or "")
    stored_path = str(store_result["stored_path"] or "")
    action = str(store_result["action"] or "")
    matched_file_name = str(store_result.get("matched_file_name") or "").strip() or None
    matched_stored_path = str(store_result.get("matched_stored_path") or "").strip() or None

    save_uploaded_file(
        session_id=session_id,
        file_name=file_name,
        stored_path=stored_path,
        file_sha256=sha256_bytes(file_bytes),
        upload_action=action,
        matched_file_name=matched_file_name,
        matched_stored_path=matched_stored_path,
        request_id=request_id,
    )

    emit_flow("flow", "route_selected", build_upload_route_payload(file_name, action))

    user_marker = build_upload_user_marker(file_name)
    assistant_reply = build_upload_reply(file_name, action, matched_file_name)
    save_turn(session_id, "user", user_marker, request_id=request_id)
    save_turn(session_id, "assistant", assistant_reply, request_id=request_id)

    emit_flow("entry", "reply_generated", build_reply_generated_payload("upload_ack", assistant_reply))
    emit_flow("flow", "stop_reason", build_stop_reason_payload("upload_complete", action))

    return {
        "reply": assistant_reply,
        "requestId": request_id,
        "fileName": file_name,
        "action": action,
        "knowledgeBasePath": stored_path,
        "matchedFileName": matched_file_name,
        "matchedKnowledgeBasePath": matched_stored_path,
    }, 200
