from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from backend.agent import Agent
from backend.mcp_client import MCPHost, load_mcp_server_configs_from_env
from backend.memory import (
    build_session_id,
    extract_doc_binding,
    generate_request_id,
    init_db,
    latest_uploaded_file,
    load_memory_context,
    save_flow_event,
    save_tool_call,
    save_turn,
    save_uploaded_file,
    upsert_session_doc,
)


app = Flask(__name__)
init_db()

DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system" / "assistant_v1.md"
KNOWLEDGE_BASE_PAPER_DIR = Path(__file__).resolve().parents[1] / "knowledge_base" / "papers"
KNOWLEDGE_BASE_UPLOAD_DIR = KNOWLEDGE_BASE_PAPER_DIR / "uploads"
PDF_HEADER = b"%PDF-"


def load_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def is_fresh_document_request(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    fresh_tokens = ("重新生成", "重新写一份", "重新出一份", "新生成一份", "新建一份")
    return "文档" in text and any(token in text for token in fresh_tokens)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_pdf_filename(filename: str) -> str:
    normalized = secure_filename(str(filename or "").strip())
    if not normalized:
        normalized = "uploaded.pdf"
    if not normalized.lower().endswith(".pdf"):
        normalized = f"{Path(normalized).stem or 'uploaded'}.pdf"
    return normalized


def _upload_storage_name(filename: str) -> str:
    normalized_name = _normalize_pdf_filename(filename)
    return f"upload__{normalized_name}"


def _knowledge_base_pdf_paths() -> list[Path]:
    return sorted(path for path in KNOWLEDGE_BASE_PAPER_DIR.rglob("*.pdf") if path.is_file())


def _relative_project_path(path: Path) -> str:
    return str(path.relative_to(Path(__file__).resolve().parents[1]))


def _build_selected_target(target_type: str, primary_id: str | None, display_name: str | None, clear_reason: str | None = None) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "primary_id": primary_id,
        "display_name": display_name,
        "clear_reason": clear_reason,
    }


def _build_route_payload(
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


def _store_pdf_in_knowledge_base(file_bytes: bytes, original_name: str) -> dict[str, str | None]:
    KNOWLEDGE_BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_BASE_UPLOAD_DIR / _upload_storage_name(original_name)
    incoming_sha = _sha256_bytes(file_bytes)

    if target_path.exists():
        existing_bytes = target_path.read_bytes()
        if _sha256_bytes(existing_bytes) == incoming_sha:
            return {
                "file_name": target_path.name,
                "stored_path": _relative_project_path(target_path),
                "action": "unchanged",
                "matched_file_name": target_path.name,
                "matched_stored_path": _relative_project_path(target_path),
            }
        action = "replaced"
    else:
        action = "added"

    for existing_path in _knowledge_base_pdf_paths():
        if existing_path == target_path:
            continue
        if _sha256_bytes(existing_path.read_bytes()) != incoming_sha:
            continue
        return {
            "file_name": target_path.name,
            "stored_path": _relative_project_path(existing_path),
            "action": "duplicate_content",
            "matched_file_name": existing_path.name,
            "matched_stored_path": _relative_project_path(existing_path),
        }

    target_path.write_bytes(file_bytes)
    return {
        "file_name": target_path.name,
        "stored_path": _relative_project_path(target_path),
        "action": action,
        "matched_file_name": target_path.name if action == "replaced" else None,
        "matched_stored_path": _relative_project_path(target_path) if action == "replaced" else None,
    }


def _build_upload_reply(file_name: str, action: str, matched_file_name: str | None = None) -> str:
    if action == "unchanged":
        return f"PDF `{file_name}` 已经在知识库里了，文件名和内容都重复，未再次写入。"
    if action == "duplicate_content":
        if matched_file_name:
            return f"PDF `{file_name}` 与知识库中的 `{matched_file_name}` 内容完全一致，未重复加入知识库。"
        return f"PDF `{file_name}` 与知识库中的现有文件内容完全一致，未重复加入知识库。"
    if action == "replaced":
        return f"检测到同名 PDF `{file_name}` 已存在，已用新上传内容更新知识库中的同名文件。"
    return f"PDF `{file_name}` 已加入知识库。后续检索会自动纳入它。"


def is_add_to_knowledge_base_request(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False

    knowledge_tokens = ("知识库", "知识源", "知识源库")
    add_tokens = ("加入", "添加", "放到", "纳入", "导入")
    file_tokens = (
        "这份文档",
        "这个文件",
        "这份文件",
        "刚上传的文件",
        "刚才上传的文件",
        "刚上传的pdf",
        "刚上传的PDF",
        "这个pdf",
        "这个PDF",
        "文档",
        "文件",
        "pdf",
        "PDF",
    )
    generation_tokens = ("总结", "摘要", "生成", "分析", "写一份", "文档必须包含")

    if not any(token in text for token in knowledge_tokens):
        return False
    if not any(token in text for token in add_tokens):
        return False
    if not any(token in text for token in file_tokens):
        return False
    if any(token in text for token in generation_tokens):
        return False
    return True


def maybe_short_circuit_upload_followup(session_id: str, content: str) -> tuple[str, dict[str, Any]] | None:
    if not is_add_to_knowledge_base_request(content):
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

    payload = _build_route_payload(
        route_code="short_circuit",
        route_detail="upload_followup_confirmation",
        reasons=["knowledge_base_followup_detected", "recent_uploaded_file_found"],
        selected_target=_build_selected_target("uploaded_file", file_name, file_name),
        guard_hits=[{"code": "upload_followup_guard", "detail": "ack_existing_upload"}],
        clarify_needed=False,
    )
    return reply, payload


async def run_agent(payload: dict[str, Any]) -> str:
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
        {
            "message_type": "text",
            "content_preview": content[:200],
        },
    )

    short_circuit = maybe_short_circuit_upload_followup(session_id, content)
    if short_circuit:
        reply, route_payload = short_circuit
        emit_flow("orchestration", "route_selected", route_payload)
        save_turn(session_id, "user", content, request_id=request_id)
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow(
            "entry",
            "reply_generated",
            {
                "reply_type": "ack_existing_upload",
                "reply_preview": reply[:200],
            },
        )
        emit_flow(
            "orchestration",
            "stop_reason",
            {
                "code": "short_circuit",
                "detail": "upload_followup_confirmation",
                "layer": "orchestration",
            },
        )
        return reply

    include_bound_doc = not is_fresh_document_request(content)
    route_detail = "fresh_document_request" if not include_bound_doc else "default_agent_flow"
    route_reason = ["fresh_document_request"] if not include_bound_doc else ["default_text_message"]
    emit_flow(
        "orchestration",
        "route_selected",
        _build_route_payload(
            route_code="agent_chat",
            route_detail=route_detail,
            reasons=route_reason,
            selected_target=_build_selected_target(
                "document" if include_bound_doc else "none",
                None,
                None,
                clear_reason="fresh_document_request" if not include_bound_doc else "no_target_selected_at_route_time",
            ),
            clarify_needed=False,
        ),
    )

    memory_context = load_memory_context(
        session_id,
        include_bound_doc=include_bound_doc,
    )
    emit_flow(
        "policy_state",
        "memory_loaded",
        {
            "include_bound_doc": include_bound_doc,
            "has_memory_context": bool(memory_context),
        },
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
            "policy_state",
            "doc_binding_updated",
            {
                "selected_target": _build_selected_target(
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
                "tool_runtime",
                "tool_runtime_ready",
                {
                    "tool_count": len(mcp_runtime.tools),
                    "server_count": len(server_configs),
                },
            )

        agent = Agent(
            name="WeComBackendAgent",
            system_prompt=load_system_prompt(),
            mcp_client=mcp_runtime,
            memory_context=memory_context,
            on_tool_result=on_tool_result,
            on_flow_event=lambda event_name, event_payload: emit_flow("orchestration", event_name, event_payload),
        )
        reply = await agent.chat(content)
        reply = reply or "No response generated."
        save_turn(session_id, "assistant", reply, request_id=request_id)
        emit_flow(
            "entry",
            "reply_generated",
            {
                "reply_type": "assistant_final",
                "reply_preview": reply[:200],
            },
        )
        return reply
    finally:
        if mcp_runtime:
            await mcp_runtime.cleanup()


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    content = str(payload.get("content", "")).strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    try:
        payload.setdefault("requestId", generate_request_id())
        reply = asyncio.run(run_agent(payload))
        return jsonify({"reply": reply, "requestId": payload["requestId"]})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/knowledge-base/upload")
def upload_knowledge_base_file():
    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        return jsonify({"error": "file is required"}), 400

    original_name = str(uploaded_file.filename or "").strip()
    if not original_name:
        return jsonify({"error": "filename is required"}), 400

    file_bytes = uploaded_file.read()
    if not file_bytes:
        return jsonify({"error": "uploaded file is empty"}), 400

    if not original_name.lower().endswith(".pdf"):
        return jsonify({"error": "only PDF files are supported"}), 400

    if not file_bytes.startswith(PDF_HEADER):
        return jsonify({"error": "uploaded file is not a valid PDF"}), 400

    request_id = generate_request_id()
    session_id = build_session_id(
        chat_type=str(request.form.get("chatType", "")),
        chat_id=request.form.get("chatId"),
        user_id=str(request.form.get("userId", "")),
    )

    def emit_flow(layer_at_event: str, event_name: str, event_payload: dict[str, Any]) -> None:
        save_flow_event(session_id, request_id, layer_at_event, event_name, event_payload)

    emit_flow(
        "entry",
        "request_received",
        {
            "message_type": "file",
            "file_name": original_name,
        },
    )

    store_result = _store_pdf_in_knowledge_base(file_bytes, original_name)
    file_name = str(store_result["file_name"] or "")
    stored_path = str(store_result["stored_path"] or "")
    action = str(store_result["action"] or "")
    matched_file_name = str(store_result.get("matched_file_name") or "").strip() or None
    matched_stored_path = str(store_result.get("matched_stored_path") or "").strip() or None

    save_uploaded_file(
        session_id=session_id,
        file_name=file_name,
        stored_path=stored_path,
        file_sha256=_sha256_bytes(file_bytes),
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
        "orchestration",
        "route_selected",
        _build_route_payload(
            route_code="upload_ingest",
            route_detail="pdf_upload_to_knowledge_base",
            reasons=["pdf_file_message"],
            selected_target=_build_selected_target("uploaded_file", file_name, file_name),
            guard_hits=route_guard_hits,
            clarify_needed=False,
        ),
    )

    user_marker = f"[上传PDF] {file_name}"
    assistant_reply = _build_upload_reply(file_name, action, matched_file_name)
    save_turn(session_id, "user", user_marker, request_id=request_id)
    save_turn(session_id, "assistant", assistant_reply, request_id=request_id)

    emit_flow(
        "entry",
        "reply_generated",
        {
            "reply_type": "upload_ack",
            "reply_preview": assistant_reply[:200],
        },
    )
    emit_flow(
        "orchestration",
        "stop_reason",
        {
            "code": "upload_complete",
            "detail": action,
            "layer": "orchestration",
        },
    )

    return jsonify(
        {
            "reply": assistant_reply,
            "requestId": request_id,
            "fileName": file_name,
            "action": action,
            "knowledgeBasePath": stored_path,
            "matchedFileName": matched_file_name,
            "matchedKnowledgeBasePath": matched_stored_path,
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
