from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "memory.sqlite3"
EVALS_DIR = PROJECT_ROOT / "evals"
SCENARIOS_DIR = EVALS_DIR / "scenarios"
RUNS_DIR = EVALS_DIR / "runs"
GLOBAL_GATES_PATH = EVALS_DIR / "gates" / "global.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def latest_user_turn(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT id, session_id, role, content, created_at
        FROM conversation_turns
        WHERE session_id = ?
          AND role = 'user'
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No user turns found for session_id={session_id}")
    return row


def next_assistant_turn(conn: sqlite3.Connection, session_id: str, user_turn_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, session_id, role, content, created_at
        FROM conversation_turns
        WHERE session_id = ?
          AND role = 'assistant'
          AND id > ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (session_id, user_turn_id),
    ).fetchone()


def recent_tool_calls(conn: sqlite3.Connection, session_id: str, from_created_at: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, tool_name, args_json, result_excerpt, created_at
        FROM tool_calls
        WHERE session_id = ?
          AND created_at >= datetime(?, '-5 second')
        ORDER BY id ASC
        """,
        (session_id, from_created_at),
    ).fetchall()


def current_doc_binding(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT doc_id, doc_url, doc_name, last_tool_name, last_user_text, updated_at
        FROM session_docs
        WHERE session_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()


def latest_uploaded_file(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT file_name, stored_path, file_sha256, upload_action, created_at
        FROM session_uploaded_files
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()


def latest_doc_write_payload(tool_calls: list[sqlite3.Row]) -> dict[str, Any]:
    for row in reversed(tool_calls):
        if row["tool_name"].endswith("edit_doc_content"):
            args_dict = parse_args_json(row["args_json"])
            return {
                "tool_name": row["tool_name"],
                "args": args_dict,
                "created_at": row["created_at"],
            }
    return {"tool_name": None, "args": {}, "created_at": None}


def latest_rag_query_payload(tool_calls: list[sqlite3.Row]) -> dict[str, Any]:
    for row in reversed(tool_calls):
        if row["tool_name"].endswith("llamaindex_rag_query"):
            args_dict = parse_args_json(row["args_json"])
            return {
                "tool_name": row["tool_name"],
                "original_query": args_dict.get("query", ""),
                "rewritten_query": args_dict.get("rewritten_query", ""),
                "created_at": row["created_at"],
            }
    return {
        "tool_name": None,
        "original_query": "",
        "rewritten_query": "",
        "created_at": None,
    }


def evaluate_global_gate(
    gate_id: str,
    assistant_reply: str,
    tool_calls: list[sqlite3.Row],
    doc_binding: sqlite3.Row | None,
) -> tuple[bool, str]:
    if gate_id == "must_bind_doc_triple":
        if doc_binding and doc_binding["doc_id"] and doc_binding["doc_url"] and doc_binding["doc_name"]:
            return True, "doc_id/doc_url/doc_name 已绑定。"
        return False, "缺少完整的文档三元组。"

    if gate_id == "must_not_claim_success_on_failure":
        failure_tools = [row["tool_name"] for row in tool_calls if '"errcode": 0' not in str(row["result_excerpt"])]
        success_markers = ("已创建", "已更新", "已生成", "已加入知识库", "文档已更新")
        if failure_tools and any(token in assistant_reply for token in success_markers):
            return False, f"存在失败 tool 调用，但 assistant 仍声称成功：{failure_tools}"
        return True, "未发现失败后误报成功。"

    if gate_id == "must_follow_requested_structure":
        requested_sections = ["背景", "每篇论文摘要", "横向对比", "结论与建议"]
        write_payload = latest_doc_write_payload(tool_calls)
        content = str(write_payload["args"].get("content", "") or "")
        missing = [section for section in requested_sections if section not in content]
        if missing:
            return False, f"缺少结构部分：{missing}"
        return True, "写入内容包含要求结构。"

    return True, f"未实现的 global gate，默认跳过：{gate_id}"


def evaluate_scenario_gate(
    gate_id: str,
    assistant_reply: str,
    tool_calls: list[sqlite3.Row],
    user_request: str,
    uploaded_file: sqlite3.Row | None,
) -> tuple[bool, str]:
    write_payload = latest_doc_write_payload(tool_calls)
    content = str(write_payload["args"].get("content", "") or "")
    tool_names = [row["tool_name"] for row in tool_calls]

    if gate_id == "fresh_regenerate_must_not_reuse_existing_doc":
        if "重新生成" in user_request and "文档" in user_request:
            if any(name.endswith("create_doc") for name in tool_names):
                return True, "重新生成请求先创建了新文档。"
            if any(name.endswith("edit_doc_content") for name in tool_names):
                return False, "重新生成请求直接走了 edit_doc_content，疑似复用旧文档。"
        return True, "不适用或未发现复用旧文档。"

    if gate_id == "generated_doc_must_not_contain_placeholders":
        if "..." in content:
            return False, "写入内容包含 `...` 占位符。"
        return True, "写入内容未发现占位符。"

    if gate_id == "generated_doc_must_include_required_sections":
        required_sections = ["背景", "每篇论文摘要", "横向对比", "结论与建议"]
        missing = [section for section in required_sections if section not in content]
        if missing:
            return False, f"写入内容缺少部分：{missing}"
        return True, "写入内容包含 1/2/3/4 四部分。"

    if gate_id == "generated_doc_must_not_add_unrequested_table":
        if not any(token in user_request for token in ("表格", "对比表", "comparison table")):
            forbidden_markers = ("## 5.", "### 5.", "技术对比表", "| 方法 | 优点 | 局限 |")
            if any(marker in content for marker in forbidden_markers):
                return False, "用户未要求表格，但写入内容提前出现了第 5 节或对比表。"
        return True, "未发现未请求的表格内容。"

    if gate_id == "uploaded_pdf_must_be_recorded":
        if uploaded_file and uploaded_file["file_name"] and uploaded_file["stored_path"]:
            return True, "已记录最近上传文件状态。"
        return False, "缺少最近上传文件的结构化状态。"

    if gate_id == "followup_add_to_kb_must_not_request_file_again":
        refusal_markers = (
            "请提供您要添加到知识库的文件",
            "上传该文件",
            "目前我无法直接接收文件",
            "请补充信息",
        )
        if any(marker in assistant_reply for marker in refusal_markers):
            return False, "已经有上传文件状态，但 assistant 仍再次索要文件。"
        return True, "未发现重复索要文件。"

    if gate_id == "followup_add_to_kb_must_ack_existing_upload":
        if not uploaded_file:
            return False, "没有可用于确认的上传文件状态。"
        success_markers = ("已加入知识库", "已经加入知识库", "已更新到知识库", "已经在知识库里")
        if any(marker in assistant_reply for marker in success_markers):
            return True, "assistant 正确确认了已上传文件的知识库状态。"
        return False, "assistant 没有确认刚上传文件已进入知识库。"

    if gate_id == "duplicate_upload_same_content_must_be_noticed":
        if not uploaded_file:
            return False, "缺少最近上传文件状态。"
        action = str(uploaded_file["upload_action"] or "")
        if action not in {"unchanged", "duplicate_content"}:
            return False, f"最近上传动作不是同内容重复上传：{action}"
        markers = ("内容完全一致", "未重复加入", "未再次写入", "文件名和内容都重复")
        if any(marker in assistant_reply for marker in markers):
            return True, "assistant 明确提示了同内容重复上传。"
        return False, "assistant 没有明确提示同内容重复上传。"

    if gate_id == "same_name_upload_update_must_be_noticed":
        if not uploaded_file:
            return False, "缺少最近上传文件状态。"
        action = str(uploaded_file["upload_action"] or "")
        if action != "replaced":
            return False, f"最近上传动作不是同名更新：{action}"
        if "同名" in assistant_reply and any(marker in assistant_reply for marker in ("已存在", "更新")):
            return True, "assistant 明确提示了同名文件更新。"
        return False, "assistant 没有明确提示同名文件更新。"

    return True, f"未实现的 scenario gate，默认跳过：{gate_id}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export latest WeCom eval run and validate gates.")
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()

    scenario_dir = SCENARIOS_DIR / args.scenario_id
    scenario = load_yaml(scenario_dir / "scenario.yaml")
    global_gates_config = load_yaml(GLOBAL_GATES_PATH)

    global_gate_catalog = {
        gate["id"]: gate.get("description", "")
        for gate in global_gates_config.get("gates", [])
    }
    scenario_gate_catalog = {
        gate["id"]: gate.get("description", "")
        for gate in scenario.get("scenario_gates", [])
    }

    run_dir = RUNS_DIR / args.run_id / args.scenario_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        user_turn = latest_user_turn(conn, args.session_id)
        assistant_turn = next_assistant_turn(conn, args.session_id, user_turn["id"])
        tool_calls = recent_tool_calls(conn, args.session_id, user_turn["created_at"])
        doc_binding = current_doc_binding(conn, args.session_id)
        uploaded_file = latest_uploaded_file(conn, args.session_id)

    assistant_reply = str(assistant_turn["content"] if assistant_turn else "")
    user_request = str(user_turn["content"])
    write_payload = latest_doc_write_payload(tool_calls)
    rag_query_payload = latest_rag_query_payload(tool_calls)

    metadata = {
        "scenario_id": args.scenario_id,
        "run_id": args.run_id,
        "session_id": args.session_id,
        "user_turn_id": user_turn["id"],
        "assistant_turn_id": assistant_turn["id"] if assistant_turn else None,
        "user_created_at": user_turn["created_at"],
        "assistant_created_at": assistant_turn["created_at"] if assistant_turn else None,
        "prompt_version": scenario.get("prompt_version"),
    }

    dump_json(run_dir / "metadata.json", metadata)
    (run_dir / "user_request.txt").write_text(user_request, encoding="utf-8")
    (run_dir / "assistant_reply.txt").write_text(assistant_reply, encoding="utf-8")
    dump_json(run_dir / "tool_trace.json", [dict(row) for row in tool_calls])
    dump_json(run_dir / "doc_binding.json", dict(doc_binding) if doc_binding else {})
    dump_json(run_dir / "uploaded_file.json", dict(uploaded_file) if uploaded_file else {})
    dump_json(run_dir / "rag_query.json", rag_query_payload)
    (run_dir / "written_doc_content.md").write_text(str(write_payload["args"].get("content", "") or ""), encoding="utf-8")

    gate_results: list[dict[str, Any]] = []
    for gate_id in scenario.get("global_gates", []):
        passed, reason = evaluate_global_gate(gate_id, assistant_reply, tool_calls, doc_binding)
        gate_results.append(
            {
                "id": gate_id,
                "scope": "global",
                "description": global_gate_catalog.get(gate_id, ""),
                "passed": passed,
                "reason": reason,
            }
        )

    for gate_id in scenario_gate_catalog:
        passed, reason = evaluate_scenario_gate(gate_id, assistant_reply, tool_calls, user_request, uploaded_file)
        gate_results.append(
            {
                "id": gate_id,
                "scope": "scenario",
                "description": scenario_gate_catalog.get(gate_id, ""),
                "passed": passed,
                "reason": reason,
            }
        )

    summary = {
        "passed": all(item["passed"] for item in gate_results),
        "failed_gate_ids": [item["id"] for item in gate_results if not item["passed"]],
        "gate_results": gate_results,
    }
    dump_json(run_dir / "gate_results.json", summary)

    print(f"Saved run artifacts to: {run_dir}")
    print(f"Overall passed: {summary['passed']}")
    if summary["failed_gate_ids"]:
        print("Failed gates:")
        for gate_id in summary["failed_gate_ids"]:
            print(f"- {gate_id}")


if __name__ == "__main__":
    main()
