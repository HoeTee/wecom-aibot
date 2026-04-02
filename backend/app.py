import asyncio
import os

from flask import Flask, jsonify, request

from backend.agent import Agent
from backend.mcp_client.mcp_minimal import MinimalMCPClient


app = Flask(__name__)


async def run_agent(content: str) -> str:
    mcp_server_url = os.getenv("MCP_SERVER_URL", "").strip()
    mcp_client = None

    try:
        if mcp_server_url:
            mcp_client = MinimalMCPClient(mcp_server_url)
            await mcp_client.connect()

        agent = Agent(
            name="WeComBackendAgent",
            system_prompt=(
                "You are a concise enterprise assistant. "
                "Use available MCP tools when they help answer the user."
            ),
            mcp_client=mcp_client,
        )
        reply = await agent.chat(content)
        return reply or "No response generated."
    finally:
        if mcp_client:
            await mcp_client.cleanup()


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
        reply = asyncio.run(run_agent(content))
        return jsonify({"reply": reply})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
