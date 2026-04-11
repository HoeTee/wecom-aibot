from __future__ import annotations

import asyncio
from typing import Any

from backend.agent import Agent, Settings
from backend.caps.documents import load_system_prompt
from backend.policy.payloads import (
    build_doc_binding_updated_payload,
    build_memory_loaded_payload,
    build_reply_generated_payload,
    build_request_received_payload,
    build_route_payload,
    build_runtime_ready_payload,
    build_selected_target,
    build_stop_reason_payload,
)
from backend.policy.document import is_fresh_document_request
from backend.runtime import MCPHost, load_mcp_server_configs_from_env
from backend.runtime.local_tools import get_local_agent_tools
from backend.state.store import (
    build_session_id,
    generate_request_id,
    latest_uploaded_file,
    load_memory_context,
    persist_doc_binding_from_tool_result,
    save_flow_event,
    save_tool_call,
    save_turn,
)


ChatResult = dict[str, Any]


def _use_local_rag_runtime(server_name: str) -> bool:
    return str(server_name or "").strip().lower() == "llamaindex_rag"


def _is_add_to_knowledge_base_request(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False

    if not any(token in text for token in ("知识库", "知识源", "知识库里")):
        return False
    if not any(token in text for token in ("加入", "添加", "放到", "纳入", "导入")):
        return False
    if not any(
        token in text
        for token in (
            "这份文档",
            "这个文件",
            "刚上传的文件",
            "刚才上传的文件",
            "刚上传的 PDF",
            "刚上传的pdf",
            "这个 PDF",
            "这个pdf",
            "文档",
            "文件",
            "PDF",
            "pdf",
        )
    ):
        return False
    if any(token in text for token in ("总结", "摘要", "生成", "分析", "文档必须包含")):
        return False
    return True


def _build_agent_route_payload(content: str) -> tuple[bool, dict[str, Any]]:
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


def _maybe_short_circuit_upload_followup(session_id: str, content: str) -> tuple[str, dict[str, Any]] | None:
    if not _is_add_to_knowledge_base_request(content):
        return None

    latest_upload = latest_uploaded_file(session_id)
    if not latest_upload:
        return None

    file_name = str(latest_upload["file_name"])
    action = str(latest_upload["upload_action"])
    matched_file_name = str(latest_upload.get("matched_file_name") or "").strip() or None

    if action == "unchanged":
        reply = f"刚上传的 PDF `{file_name}` 已经在知识库里了，不需要重复添加。"
    elif action == "duplicate_content":
        if matched_file_name:
            reply = f"刚上传的 PDF `{file_name}` 与知识库中的 `{matched_file_name}` 内容完全一致，未重复加入。"
        else:
            reply = f"刚上传的 PDF `{file_name}` 与知识库中的已有文件内容完全一致，未重复加入。"
    elif action == "replaced":
        reply = f"刚上传的 PDF `{file_name}` 已经更新到知识库了。"
    else:
        reply = f"刚上传的 PDF `{file_name}` 已经加入知识库了。"

    payload = build_route_payload(
        route_code="short_circuit",
        route_detail="upload_followup_confirmation",
        reasons=["knowledge_base_followup_detected", "recent_uploaded_file_found"],
        selected_target=build_selected_target("uploaded_file", file_name, file_name),
        guard_hits=[{"code": "upload_followup_guard", "detail": "ack_existing_upload"}],
        clarify_needed=False,
    )
    return reply, payload


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

        short_circuit = _maybe_short_circuit_upload_followup(session_id, content)
        if short_circuit:
            reply, route_payload = short_circuit
            save_user_turn_once(content)
            save_turn(session_id, "assistant", reply, request_id=request_id)
            emit_flow("flow", "route_selected", route_payload)
            emit_flow("entry", "reply_generated", build_reply_generated_payload("ack_existing_upload", reply))
            emit_flow("flow", "stop_reason", build_stop_reason_payload("short_circuit", "upload_followup_confirmation"))
            return {"reply": reply, "requestId": request_id}

        include_bound_doc, route_payload = _build_agent_route_payload(content)
        return await run_agent_flow(
            content,
            include_bound_doc=include_bound_doc,
            route_payload=route_payload,
        )
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()
