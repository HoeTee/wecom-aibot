from __future__ import annotations

import asyncio
from typing import Any

from backend.agent import Agent, Settings
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
from backend.runtime.local_tools import get_local_agent_tools
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


def _use_local_rag_runtime(server_name: str) -> bool:
    return str(server_name or "").strip().lower() == "llamaindex_rag"


def _summarize_args(args_dict: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in args_dict.items():
        if key == "content":
            text = str(value or "").strip()
            summary["content_preview"] = text[:200]
            summary["content_length"] = len(text)
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        else:
            summary[key] = str(value)[:200]
    return summary


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

    async def ensure_runtime() -> MCPHost | None:
        nonlocal mcp_runtime
        if mcp_runtime:
            return mcp_runtime
        server_configs = [
            config
            for config in load_mcp_server_configs_from_env()
            if not _use_local_rag_runtime(config.name)
        ]
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

    async def run_agent_flow(
        user_text: str,
        *,
        include_bound_doc: bool,
        route_payload: dict[str, Any],
    ) -> ChatResult:
        runtime = await ensure_runtime()
        tools = list(runtime.tools) if runtime else []
        tools.extend(get_local_agent_tools())
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
            tools=tools,
            memory_context=memory_context,
            on_tool_result=on_tool_result,
            on_flow_event=lambda event_name, event_payload: emit_flow("flow", event_name, event_payload),
        )
        try:
            reply = await asyncio.wait_for(
                agent.chat(user_text),
                timeout=Settings().agent_timeout_seconds,
            )
        except asyncio.TimeoutError:
            reply = "这次处理超时了。我没有继续执行不确定的动作。请直接重试，或明确告诉我你要操作的知识库文件/文档对象。"
            save_turn(session_id, "assistant", reply, request_id=request_id)
            emit_flow(
                "flow",
                "guard_hit",
                {
                    "guard_hit": [{"code": "agent_timeout", "detail": "safe_reply_after_timeout"}],
                    "timeout_seconds": Settings().agent_timeout_seconds,
                },
            )
            emit_flow("entry", "reply_generated", build_reply_generated_payload("assistant_timeout", reply))
            emit_flow("flow", "stop_reason", build_stop_reason_payload("agent_timeout", "safe_reply_after_timeout"))
            return {"reply": reply, "requestId": request_id}
        reply = reply or "No response generated."
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow("entry", "reply_generated", build_reply_generated_payload("assistant_final", reply))
        response: ChatResult = {"reply": reply, "requestId": request_id}
        if agent.prepared_attachment:
            emit_flow(
                "entry",
                "attachment_prepared",
                {
                    "attachment_type": agent.prepared_attachment.get("type"),
                    "attachment_name": agent.prepared_attachment.get("name"),
                    "attachment_path": agent.prepared_attachment.get("path"),
                },
            )
            response["attachment"] = agent.prepared_attachment
        return response

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

        include_bound_doc, route_payload = select_chat_route(content)
        return await run_agent_flow(
            content,
            include_bound_doc=include_bound_doc,
            route_payload=route_payload,
        )
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()
