from __future__ import annotations

from typing import Any

from backend.caps.knowledge_base import PDF_HEADER, build_upload_reply, sha256_bytes, store_pdf_in_knowledge_base
from backend.policy.routing import build_route_payload, build_selected_target
from backend.state.store import build_session_id, generate_request_id, save_flow_event, save_turn, save_uploaded_file


def process_upload(form: Any, uploaded_file: Any) -> tuple[dict[str, Any], int]:
    if uploaded_file is None:
        return {"error": "file is required"}, 400

    original_name = str(uploaded_file.filename or "").strip()
    if not original_name:
        return {"error": "filename is required"}, 400

    file_bytes = uploaded_file.read()
    if not file_bytes:
        return {"error": "uploaded file is empty"}, 400

    if not original_name.lower().endswith(".pdf"):
        return {"error": "only PDF files are supported"}, 400

    if not file_bytes.startswith(PDF_HEADER):
        return {"error": "uploaded file is not a valid PDF"}, 400

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
        {"message_type": "file", "file_name": original_name},
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

    route_guard_hits: list[dict[str, str]] = []
    if action == "unchanged":
        route_guard_hits.append({"code": "duplicate_upload_guard", "detail": "same_name_same_content"})
    elif action == "duplicate_content":
        route_guard_hits.append({"code": "duplicate_upload_guard", "detail": "same_content_different_name"})
    elif action == "replaced":
        route_guard_hits.append({"code": "upload_update_guard", "detail": "same_name_content_updated"})

    emit_flow(
        "flow",
        "route_selected",
        build_route_payload(
            route_code="upload_ingest",
            route_detail="pdf_upload_to_knowledge_base",
            reasons=["pdf_file_message"],
            selected_target=build_selected_target("uploaded_file", file_name, file_name),
            guard_hits=route_guard_hits,
            clarify_needed=False,
        ),
    )

    user_marker = f"[上传PDF] {file_name}"
    assistant_reply = build_upload_reply(file_name, action, matched_file_name)
    save_turn(session_id, "user", user_marker, request_id=request_id)
    save_turn(session_id, "assistant", assistant_reply, request_id=request_id)

    emit_flow(
        "entry",
        "reply_generated",
        {"reply_type": "upload_ack", "reply_preview": assistant_reply[:200]},
    )
    emit_flow(
        "flow",
        "stop_reason",
        {"code": "upload_complete", "detail": action, "layer": "flow"},
    )

    return {
        "reply": assistant_reply,
        "requestId": request_id,
        "fileName": file_name,
        "action": action,
        "knowledgeBasePath": stored_path,
        "matchedFileName": matched_file_name,
        "matchedKnowledgeBasePath": matched_stored_path,
    }, 200
