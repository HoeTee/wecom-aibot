from __future__ import annotations

from typing import Any

from backend.state.store import latest_uploaded_file


def is_add_to_knowledge_base_request(content: str) -> bool:
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


def build_selected_target(
    target_type: str,
    primary_id: str | None,
    display_name: str | None,
    clear_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "primary_id": primary_id,
        "display_name": display_name,
        "clear_reason": clear_reason,
    }


def build_route_payload(
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

    payload = build_route_payload(
        route_code="short_circuit",
        route_detail="upload_followup_confirmation",
        reasons=["knowledge_base_followup_detected", "recent_uploaded_file_found"],
        selected_target=build_selected_target("uploaded_file", file_name, file_name),
        guard_hits=[{"code": "upload_followup_guard", "detail": "ack_existing_upload"}],
        clarify_needed=False,
    )
    return reply, payload
