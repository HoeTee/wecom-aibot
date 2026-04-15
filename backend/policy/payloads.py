from __future__ import annotations

from typing import Any


def build_selected_target(
    target_type: str,
    primary_id: str | None,
    display_name: str | None,
    clear_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "primary_id": primary_id,
        "display_name": display_name,
        "clear_reason": clear_reason,
    }


def build_route_payload(
    route_code: str,
    route_detail: str,
    reasons: list[str],
    selected_target: dict[str, Any],
    guard_hits: list[dict[str, str]] | None = None,
    clarify_needed: bool = False,
    clarify_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "route_selected": {"code": route_code, "detail": route_detail},
        "route_reason": reasons,
        "selected_target": selected_target,
        "guard_hit": guard_hits or [],
        "clarify_needed": {
            "needed": clarify_needed,
            "clarify_reason": clarify_reason,
        },
    }


def build_request_received_payload(message_type: str, *, content_preview: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"message_type": message_type}
    if content_preview is not None:
        payload["content_preview"] = content_preview
    return payload


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
