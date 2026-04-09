from __future__ import annotations

import asyncio

from flask import Flask, jsonify, request

from backend.flow.chat import run_chat
from backend.flow.upload import process_upload
from backend.state.store import generate_request_id, init_db


def create_app() -> Flask:
    app = Flask(__name__)
    init_db()

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
            result = asyncio.run(run_chat(payload))
            response = {"requestId": payload["requestId"], **result}
            return jsonify(response)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/knowledge-base/upload")
    def upload_knowledge_base_file():
        body, status = process_upload(request.form, request.files.get("file"))
        return jsonify(body), status

    return app
