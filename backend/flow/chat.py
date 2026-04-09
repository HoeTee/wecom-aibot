from __future__ import annotations

from typing import Any

from backend.agent import Agent
from backend.caps.documents import load_system_prompt
from backend.policy.chat import (
    build_doc_binding_updated_payload,
    build_memory_loaded_payload,
    build_reply_generated_payload,
    build_request_received_payload,
    build_runtime_ready_payload,
    build_stop_reason_payload,
    select_chat_route,
)
from backend.policy.routing import maybe_short_circuit_upload_followup
from backend.runtime import MCPHost, load_mcp_server_configs_from_env
from backend.state.store import (
    build_session_id,
    generate_request_id,
    load_memory_context,
    persist_doc_binding_from_tool_result,
    save_flow_event,
    save_tool_call,
    save_turn,
)


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
        build_request_received_payload("text", content_preview=content[:200]),
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
            build_reply_generated_payload("ack_existing_upload", reply),
        )
        emit_flow(
            "flow",
            "stop_reason",
            build_stop_reason_payload("short_circuit", "upload_followup_confirmation"),
        )
        return reply

    include_bound_doc, route_payload = select_chat_route(content)
    emit_flow(
        "flow",
        "route_selected",
        route_payload,
    )

    memory_context = load_memory_context(session_id, include_bound_doc=include_bound_doc)
    emit_flow(
        "state",
        "memory_loaded",
        build_memory_loaded_payload(include_bound_doc, bool(memory_context)),
    )

    def on_tool_result(tool_name: str, args_dict: dict[str, Any], result_text: str) -> None:
        save_tool_call(session_id, tool_name, args_dict, result_text, request_id=request_id)
        binding = persist_doc_binding_from_tool_result(
            session_id=session_id,
            request_id=request_id,
            tool_name=tool_name,
            args_dict=args_dict,
            result_text=result_text,
            last_user_text=content,
        )
        if not binding:
            return
        emit_flow(
            "state",
            "doc_binding_updated",
            build_doc_binding_updated_payload(binding),
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
                build_runtime_ready_payload(len(mcp_runtime.tools), len(server_configs)),
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
            build_reply_generated_payload("assistant_final", reply),
        )
        return reply
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()
