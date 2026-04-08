import asyncio
import hashlib
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from backend.agent import Agent
from backend.mcp_client import MCPHost, load_mcp_server_configs_from_env
from backend.memory import (
    build_session_id,
    extract_doc_binding,
    init_db,
    latest_uploaded_file,
    load_memory_context,
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


def _store_pdf_in_knowledge_base(file_bytes: bytes, original_name: str) -> tuple[Path, str]:
    KNOWLEDGE_BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = KNOWLEDGE_BASE_UPLOAD_DIR / _upload_storage_name(original_name)

    if target_path.exists():
        existing_bytes = target_path.read_bytes()
        if _sha256_bytes(existing_bytes) == _sha256_bytes(file_bytes):
            return target_path, "unchanged"
        action = "replaced"
    else:
        action = "added"

    target_path.write_bytes(file_bytes)
    return target_path, action


def _build_upload_reply(stored_name: str, action: str) -> str:
    if action == "unchanged":
        return f"PDF `{stored_name}` 已存在于知识库，未重复写入。后续检索会继续使用它。"
    if action == "replaced":
        return f"PDF `{stored_name}` 已更新到知识库。后续检索会自动纳入新内容。"
    return f"PDF `{stored_name}` 已加入知识库。后续检索会自动纳入它。"


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


def maybe_short_circuit_upload_followup(session_id: str, content: str) -> str | None:
    if not is_add_to_knowledge_base_request(content):
        return None

    latest_upload = latest_uploaded_file(session_id)
    if not latest_upload:
        return None

    file_name = str(latest_upload["file_name"])
    action = str(latest_upload["upload_action"])
    if action == "unchanged":
        return f"刚上传的 PDF `{file_name}` 已经在知识库里了，不需要重复添加。"
    if action == "replaced":
        return f"刚上传的 PDF `{file_name}` 已经更新到知识库了。"
    return f"刚上传的 PDF `{file_name}` 已经加入知识库了。"


async def run_agent(payload: dict) -> str:
    mcp_runtime = None
    content = str(payload.get("content", "")).strip()
    session_id = build_session_id(
        chat_type=str(payload.get("chatType", "")),
        chat_id=payload.get("chatId"),
        user_id=str(payload.get("userId", "")),
    )

    short_circuit_reply = maybe_short_circuit_upload_followup(session_id, content)
    if short_circuit_reply:
        save_turn(session_id, "user", content)
        save_turn(session_id, "assistant", short_circuit_reply)
        return short_circuit_reply

    memory_context = load_memory_context(
        session_id,
        include_bound_doc=not is_fresh_document_request(content),
    )

    def on_tool_result(tool_name: str, args_dict: dict, result_text: str) -> None:
        save_tool_call(session_id, tool_name, args_dict, result_text)
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
        )

    try:
        save_turn(session_id, "user", content)

        server_configs = load_mcp_server_configs_from_env()
        if server_configs:
            mcp_runtime = MCPHost(server_configs)
            await mcp_runtime.connect_all()

        agent = Agent(
            name="WeComBackendAgent",
            system_prompt=load_system_prompt(),
            mcp_client=mcp_runtime,
            memory_context=memory_context,
            on_tool_result=on_tool_result,
        )
        reply = await agent.chat(content)
        reply = reply or "No response generated."
        save_turn(session_id, "assistant", reply)
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
        reply = asyncio.run(run_agent(payload))
        return jsonify({"reply": reply})
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

    stored_path, action = _store_pdf_in_knowledge_base(file_bytes, original_name)

    session_id = build_session_id(
        chat_type=str(request.form.get("chatType", "")),
        chat_id=request.form.get("chatId"),
        user_id=str(request.form.get("userId", "")),
    )
    save_uploaded_file(
        session_id=session_id,
        file_name=stored_path.name,
        stored_path=str(stored_path.relative_to(Path(__file__).resolve().parents[1])),
        file_sha256=_sha256_bytes(file_bytes),
        upload_action=action,
    )
    user_marker = f"[上传PDF] {stored_path.name}"
    assistant_reply = _build_upload_reply(stored_path.name, action)
    save_turn(session_id, "user", user_marker)
    save_turn(session_id, "assistant", assistant_reply)

    return jsonify(
        {
            "reply": assistant_reply,
            "fileName": stored_path.name,
            "action": action,
            "knowledgeBasePath": str(stored_path.relative_to(Path(__file__).resolve().parents[1])),
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
