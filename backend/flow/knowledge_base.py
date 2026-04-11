from __future__ import annotations

from typing import Any

from backend.caps.knowledge_base import (
    build_recent_upload_fallback_candidates,
    can_rename_record,
    delete_record,
    export_record_path,
    list_pdf_records,
    match_pdf_records,
    rename_record,
    resolve_record_by_index,
)
from backend.policy.knowledge_base import (
    asks_upload_label,
    asks_recent_uploaded_file,
    build_delete_confirm_reply,
    build_export_clarify_reply,
    build_kb_list_reply,
    build_rename_candidates_reply,
    build_rename_confirm_reply,
    build_rename_intro_reply,
    build_rename_new_name_reply,
    build_rename_unsupported_reply,
    build_recent_upload_reply,
    build_related_candidates_reply,
    candidate_action_is_clear,
    is_affirmative,
    is_best_doc_query,
    is_delete_request,
    is_export_request,
    is_kb_file_management_intent,
    is_kb_list_request,
    is_kb_list_followup_request,
    is_rename_request,
    is_related_doc_query,
    is_uploaded_file_list_request,
    parse_candidate_selection,
    parse_new_file_name,
    wants_full_list,
    wants_brief_answer,
    wants_generate_doc,
    wants_original_file,
    wants_summary,
    wants_summary_and_doc,
)
from backend.policy.payloads import build_route_payload, build_selected_target
from backend.state.store import (
    latest_route_selection,
    latest_recent_candidate_list,
    latest_pending_action,
    latest_uploaded_file,
    resolve_pending_action,
    save_recent_candidate_list,
    save_pending_action,
    update_uploaded_file_reference,
)


def _serializable_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_name": record["file_name"],
        "stored_name": record["stored_name"],
        "stored_path": record["stored_path"],
        "source_type": record["source_type"],
        "match_reason": record.get("match_reason", ""),
        "match_score": record.get("match_score", 0),
    }


def _build_result(
    *,
    reply: str,
    route_code: str,
    route_detail: str,
    reasons: list[str],
    selected_target: dict[str, Any],
    reply_type: str,
    stop_code: str,
    stop_detail: str,
    clarify_needed: bool = False,
    clarify_reason: str | None = None,
    guard_hits: list[dict[str, str]] | None = None,
    attachment: dict[str, Any] | None = None,
    delegate_message: str | None = None,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "route_payload": build_route_payload(
            route_code=route_code,
            route_detail=route_detail,
            reasons=reasons,
            selected_target=selected_target,
            guard_hits=guard_hits,
            clarify_needed=clarify_needed,
            clarify_reason=clarify_reason,
        ),
        "reply_type": reply_type,
        "stop_reason": {"code": stop_code, "detail": stop_detail, "layer": "flow"},
        "attachment": attachment,
        "delegate_message": delegate_message,
    }


def _select_candidates_from_content(content: str, *, limit: int = 5, source_type: str | None = None) -> list[dict[str, Any]]:
    return [_serializable_record(item) for item in match_pdf_records(content, limit=limit, source_type=source_type)]


def _select_record_from_pending(pending_payload: dict[str, Any], content: str) -> dict[str, Any] | None:
    candidates = pending_payload.get("candidates") or []
    index = parse_candidate_selection(content)
    if index is None:
        return None
    return resolve_record_by_index(candidates, index)


def _recent_list_candidates(session_id: str) -> list[dict[str, Any]]:
    payload = latest_recent_candidate_list(session_id, candidate_type="knowledge_base") or {}
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        return []
    return [dict(item) for item in candidates if isinstance(item, dict)]


def _select_record_from_recent_list(session_id: str, content: str) -> dict[str, Any] | None:
    index = parse_candidate_selection(content)
    if index is None:
        return None
    return resolve_record_by_index(_recent_list_candidates(session_id), index)


def _intent_is(intent_hint: dict[str, Any] | None, *intent_names: str) -> bool:
    if not isinstance(intent_hint, dict):
        return False
    return str(intent_hint.get("intent") or "").strip() in set(intent_names)


def _save_recent_candidates(session_id: str, request_id: str, candidates: list[dict[str, Any]]) -> None:
    if not candidates:
        return
    save_recent_candidate_list(
        session_id,
        request_id,
        "knowledge_base",
        [_serializable_record(item) for item in candidates],
    )


def _kb_candidate_not_found_result(
    *,
    route_detail: str,
    reason_code: str,
    clarify_reason: str,
    stop_detail: str,
) -> dict[str, Any]:
    return _build_result(
        reply="我还没有匹配到明确的知识库文件。你可以直接告诉我文件名，或者给我更具体的关键词。",
        route_code="knowledge_base",
        route_detail=route_detail,
        reasons=[reason_code, "candidate_not_found"],
        selected_target=build_selected_target("knowledge_base", None, None, clear_reason=clarify_reason),
        reply_type="clarify",
        stop_code="clarify_waiting_user",
        stop_detail=stop_detail,
        clarify_needed=True,
        clarify_reason=clarify_reason,
    )


def handle_pending_knowledge_base_action(session_id: str, request_id: str, content: str) -> dict[str, Any] | None:
    pending = latest_pending_action(session_id)
    if not pending:
        return None

    action_type = str(pending["action_type"])
    payload = dict(pending["payload"])

    if action_type == "kb_list_scope":
        if not is_kb_list_followup_request(content):
            return None
        resolve_pending_action(pending["id"])
        scope = str(payload.get("scope") or "all")
        records = list_pdf_records(source_type="upload" if scope == "upload" else None)
        scope_label = "你上传并纳入知识库的文件" if scope == "upload" else "知识库"
        return _build_result(
            reply=build_kb_list_reply(records, show_all=True, scope_label=scope_label),
            route_code="knowledge_base",
            route_detail="list_files_full",
            reasons=["knowledge_base_list_followup", "full_list_requested"],
            selected_target=build_selected_target("knowledge_base", None, f"{len(records)} files"),
            reply_type="kb_list",
            stop_code="knowledge_base_list_returned",
            stop_detail="list_files_full",
        )

    if action_type == "kb_rename_candidates":
        selected = _select_record_from_pending(payload, content)
        if not selected:
            return None
        resolve_pending_action(pending["id"])
        if not can_rename_record(selected):
            return _build_result(
                reply=build_rename_unsupported_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="rename_unsupported",
                reasons=["pending_rename_selection_resolved", "base_material_selected"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_rename_unsupported",
                stop_code="knowledge_base_rename_unsupported",
                stop_detail="rename_only_supported_for_uploads",
            )

        new_file_name = str(payload.get("new_file_name") or "").strip()
        if not new_file_name:
            save_pending_action(session_id, "kb_rename_new_name", {"selected": selected}, request_id=request_id)
            return _build_result(
                reply=build_rename_new_name_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="rename_new_name_clarify",
                reasons=["pending_rename_selection_resolved", "new_name_missing"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_new_name_needed",
                clarify_needed=True,
                clarify_reason="need_new_file_name",
            )

        save_pending_action(
            session_id,
            "kb_rename_confirm",
            {"selected": selected, "new_file_name": new_file_name},
            request_id=request_id,
        )
        return _build_result(
            reply=build_rename_confirm_reply(selected["file_name"], new_file_name),
            route_code="knowledge_base",
            route_detail="rename_confirm",
            reasons=["pending_rename_selection_resolved", "new_name_provided"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="rename_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_rename_confirmation",
        )

    if action_type == "kb_rename_new_name":
        selected = dict(payload.get("selected") or {})
        if not selected:
            resolve_pending_action(pending["id"])
            return None

        new_file_name = parse_new_file_name(content)
        if not new_file_name:
            return _build_result(
                reply=build_rename_new_name_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="rename_new_name_clarify",
                reasons=["pending_rename_new_name_still_waiting"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_new_name_needed",
                clarify_needed=True,
                clarify_reason="need_new_file_name",
            )

        resolve_pending_action(pending["id"])
        save_pending_action(
            session_id,
            "kb_rename_confirm",
            {"selected": selected, "new_file_name": new_file_name},
            request_id=request_id,
        )
        return _build_result(
            reply=build_rename_confirm_reply(selected["file_name"], new_file_name),
            route_code="knowledge_base",
            route_detail="rename_confirm",
            reasons=["pending_rename_new_name_resolved"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="rename_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_rename_confirmation",
        )

    if action_type == "kb_rename_confirm":
        selected = dict(payload.get("selected") or {})
        new_file_name = str(payload.get("new_file_name") or "").strip()
        if not selected or not new_file_name:
            resolve_pending_action(pending["id"])
            return None
        if not ("确认改名" in content or is_affirmative(content)):
            return _build_result(
                reply=build_rename_confirm_reply(selected["file_name"], new_file_name),
                route_code="knowledge_base",
                route_detail="rename_confirm",
                reasons=["pending_rename_confirmation_still_waiting"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_rename_confirmation",
            )
        resolve_pending_action(pending["id"])
        rename_result = rename_record(selected, new_file_name)
        update_uploaded_file_reference(
            rename_result["old_stored_path"],
            rename_result["new_file_name"],
            rename_result["new_stored_path"],
        )
        return _build_result(
            reply=f"已把 `{rename_result['old_file_name']}` 改名为 `{rename_result['new_file_name']}`。",
            route_code="knowledge_base",
            route_detail="rename_file",
            reasons=["pending_rename_confirmed"],
            selected_target=build_selected_target(
                "knowledge_base_file",
                rename_result["new_stored_path"],
                rename_result["new_file_name"],
            ),
            reply_type="kb_rename_done",
            stop_code="knowledge_base_file_renamed",
            stop_detail="rename_completed",
        )

    if action_type == "kb_export_candidates":
        selected = _select_record_from_pending(payload, content)
        if not selected:
            return None

        resolve_pending_action(pending["id"])
        if wants_original_file(content):
            path = export_record_path(selected)
            return _build_result(
                reply=f"我把 `{selected['file_name']}` 的原 PDF 发给你。",
                route_code="knowledge_base",
                route_detail="export_original_file",
                reasons=["pending_export_selection_resolved", "original_file_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_export_file",
                stop_code="attachment_ready",
                stop_detail="knowledge_base_original_pdf",
                attachment={"type": "file", "path": str(path), "name": selected["file_name"]},
            )

        save_pending_action(
            session_id,
            "kb_export_selected",
            {"selected": selected},
            request_id=request_id,
        )
        return _build_result(
            reply=build_export_clarify_reply(selected["file_name"]),
            route_code="knowledge_base",
            route_detail="export_action_clarify",
            reasons=["pending_export_selection_resolved", "action_not_clear"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="export_action_needed",
            clarify_needed=True,
            clarify_reason="need_export_action",
        )

    if action_type == "kb_export_selected":
        selected = dict(payload.get("selected") or {})
        if not selected:
            resolve_pending_action(pending["id"])
            return None

        if wants_original_file(content):
            resolve_pending_action(pending["id"])
            path = export_record_path(selected)
            return _build_result(
                reply=f"我把 `{selected['file_name']}` 的原 PDF 发给你。",
                route_code="knowledge_base",
                route_detail="export_original_file",
                reasons=["pending_export_action_resolved", "original_file_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_export_file",
                stop_code="attachment_ready",
                stop_detail="knowledge_base_original_pdf",
                attachment={"type": "file", "path": str(path), "name": selected["file_name"]},
            )

        if wants_summary_and_doc(content):
            resolve_pending_action(pending["id"])
            delegate = (
                f"请只基于知识库中的文件 `{selected['file_name']}` 先生成一份企业微信文档，"
                "然后在聊天里给我一句摘要。不要处理其他文件。"
            )
            return _build_result(
                reply=f"我会先基于 `{selected['file_name']}` 生成文档，然后再回一句摘要。",
                route_code="knowledge_base",
                route_detail="selected_file_summary_and_doc",
                reasons=["pending_export_action_resolved", "summary_and_doc_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_selected_doc_task",
                stop_code="delegate_to_agent",
                stop_detail="selected_file_summary_and_doc",
                delegate_message=delegate,
            )

        if wants_generate_doc(content):
            resolve_pending_action(pending["id"])
            delegate = f"请只基于知识库中的文件 `{selected['file_name']}` 生成一份企业微信文档，不要处理其他文件。"
            return _build_result(
                reply=f"我会基于 `{selected['file_name']}` 生成一份文档。",
                route_code="knowledge_base",
                route_detail="selected_file_generate_doc",
                reasons=["pending_export_action_resolved", "generate_doc_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_selected_doc_task",
                stop_code="delegate_to_agent",
                stop_detail="selected_file_generate_doc",
                delegate_message=delegate,
            )

        if wants_summary(content):
            resolve_pending_action(pending["id"])
            save_pending_action(
                session_id,
                "kb_summary_format",
                {"selected": selected},
                request_id=request_id,
            )
            return _build_result(
                reply=f"你是希望我直接在聊天里总结 `{selected['file_name']}`，还是顺手生成一份文档？",
                route_code="knowledge_base",
                route_detail="summary_format_clarify",
                reasons=["pending_export_action_resolved", "summary_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="summary_format_needed",
                clarify_needed=True,
                clarify_reason="need_summary_format",
            )
        return _build_result(
            reply=build_export_clarify_reply(selected["file_name"]),
            route_code="knowledge_base",
            route_detail="export_action_clarify",
            reasons=["pending_export_action_still_waiting"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="export_action_needed",
            clarify_needed=True,
            clarify_reason="need_export_action",
        )

    if action_type == "kb_summary_format":
        selected = dict(payload.get("selected") or {})
        if not selected:
            resolve_pending_action(pending["id"])
            return None

        if wants_summary_and_doc(content) or wants_generate_doc(content):
            resolve_pending_action(pending["id"])
            delegate = (
                f"请只基于知识库中的文件 `{selected['file_name']}` 生成一份企业微信文档，"
                "然后在聊天里给一句简短摘要。"
            )
            return _build_result(
                reply=f"我会先基于 `{selected['file_name']}` 生成文档，然后补一句摘要。",
                route_code="knowledge_base",
                route_detail="summary_format_doc",
                reasons=["pending_summary_format_resolved", "doc_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_selected_doc_task",
                stop_code="delegate_to_agent",
                stop_detail="summary_then_doc",
                delegate_message=delegate,
            )

        if wants_summary(content):
            resolve_pending_action(pending["id"])
            delegate = f"请只基于知识库中的文件 `{selected['file_name']}` 在聊天里给我一个简短摘要，不要生成文档。"
            return _build_result(
                reply=f"我先直接在聊天里总结 `{selected['file_name']}`。",
                route_code="knowledge_base",
                route_detail="summary_format_chat",
                reasons=["pending_summary_format_resolved", "chat_summary_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_selected_summary_task",
                stop_code="delegate_to_agent",
                stop_detail="chat_summary_only",
                delegate_message=delegate,
            )
        return _build_result(
            reply=f"你是希望我直接在聊天里总结 `{selected['file_name']}`，还是顺手生成一份文档？",
            route_code="knowledge_base",
            route_detail="summary_format_clarify",
            reasons=["pending_summary_format_still_waiting"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="summary_format_needed",
            clarify_needed=True,
            clarify_reason="need_summary_format",
        )

    if action_type == "kb_delete_candidates":
        selected = _select_record_from_pending(payload, content)
        if not selected:
            return None
        resolve_pending_action(pending["id"])
        save_pending_action(session_id, "kb_delete_confirm", {"selected": selected}, request_id=request_id)
        return _build_result(
            reply=build_delete_confirm_reply(selected["file_name"]),
            route_code="knowledge_base",
            route_detail="delete_confirm",
            reasons=["pending_delete_selection_resolved"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="delete_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_delete_confirmation",
        )

    if action_type == "kb_delete_confirm":
        selected = dict(payload.get("selected") or {})
        if not selected:
            resolve_pending_action(pending["id"])
            return None
        if not ("确认删除" in content or is_affirmative(content)):
            return _build_result(
                reply=build_delete_confirm_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="delete_confirm",
                reasons=["pending_delete_confirmation_still_waiting"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="delete_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_delete_confirmation",
            )
        resolve_pending_action(pending["id"])
        delete_record(selected)
        return _build_result(
            reply=f"已删除 `{selected['file_name']}`。",
            route_code="knowledge_base",
            route_detail="delete_file",
            reasons=["pending_delete_confirmed"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="kb_delete_done",
            stop_code="knowledge_base_file_deleted",
            stop_detail="delete_completed",
        )

    if action_type == "kb_related_candidates":
        selected = _select_record_from_pending(payload, content)
        if not selected:
            return None
        resolve_pending_action(pending["id"])

        if wants_original_file(content):
            path = export_record_path(selected)
            return _build_result(
                reply=f"我把 `{selected['file_name']}` 的原 PDF 发给你。",
                route_code="knowledge_base",
                route_detail="related_candidate_export_file",
                reasons=["related_candidate_selected", "original_file_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_export_file",
                stop_code="attachment_ready",
                stop_detail="knowledge_base_original_pdf",
                attachment={"type": "file", "path": str(path), "name": selected["file_name"]},
            )

        if candidate_action_is_clear(content):
            save_pending_action(session_id, "kb_export_selected", {"selected": selected}, request_id=request_id)
            return handle_pending_knowledge_base_action(session_id, request_id, content)

        save_pending_action(session_id, "kb_export_selected", {"selected": selected}, request_id=request_id)
        return _build_result(
            reply=f"你想针对 `{selected['file_name']}` 做什么？可以是发原文件、给摘要，或者生成文档。",
            route_code="knowledge_base",
            route_detail="related_candidate_action_clarify",
            reasons=["related_candidate_selected", "action_not_clear"],
            selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="related_candidate_action_needed",
            clarify_needed=True,
            clarify_reason="need_related_candidate_action",
        )

    return None


def handle_knowledge_base_request(
    session_id: str,
    request_id: str,
    content: str,
    *,
    intent_hint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    pending_result = handle_pending_knowledge_base_action(session_id, request_id, content)
    if pending_result:
        return pending_result

    if is_kb_list_followup_request(content):
        latest_route = latest_route_selection(session_id)
        route_code = str((latest_route or {}).get("route_selected", {}).get("code") or "")
        route_detail = str((latest_route or {}).get("route_selected", {}).get("detail") or "")
        if route_code == "knowledge_base" and route_detail in {"list_files", "list_uploaded_files"}:
            source_type = "upload" if route_detail == "list_uploaded_files" else None
            records = list_pdf_records(source_type=source_type)
            scope_label = "你上传并纳入知识库的文件" if source_type == "upload" else "知识库"
            _save_recent_candidates(session_id, request_id, records)
            return _build_result(
                reply=build_kb_list_reply(records, show_all=True, scope_label=scope_label),
                route_code="knowledge_base",
                route_detail=f"{route_detail}_followup_full",
                reasons=["knowledge_base_list_followup", "full_list_requested"],
                selected_target=build_selected_target("knowledge_base", None, f"{len(records)} files"),
                reply_type="kb_list",
                stop_code="knowledge_base_list_returned",
                stop_detail="list_files_full_followup",
            )

    if is_kb_list_request(content) or _intent_is(intent_hint, "kb.list"):
        show_all = wants_full_list(content)
        records = list_pdf_records()
        if records and not show_all and len(records) > 10:
            save_pending_action(session_id, "kb_list_scope", {"scope": "all"}, request_id=request_id)
            _save_recent_candidates(session_id, request_id, records[:10])
        else:
            _save_recent_candidates(session_id, request_id, records)
        return _build_result(
            reply=build_kb_list_reply(
                records,
                show_only_count=wants_brief_answer(content),
                show_all=show_all,
            ),
            route_code="knowledge_base",
            route_detail="list_files_full" if show_all else "list_files",
            reasons=["knowledge_base_list_request", "full_list_requested" if show_all else "default_list_limit"],
            selected_target=build_selected_target("knowledge_base", None, f"{len(records)} files"),
            reply_type="kb_list",
            stop_code="knowledge_base_list_returned",
            stop_detail="list_files_full" if show_all else "list_files",
        )

    if is_uploaded_file_list_request(content) or _intent_is(intent_hint, "kb.list_uploads"):
        records = list_pdf_records(source_type="upload")
        show_all = wants_full_list(content)
        if records and not show_all and len(records) > 10:
            save_pending_action(session_id, "kb_list_scope", {"scope": "upload"}, request_id=request_id)
            _save_recent_candidates(session_id, request_id, records[:10])
        else:
            _save_recent_candidates(session_id, request_id, records)
        return _build_result(
            reply=build_kb_list_reply(
                records,
                show_only_count=wants_brief_answer(content),
                show_all=show_all,
                scope_label="你上传并纳入知识库的文件",
            ),
            route_code="knowledge_base",
            route_detail="list_uploaded_files_full" if show_all else "list_uploaded_files",
            reasons=["uploaded_file_list_request", "full_list_requested" if show_all else "default_list_limit"],
            selected_target=build_selected_target("knowledge_base", None, f"{len(records)} upload files"),
            reply_type="kb_list",
            stop_code="knowledge_base_list_returned",
            stop_detail="list_uploaded_files_full" if show_all else "list_uploaded_files",
        )

    if asks_recent_uploaded_file(content) or asks_upload_label(content):
        latest = latest_uploaded_file(session_id)
        fallback = None if latest else build_recent_upload_fallback_candidates()
        return _build_result(
            reply=build_recent_upload_reply(latest, fallback),
            route_code="knowledge_base",
            route_detail="recent_uploaded_lookup",
            reasons=["recent_uploaded_file_request"],
            selected_target=build_selected_target(
                "uploaded_file" if latest else "knowledge_base",
                str(latest["stored_path"]) if latest else None,
                str(latest["file_name"]) if latest else None,
                clear_reason=None if latest else "recent_upload_not_found",
            ),
            reply_type="kb_recent_upload",
            stop_code="recent_upload_lookup_done",
            stop_detail="recent_upload_lookup",
        )

    if is_export_request(content) or _intent_is(intent_hint, "kb.export"):
        candidates = _select_candidates_from_content(content, limit=5)
        if not candidates:
            recent_selected = _select_record_from_recent_list(session_id, content)
            if recent_selected:
                candidates = [_serializable_record(recent_selected)]
        if not candidates:
            return _kb_candidate_not_found_result(
                route_detail="export_candidate_not_found",
                reason_code="knowledge_base_export_request",
                clarify_reason="need_export_candidate",
                stop_detail="need_export_candidate",
            )

        selected = candidates[0] if len(candidates) == 1 else None
        if selected and wants_original_file(content):
            path = export_record_path(selected)
            return _build_result(
                reply=f"我把 `{selected['file_name']}` 的原 PDF 发给你。",
                route_code="knowledge_base",
                route_detail="export_original_file",
                reasons=["knowledge_base_export_request", "single_candidate", "original_file_requested"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_export_file",
                stop_code="attachment_ready",
                stop_detail="knowledge_base_original_pdf",
                attachment={"type": "file", "path": str(path), "name": selected["file_name"]},
            )

        if selected:
            save_pending_action(session_id, "kb_export_selected", {"selected": selected}, request_id=request_id)
            return _build_result(
                reply=build_export_clarify_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="export_action_clarify",
                reasons=["knowledge_base_export_request", "single_candidate", "action_not_clear"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="export_action_needed",
                clarify_needed=True,
                clarify_reason="need_export_action",
            )

        save_pending_action(session_id, "kb_export_candidates", {"candidates": candidates[:3]}, request_id=request_id)
        _save_recent_candidates(session_id, request_id, candidates[:3])
        lines = ["我先匹配到了这些候选文件："]
        for index, item in enumerate(candidates[:3], start=1):
            lines.append(f"{index}. {item['file_name']}：{item.get('match_reason') or '文件名相关'}")
        lines.append("请告诉我你要哪一篇，以及是要原文件、摘要，还是生成文档。")
        return _build_result(
            reply="\n".join(lines),
            route_code="knowledge_base",
            route_detail="export_candidates",
            reasons=["knowledge_base_export_request", "multiple_candidates"],
            selected_target=build_selected_target("knowledge_base", None, candidates[0]["file_name"]),
            reply_type="kb_candidates",
            stop_code="candidate_list_returned",
            stop_detail="export_candidates_ready",
            clarify_needed=True,
            clarify_reason="need_candidate_selection",
        )

    if is_delete_request(content) or _intent_is(intent_hint, "kb.delete"):
        candidates = _select_candidates_from_content(content, limit=5)
        if not candidates:
            recent_selected = _select_record_from_recent_list(session_id, content)
            if recent_selected:
                candidates = [_serializable_record(recent_selected)]
        if not candidates:
            return _kb_candidate_not_found_result(
                route_detail="delete_candidate_not_found",
                reason_code="knowledge_base_delete_request",
                clarify_reason="need_delete_candidate",
                stop_detail="need_delete_candidate",
            )

        selected = candidates[0] if len(candidates) == 1 else None
        if selected:
            save_pending_action(session_id, "kb_delete_confirm", {"selected": selected}, request_id=request_id)
            return _build_result(
                reply=build_delete_confirm_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="delete_confirm",
                reasons=["knowledge_base_delete_request", "single_candidate"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="delete_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_delete_confirmation",
            )

        save_pending_action(session_id, "kb_delete_candidates", {"candidates": candidates[:3]}, request_id=request_id)
        _save_recent_candidates(session_id, request_id, candidates[:3])
        lines = ["我先匹配到了这些候选文件："]
        for index, item in enumerate(candidates[:3], start=1):
            lines.append(f"{index}. {item['file_name']}：{item.get('match_reason') or '文件名相关'}")
        lines.append("请告诉我你要删除哪一篇。")
        return _build_result(
            reply="\n".join(lines),
            route_code="knowledge_base",
            route_detail="delete_candidates",
            reasons=["knowledge_base_delete_request", "multiple_candidates"],
            selected_target=build_selected_target("knowledge_base", None, candidates[0]["file_name"]),
            reply_type="kb_candidates",
            stop_code="candidate_list_returned",
            stop_detail="delete_candidates_ready",
            clarify_needed=True,
            clarify_reason="need_candidate_selection",
        )

    if is_related_doc_query(content) or is_best_doc_query(content) or _intent_is(intent_hint, "kb.related"):
        candidates = _select_candidates_from_content(content, limit=5)
        if not candidates:
            return _build_result(
                reply="我没有从文件名和元信息里匹配到明确候选。你可以给我更具体的关键词，或者直接说你想找哪类文档。",
                route_code="knowledge_base",
                route_detail="related_candidates_not_found",
                reasons=["knowledge_base_related_query", "metadata_match_insufficient"],
                selected_target=build_selected_target("knowledge_base", None, None, clear_reason="no_candidate_found"),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="need_more_keywords",
                clarify_needed=True,
                clarify_reason="metadata_match_insufficient",
            )

        reasons = [str(item.get("match_reason") or "文件名相关") for item in candidates[:3]]
        recommended_index = 0 if is_best_doc_query(content) else None
        intro = (
            "我先给你一个初步判断：知识库里大概率有相关材料。"
            if is_related_doc_query(content)
            else None
        )
        save_pending_action(
            session_id,
            "kb_related_candidates",
            {"candidates": candidates[:3]},
            request_id=request_id,
        )
        _save_recent_candidates(session_id, request_id, candidates[:3])
        return _build_result(
            reply=build_related_candidates_reply(
                query=content,
                candidates=candidates,
                reasons=reasons,
                recommended_index=recommended_index,
                intro=intro,
            ),
            route_code="knowledge_base",
            route_detail="related_candidates",
            reasons=["knowledge_base_related_query"],
            selected_target=build_selected_target("knowledge_base", None, candidates[0]["file_name"]),
            reply_type="kb_candidates",
            stop_code="candidate_list_returned",
            stop_detail="related_candidates_ready",
            clarify_needed=True,
            clarify_reason="need_candidate_selection",
        )

    if is_rename_request(content) or _intent_is(intent_hint, "kb.rename"):
        candidates = _select_candidates_from_content(content, limit=5)
        new_file_name = parse_new_file_name(content)
        if not candidates:
            recent_selected = _select_record_from_recent_list(session_id, content)
            if recent_selected:
                candidates = [_serializable_record(recent_selected)]
        if not candidates:
            return _build_result(
                reply=build_rename_intro_reply(),
                route_code="knowledge_base",
                route_detail="rename_intro",
                reasons=["knowledge_base_rename_request", "candidate_not_found", "intent_or_text_detected"],
                selected_target=build_selected_target("knowledge_base", None, None, clear_reason="rename_target_missing"),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_target_needed",
                clarify_needed=True,
                clarify_reason="need_rename_target_and_name",
            )

        selected = candidates[0] if len(candidates) == 1 else None
        if selected and not can_rename_record(selected):
            return _build_result(
                reply=build_rename_unsupported_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="rename_unsupported",
                reasons=["knowledge_base_rename_request", "base_material_selected"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="kb_rename_unsupported",
                stop_code="knowledge_base_rename_unsupported",
                stop_detail="rename_only_supported_for_uploads",
            )

        if selected and new_file_name:
            save_pending_action(
                session_id,
                "kb_rename_confirm",
                {"selected": selected, "new_file_name": new_file_name},
                request_id=request_id,
            )
            return _build_result(
                reply=build_rename_confirm_reply(selected["file_name"], new_file_name),
                route_code="knowledge_base",
                route_detail="rename_confirm",
                reasons=["knowledge_base_rename_request", "single_candidate", "new_name_provided"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_rename_confirmation",
            )

        if selected:
            save_pending_action(session_id, "kb_rename_new_name", {"selected": selected}, request_id=request_id)
            return _build_result(
                reply=build_rename_new_name_reply(selected["file_name"]),
                route_code="knowledge_base",
                route_detail="rename_new_name_clarify",
                reasons=["knowledge_base_rename_request", "single_candidate", "new_name_missing"],
                selected_target=build_selected_target("knowledge_base_file", selected["stored_path"], selected["file_name"]),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="rename_new_name_needed",
                clarify_needed=True,
                clarify_reason="need_new_file_name",
            )

        save_pending_action(
            session_id,
            "kb_rename_candidates",
            {"candidates": candidates[:3], "new_file_name": new_file_name},
            request_id=request_id,
        )
        _save_recent_candidates(session_id, request_id, candidates[:3])
        return _build_result(
            reply=build_rename_candidates_reply(candidates[:3]),
            route_code="knowledge_base",
            route_detail="rename_candidates",
            reasons=["knowledge_base_rename_request", "multiple_candidates"],
            selected_target=build_selected_target("knowledge_base", None, candidates[0]["file_name"]),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="rename_candidate_selection_needed",
            clarify_needed=True,
            clarify_reason="need_rename_target_selection",
        )

    if is_kb_file_management_intent(intent_hint):
        return _kb_candidate_not_found_result(
            route_detail="knowledge_base_intent_unresolved",
            reason_code=str(intent_hint.get("intent") or "knowledge_base_intent"),
            clarify_reason="need_knowledge_base_target",
            stop_detail="need_knowledge_base_target",
        )

    return None
