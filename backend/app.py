import asyncio

from flask import Flask, jsonify, request

from backend.agent import Agent
from backend.mcp_client import MCPHost, load_mcp_server_configs_from_env
from backend.memory import (
    build_session_id,
    extract_doc_binding,
    init_db,
    load_memory_context,
    save_tool_call,
    save_turn,
    upsert_session_doc,
)


app = Flask(__name__)
init_db()


async def run_agent(payload: dict) -> str:
    mcp_runtime = None
    content = str(payload.get("content", "")).strip()
    session_id = build_session_id(
        chat_type=str(payload.get("chatType", "")),
        chat_id=payload.get("chatId"),
        user_id=str(payload.get("userId", "")),
    )
    memory_context = load_memory_context(session_id)

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
            system_prompt=(
                "You are a concise enterprise assistant. "
                "Use available MCP tools when they help answer the user."
            ),
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
