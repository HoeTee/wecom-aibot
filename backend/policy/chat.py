from __future__ import annotations

from typing import Any

from backend.policy.document import is_fresh_document_request
from backend.policy.routing import build_route_payload, build_selected_target


def build_request_received_payload(message_type: str, *, content_preview: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"message_type": message_type}
    if content_preview is not None:
        payload["content_preview"] = content_preview
    return payload


def select_chat_route(content: str) -> tuple[bool, dict[str, Any]]:
    include_bound_doc = not is_fresh_document_request(content)
    route_detail = "fresh_document_request" if not include_bound_doc else "default_agent_flow"
    route_reason = ["fresh_document_request"] if not include_bound_doc else ["default_text_message"]
    route_payload = build_route_payload(
        route_code="agent_chat",
        route_detail=route_detail,
        reasons=route_reason,
        selected_target=build_selected_target(
            "document" if include_bound_doc else "none",
            None,
            None,
            clear_reason="fresh_document_request" if not include_bound_doc else "no_target_selected_at_route_time",
        ),
        clarify_needed=False,
    )
    return include_bound_doc, route_payload


def build_memory_loaded_payload(include_bound_doc: bool, has_memory_context: bool) -> dict[str, Any]:
    return {
        "include_bound_doc": include_bound_doc,
        "has_memory_context": has_memory_context,
    }


def build_doc_binding_updated_payload(binding: dict[str, str | None]) -> dict[str, Any]:
    return {
        "selected_target": build_selected_target(
            "document",
            str(binding["doc_id"] or ""),
            binding["doc_name"] or binding["doc_url"] or "",
        )
    }


def build_runtime_ready_payload(tool_count: int, server_count: int) -> dict[str, Any]:
    return {"tool_count": tool_count, "server_count": server_count}


def build_reply_generated_payload(reply_type: str, reply: str) -> dict[str, Any]:
    return {"reply_type": reply_type, "reply_preview": str(reply or "")[:200]}


def build_stop_reason_payload(code: str, detail: str, layer: str = "flow") -> dict[str, Any]:
    return {"code": code, "detail": detail, "layer": layer}
