from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent import Agent
from backend.policy.routing import (
    build_route_payload,
    build_selected_target,
    is_fresh_document_request,
    maybe_short_circuit_upload_followup,
)
from backend.runtime import MCPHost, load_mcp_server_configs_from_env
from backend.state.store import (
    build_session_id,
    extract_doc_binding,
    generate_request_id,
    load_memory_context,
    save_flow_event,
    save_tool_call,
    save_turn,
    upsert_session_doc,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "system" / "assistant_v1.md"


def load_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


async def run_chat(payload: dict[str, Any]) -> str:
    mcp_runtime = None
    content = str(payload.get("content", "")).strip()
    request_id = str(payload.get("requestId") or generate_request_id())
    session_id = build_session_id(
        chat_type=str(payload.get("chatType", "")),
        chat_id=payload.get("chatId"),
        user_id=str(payload.get("userId", "")),
    )

    def emit_flow(layer_at_event: str, event_name: str, event_payload: dict[str, Any]) -> None:
        save_flow_event(session_id, request_id, layer_at_event, event_name, event_payload)

    emit_flow(
        "entry",
        "request_received",
        {"message_type": "text", "content_preview": content[:200]},
    )

    short_circuit = maybe_short_circuit_upload_followup(session_id, content)
    if short_circuit:
        reply, route_payload = short_circuit
        emit_flow("flow", "route_selected", route_payload)
        save_turn(session_id, "user", content, request_id=request_id)
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow(
            "entry",
            "reply_generated",
            {"reply_type": "ack_existing_upload", "reply_preview": reply[:200]},
        )
        emit_flow(
            "flow",
            "stop_reason",
            {"code": "short_circuit", "detail": "upload_followup_confirmation", "layer": "flow"},
        )
        return reply

    include_bound_doc = not is_fresh_document_request(content)
    route_detail = "fresh_document_request" if not include_bound_doc else "default_agent_flow"
    route_reason = ["fresh_document_request"] if not include_bound_doc else ["default_text_message"]
    emit_flow(
        "flow",
        "route_selected",
        build_route_payload(
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
        ),
    )

    memory_context = load_memory_context(session_id, include_bound_doc=include_bound_doc)
    emit_flow(
        "state",
        "memory_loaded",
        {"include_bound_doc": include_bound_doc, "has_memory_context": bool(memory_context)},
    )

    def on_tool_result(tool_name: str, args_dict: dict[str, Any], result_text: str) -> None:
        save_tool_call(session_id, tool_name, args_dict, result_text, request_id=request_id)
        binding = extract_doc_binding(tool_name, args_dict, result_text)
        if not binding:
            return
        upsert_session_doc(
            session_id=session_id,
            doc_id=str(binding["doc_id"] or ""),
            doc_url=binding["doc_url"],
            doc_name=binding["doc_name"],
            last_tool_name=tool_name,
            last_user_text=content,
            request_id=request_id,
        )
        emit_flow(
            "state",
            "doc_binding_updated",
            {
                "selected_target": build_selected_target(
                    "document",
                    str(binding["doc_id"] or ""),
                    binding["doc_name"] or binding["doc_url"] or "",
                ),
            },
        )

    try:
        save_turn(session_id, "user", content, request_id=request_id)

        server_configs = load_mcp_server_configs_from_env()
        if server_configs:
            mcp_runtime = MCPHost(server_configs)
            await mcp_runtime.connect_all()
            emit_flow(
                "runtime",
                "tool_runtime_ready",
                {"tool_count": len(mcp_runtime.tools), "server_count": len(server_configs)},
            )

        agent = Agent(
            name="WeComBackendAgent",
            system_prompt=load_system_prompt(),
            mcp_client=mcp_runtime,
            memory_context=memory_context,
            on_tool_result=on_tool_result,
            on_flow_event=lambda event_name, event_payload: emit_flow("flow", event_name, event_payload),
        )
        reply = await agent.chat(content)
        reply = reply or "No response generated."
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow(
            "entry",
            "reply_generated",
            {"reply_type": "assistant_final", "reply_preview": reply[:200]},
        )
        return reply
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()
