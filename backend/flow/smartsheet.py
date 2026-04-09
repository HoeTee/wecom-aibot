from __future__ import annotations

from typing import Any

from backend.caps.knowledge_base import list_pdf_records
from backend.caps.smartsheet import (
    add_smartsheet_fields,
    add_smartsheet_records,
    add_smartsheet_sheet,
    create_smartsheet,
    get_smartsheet_sheets,
)
from backend.policy.routing import build_route_payload, build_selected_target
from backend.policy.smartsheet import (
    build_smartsheet_auth_expired_reply,
    build_smartsheet_partial_reply,
    build_smartsheet_success_reply,
    detect_smartsheet_request,
    infer_smartsheet_name,
    infer_smartsheet_source_scope,
    is_authorization_expired,
)
from backend.runtime import MCPHost


def _build_result(
    *,
    reply: str,
    route_detail: str,
    reasons: list[str],
    selected_target: dict[str, Any],
    reply_type: str,
    stop_code: str,
    stop_detail: str,
    tool_calls: list[dict[str, Any]] | None = None,
    guard_hits: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "route_payload": build_route_payload(
            route_code="smartsheet",
            route_detail=route_detail,
            reasons=reasons,
            selected_target=selected_target,
            guard_hits=guard_hits,
        ),
        "reply_type": reply_type,
        "stop_reason": {"code": stop_code, "detail": stop_detail, "layer": "flow"},
        "tool_calls": tool_calls or [],
    }


def _tool_call_entry(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": str(payload.get("tool_name") or ""),
        "args_dict": dict(payload.get("tool_args") or {}),
        "result_text": str(payload.get("tool_result_raw") or ""),
    }


def _default_fields() -> list[dict[str, Any]]:
    return [
        {"field_title": "文件名", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "来源类型", "field_type": "FIELD_TYPE_TEXT"},
        {"field_title": "知识库路径", "field_type": "FIELD_TYPE_TEXT"},
    ]


def _build_record_values(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "文件名": [{"type": "text", "text": str(record.get("file_name") or "")}],
        "来源类型": [{"type": "text", "text": str(record.get("source_type") or "")}],
        "知识库路径": [{"type": "text", "text": str(record.get("stored_path") or "")}],
    }


async def handle_smartsheet_request(
    session_id: str,
    request_id: str,
    content: str,
    *,
    host: MCPHost | None,
    intent_hint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del session_id, request_id

    if not detect_smartsheet_request(content, intent_hint):
        return None

    if host is None:
        return _build_result(
            reply="当前智能表格工具暂时不可用，请稍后再试。",
            route_detail="runtime_unavailable",
            reasons=["smartsheet_requested", "runtime_unavailable"],
            selected_target=build_selected_target("smartsheet", None, None, clear_reason="runtime_unavailable"),
            reply_type="error",
            stop_code="runtime_unavailable",
            stop_detail="smartsheet_tools_required",
            guard_hits=[{"code": "runtime_unavailable", "detail": "smartsheet_tools_required"}],
        )

    source_scope = infer_smartsheet_source_scope(content, intent_hint)
    doc_name = infer_smartsheet_name(content, intent_hint)
    selected_target = build_selected_target("smartsheet", None, doc_name)
    tool_calls: list[dict[str, Any]] = []

    create_payload = await create_smartsheet(host, doc_name)
    tool_calls.append(_tool_call_entry(create_payload))
    doc_id = str(create_payload.get("doc_id") or "").strip() or None
    doc_url = str(create_payload.get("doc_url") or "").strip() or None
    if doc_id:
        selected_target = build_selected_target("smartsheet", doc_id, doc_name)

    if is_authorization_expired(create_payload):
        return _build_result(
            reply=build_smartsheet_auth_expired_reply(create_payload),
            route_detail="create_auth_expired",
            reasons=["smartsheet_requested", "authorization_expired"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="authorization_expired",
            tool_calls=tool_calls,
            guard_hits=[{"code": "authorization_expired", "detail": "wecom_docs"}],
        )

    if not doc_id:
        return _build_result(
            reply=build_smartsheet_partial_reply(doc_name, reason="创建后未返回 doc_id。", doc_url=doc_url),
            route_detail="create_missing_doc_id",
            reasons=["smartsheet_requested", "doc_id_missing"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="doc_id_missing",
            tool_calls=tool_calls,
        )

    records = list_pdf_records() if source_scope == "knowledge_base" else []
    if not records:
        return _build_result(
            reply=build_smartsheet_success_reply(doc_name, row_count=0, doc_url=doc_url),
            route_detail="create_smartsheet_only",
            reasons=["smartsheet_requested", "manual_or_empty_source"],
            selected_target=selected_target,
            reply_type="smartsheet_created",
            stop_code="smartsheet_created",
            stop_detail="create_only",
            tool_calls=tool_calls,
        )

    sheets_payload = await get_smartsheet_sheets(host, doc_id=doc_id)
    tool_calls.append(_tool_call_entry(sheets_payload))
    if is_authorization_expired(sheets_payload):
        return _build_result(
            reply=build_smartsheet_auth_expired_reply(sheets_payload),
            route_detail="sheet_lookup_auth_expired",
            reasons=["smartsheet_requested", "authorization_expired"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="authorization_expired",
            tool_calls=tool_calls,
            guard_hits=[{"code": "authorization_expired", "detail": "wecom_docs"}],
        )

    sheet_id = str(sheets_payload.get("sheet_id") or "").strip() or None
    if not sheet_id:
        add_sheet_payload = await add_smartsheet_sheet(host, doc_id=doc_id, title="知识库整理")
        tool_calls.append(_tool_call_entry(add_sheet_payload))
        if is_authorization_expired(add_sheet_payload):
            return _build_result(
                reply=build_smartsheet_auth_expired_reply(add_sheet_payload),
                route_detail="add_sheet_auth_expired",
                reasons=["smartsheet_requested", "authorization_expired"],
                selected_target=selected_target,
                reply_type="error",
                stop_code="tool_error",
                stop_detail="authorization_expired",
                tool_calls=tool_calls,
                guard_hits=[{"code": "authorization_expired", "detail": "wecom_docs"}],
            )
        sheet_id = str(add_sheet_payload.get("sheet_id") or "").strip() or None

    if not sheet_id:
        return _build_result(
            reply=build_smartsheet_partial_reply(doc_name, reason="创建后未拿到 sheet_id。", doc_url=doc_url),
            route_detail="sheet_id_missing",
            reasons=["smartsheet_requested", "sheet_id_missing"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="sheet_id_missing",
            tool_calls=tool_calls,
        )

    fields_payload = await add_smartsheet_fields(host, doc_id=doc_id, sheet_id=sheet_id, fields=_default_fields())
    tool_calls.append(_tool_call_entry(fields_payload))
    if is_authorization_expired(fields_payload):
        return _build_result(
            reply=build_smartsheet_auth_expired_reply(fields_payload),
            route_detail="add_fields_auth_expired",
            reasons=["smartsheet_requested", "authorization_expired"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="authorization_expired",
            tool_calls=tool_calls,
            guard_hits=[{"code": "authorization_expired", "detail": "wecom_docs"}],
        )

    add_records_payload = await add_smartsheet_records(
        host,
        doc_id=doc_id,
        sheet_id=sheet_id,
        records=[{"values": _build_record_values(record)} for record in records],
    )
    tool_calls.append(_tool_call_entry(add_records_payload))
    if is_authorization_expired(add_records_payload):
        return _build_result(
            reply=build_smartsheet_auth_expired_reply(add_records_payload),
            route_detail="add_records_auth_expired",
            reasons=["smartsheet_requested", "authorization_expired"],
            selected_target=selected_target,
            reply_type="error",
            stop_code="tool_error",
            stop_detail="authorization_expired",
            tool_calls=tool_calls,
            guard_hits=[{"code": "authorization_expired", "detail": "wecom_docs"}],
        )

    return _build_result(
        reply=build_smartsheet_success_reply(doc_name, row_count=len(records), doc_url=doc_url),
        route_detail="create_from_knowledge_base",
        reasons=["smartsheet_requested", "knowledge_base_as_source"],
        selected_target=selected_target,
        reply_type="smartsheet_created",
        stop_code="smartsheet_created",
        stop_detail="records_added",
        tool_calls=tool_calls,
    )
