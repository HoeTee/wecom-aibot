from __future__ import annotations

from typing import Any

from backend.agent import Agent
from backend.caps.documents import load_system_prompt
from backend.flow.document_ops import handle_document_operation_request
from backend.flow.knowledge_base import handle_knowledge_base_request
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


ChatResult = dict[str, Any]


async def run_chat(payload: dict[str, Any]) -> ChatResult:
    mcp_runtime: MCPHost | None = None
    content = str(payload.get("content", "")).strip()
    request_id = str(payload.get("requestId") or generate_request_id())
    session_id = build_session_id(
        chat_type=str(payload.get("chatType", "")),
        chat_id=payload.get("chatId"),
        user_id=str(payload.get("userId", "")),
    )
    user_turn_saved = False

    def emit_flow(layer_at_event: str, event_name: str, event_payload: dict[str, Any]) -> None:
        save_flow_event(session_id, request_id, layer_at_event, event_name, event_payload)

    def save_user_turn_once(user_text: str) -> None:
        nonlocal user_turn_saved
        if user_turn_saved:
            return
        save_turn(session_id, "user", user_text, request_id=request_id)
        user_turn_saved = True

    def finalize_direct(result: dict[str, Any]) -> ChatResult:
        reply = str(result["reply"])
        save_user_turn_once(content)
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow("flow", "route_selected", dict(result["route_payload"]))
        emit_flow("entry", "reply_generated", build_reply_generated_payload(str(result["reply_type"]), reply))
        emit_flow("flow", "stop_reason", dict(result["stop_reason"]))
        response: ChatResult = {"reply": reply, "requestId": request_id}
        attachment = result.get("attachment")
        if attachment:
            emit_flow(
                "entry",
                "attachment_prepared",
                {
                    "attachment_type": attachment.get("type"),
                    "attachment_name": attachment.get("name"),
                    "attachment_path": attachment.get("path"),
                },
            )
            response["attachment"] = attachment
        return response

    async def ensure_runtime() -> MCPHost | None:
        nonlocal mcp_runtime
        if mcp_runtime:
            return mcp_runtime
        server_configs = load_mcp_server_configs_from_env()
        if not server_configs:
            return None
        mcp_runtime = MCPHost(server_configs)
        await mcp_runtime.connect_all()
        emit_flow(
            "runtime",
            "tool_runtime_ready",
            build_runtime_ready_payload(len(mcp_runtime.tools), len(server_configs)),
        )
        return mcp_runtime

    async def run_agent_flow(user_text: str, *, include_bound_doc: bool, route_payload: dict[str, Any]) -> ChatResult:
        runtime = await ensure_runtime()
        memory_context = load_memory_context(session_id, include_bound_doc=include_bound_doc)
        emit_flow("flow", "route_selected", route_payload)
        emit_flow("state", "memory_loaded", build_memory_loaded_payload(include_bound_doc, bool(memory_context)))

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
            emit_flow("state", "doc_binding_updated", build_doc_binding_updated_payload(binding))

        save_user_turn_once(content)
        agent = Agent(
            name="WeComBackendAgent",
            system_prompt=load_system_prompt(),
            mcp_client=runtime,
            memory_context=memory_context,
            on_tool_result=on_tool_result,
            on_flow_event=lambda event_name, event_payload: emit_flow("flow", event_name, event_payload),
        )
        reply = await agent.chat(user_text)
        reply = reply or "No response generated."
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow("entry", "reply_generated", build_reply_generated_payload("assistant_final", reply))
        return {"reply": reply, "requestId": request_id}

    try:
        emit_flow("entry", "request_received", build_request_received_payload("text", content_preview=content[:200]))

        short_circuit = maybe_short_circuit_upload_followup(session_id, content)
        if short_circuit:
            reply, route_payload = short_circuit
            save_user_turn_once(content)
            save_turn(session_id, "assistant", reply, request_id=request_id)
            emit_flow("flow", "route_selected", route_payload)
            emit_flow("entry", "reply_generated", build_reply_generated_payload("ack_existing_upload", reply))
            emit_flow("flow", "stop_reason", build_stop_reason_payload("short_circuit", "upload_followup_confirmation"))
            return {"reply": reply, "requestId": request_id}

        runtime_for_doc_ops = await ensure_runtime()
        doc_result = await handle_document_operation_request(
            session_id,
            request_id,
            content,
            host=runtime_for_doc_ops,
        )
        if doc_result:
            delegate_message = doc_result.get("delegate_message")
            if delegate_message:
                route_payload = dict(doc_result["route_payload"])
                emit_flow(
                    "flow",
                    "delegate_message_prepared",
                    {"delegate_preview": str(delegate_message)[:200]},
                )
                return await run_agent_flow(delegate_message, include_bound_doc=True, route_payload=route_payload)
            return finalize_direct(doc_result)

        kb_result = handle_knowledge_base_request(session_id, request_id, content)
        if kb_result:
            delegate_message = kb_result.get("delegate_message")
            if delegate_message:
                route_payload = dict(kb_result["route_payload"])
                emit_flow(
                    "flow",
                    "delegate_message_prepared",
                    {"delegate_preview": str(delegate_message)[:200]},
                )
                return await run_agent_flow(delegate_message, include_bound_doc=True, route_payload=route_payload)
            return finalize_direct(kb_result)

        include_bound_doc, route_payload = select_chat_route(content)
        return await run_agent_flow(content, include_bound_doc=include_bound_doc, route_payload=route_payload)
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()
