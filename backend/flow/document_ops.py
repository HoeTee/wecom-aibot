from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.caps.documents import (
    append_section,
    append_document_section,
    build_section_block,
    choose_relevant_section,
    expand_document_section,
    get_doc_markdown,
    insert_after_section,
    overwrite_document_markdown,
    parse_markdown_sections,
    preview_document_replace,
    replace_section,
    replace_document_section,
    section_preview,
)
from backend.caps.knowledge_base import match_pdf_records, resolve_record_by_index
from backend.caps.rag import summarize_rag
from backend.policy.editing import (
    build_action_clarify_reply,
    build_location_clarify_reply,
    build_merge_confirm_reply,
    build_replace_preview_reply,
    build_section_clarify_reply,
    build_title_confirm_reply,
    is_affirmative,
    is_expand_from_kb_doc_request,
    is_merge_kb_doc_request,
    is_replace_with_kb_doc_request,
    lets_system_choose_location,
    wants_append_to_end,
    wants_auto_replace_scope,
    wants_new_section,
    wants_system_generated_title,
)
from backend.policy.knowledge_base import parse_candidate_selection
from backend.policy.payloads import build_route_payload, build_selected_target
from backend.runtime import MCPHost
from backend.state.store import (
    current_bound_doc,
    latest_pending_action,
    resolve_pending_action,
    save_pending_action,
)


def _file_stem(file_name: str) -> str:
    stem = Path(str(file_name or "")).stem
    return stem.removeprefix("upload__")


def _build_result(
    *,
    reply: str,
    route_detail: str,
    reasons: list[str],
    selected_target: dict[str, Any],
    reply_type: str,
    stop_code: str,
    stop_detail: str,
    clarify_needed: bool = False,
    clarify_reason: str | None = None,
    delegate_message: str | None = None,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "route_payload": build_route_payload(
            route_code="document_ops",
            route_detail=route_detail,
            reasons=reasons,
            selected_target=selected_target,
            clarify_needed=clarify_needed,
            clarify_reason=clarify_reason,
        ),
        "reply_type": reply_type,
        "stop_reason": {"code": stop_code, "detail": stop_detail, "layer": "flow"},
        "delegate_message": delegate_message,
    }


def _resolve_source_record(session_id: str, content: str) -> dict[str, Any] | None:
    candidates = match_pdf_records(content, limit=5)
    if len(candidates) == 1:
        return candidates[0]

    index = parse_candidate_selection(content)
    if index is not None:
        for action_type in ("kb_related_candidates", "kb_export_candidates", "kb_delete_candidates"):
            pending = latest_pending_action(session_id, action_type=action_type)
            if not pending:
                continue
            selected = resolve_record_by_index(pending["payload"].get("candidates") or [], index)
            if selected:
                return selected
    return None


def _resolve_target_doc(session_id: str) -> dict[str, Any] | None:
    return current_bound_doc(session_id)


def _extract_explicit_section_title(text: str) -> str | None:
    normalized = str(text or "").strip()
    quoted = re.search(r"[“\"']([^“\"']{2,60})[”\"']", normalized)
    if quoted:
        return quoted.group(1).strip()
    marker = re.search(r"在(.{2,40}?)(章节|一节|部分)", normalized)
    if marker:
        return marker.group(1).strip()
    return None


def _generate_section_title(current_markdown: str, source_record: dict[str, Any]) -> str:
    sections = parse_markdown_sections(current_markdown)
    default_title = f"补充分析：{_file_stem(source_record['file_name'])}"
    if not sections:
        return default_title
    first_title = str(sections[0]["title"])
    if "：" in first_title:
        prefix = first_title.split("：", 1)[0]
        return f"{prefix}：{_file_stem(source_record['file_name'])}"
    return default_title


async def _build_source_summary(host: MCPHost, source_record: dict[str, Any], user_request: str) -> str:
    file_name = source_record["file_name"]
    query = (
        f"请只基于知识库中的文件 `{file_name}`，围绕这个请求生成一段可直接写入企业微信文档的 Markdown 内容：{user_request}。"
        "不要引用其他文件。输出用中文。"
    )
    return (await summarize_rag(host, query)).strip()


async def _execute_merge(
    host: MCPHost,
    *,
    target_doc: dict[str, Any],
    source_record: dict[str, Any],
    user_request: str,
    location_mode: str,
    section_title: str | None = None,
) -> None:
    markdown = await get_doc_markdown(host, doc_id=target_doc["doc_id"], doc_url=target_doc.get("doc_url"))
    summary = await _build_source_summary(host, source_record, user_request)

    if location_mode == "append_end":
        title = section_title or f"补充：{_file_stem(source_record['file_name'])}"
        await append_document_section(
            host,
            doc_id=target_doc["doc_id"],
            doc_url=target_doc.get("doc_url"),
            title=title,
            body=summary,
            location_mode="append_end",
            level=2,
        )
    elif location_mode == "new_section":
        title = section_title or _generate_section_title(markdown, source_record)
        await append_document_section(
            host,
            doc_id=target_doc["doc_id"],
            doc_url=target_doc.get("doc_url"),
            title=title,
            body=summary,
            location_mode="new_section",
            level=2,
        )
    else:
        title = section_title or f"补充：{_file_stem(source_record['file_name'])}"
        await append_document_section(
            host,
            doc_id=target_doc["doc_id"],
            doc_url=target_doc.get("doc_url"),
            title=title,
            body=summary,
            location_mode="relevant_section",
            query=f"{user_request}\n{source_record['file_name']}",
            level=2,
        )


async def _prepare_replace_preview(
    host: MCPHost,
    *,
    target_doc: dict[str, Any],
    source_record: dict[str, Any],
    scope_hint: str,
) -> dict[str, Any]:
    return await preview_document_replace(
        host,
        doc_id=target_doc["doc_id"],
        doc_url=target_doc.get("doc_url"),
        scope_hint=scope_hint,
        source_hint=source_record["file_name"],
    )


async def _execute_replace(
    host: MCPHost,
    *,
    target_doc: dict[str, Any],
    source_record: dict[str, Any],
    section_payload: dict[str, Any],
    user_request: str,
) -> None:
    summary = await _build_source_summary(host, source_record, user_request)
    await replace_document_section(
        host,
        doc_id=target_doc["doc_id"],
        doc_url=target_doc.get("doc_url"),
        title=str((section_payload or {}).get("title") or source_record["file_name"]),
        body=summary,
        section_payload=section_payload,
        query=str((section_payload or {}).get("title") or source_record["file_name"]),
    )


async def _execute_expand(
    host: MCPHost,
    *,
    target_doc: dict[str, Any],
    source_record: dict[str, Any],
    user_request: str,
    existing_section_title: str | None = None,
    new_section_title: str | None = None,
) -> None:
    summary = await _build_source_summary(host, source_record, user_request)
    await expand_document_section(
        host,
        doc_id=target_doc["doc_id"],
        doc_url=target_doc.get("doc_url"),
        title=f"扩写补充：{_file_stem(source_record['file_name'])}",
        body=summary,
        query=existing_section_title or f"{user_request}\n{source_record['file_name']}",
        new_section_title=new_section_title,
    )


async def handle_pending_document_action(
    session_id: str,
    request_id: str,
    content: str,
    *,
    host: MCPHost | None,
) -> dict[str, Any] | None:
    pending = latest_pending_action(session_id, action_type="doc_ops")
    if not pending:
        return None

    payload = dict(pending["payload"])
    op = str(payload.get("op") or "")
    target_doc = dict(payload.get("target_doc") or {})
    source_record = dict(payload.get("source_record") or {})
    if not op or not target_doc or not source_record:
        resolve_pending_action(pending["id"])
        return None

    stage = str(payload.get("stage") or "")

    if stage == "clarify_source_doc":
        selected = _select_source_from_pending(payload, content)
        if not selected:
            return None
        resolve_pending_action(pending["id"])
        return await _continue_with_resolved_operation(
            session_id,
            request_id,
            content=str(payload.get("user_request") or content),
            host=host,
            op=op,
            target_doc=target_doc,
            source_record=selected,
        )

    if stage == "confirm_merge":
        if host is None:
            return _build_result(
                reply="当前文档工具暂时不可用，我先保留了你的操作上下文。稍后工具恢复后可以继续执行。",
                route_detail="doc_runtime_unavailable",
                reasons=["pending_doc_merge_confirmed", "runtime_unavailable"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="runtime_unavailable",
                stop_detail="document_tools_required",
                clarify_needed=True,
                clarify_reason="runtime_unavailable",
            )
        if not is_affirmative(content):
            return None
        resolve_pending_action(pending["id"])
        await _execute_merge(
            host,
            target_doc=target_doc,
            source_record=source_record,
            user_request=str(payload.get("user_request") or ""),
            location_mode=str(payload.get("location_mode") or "append_end"),
            section_title=payload.get("section_title"),
        )
        return _build_result(
            reply=f"已把 `{source_record['file_name']}` 的内容写入 `{target_doc.get('doc_name') or target_doc.get('doc_id')}`。",
            route_detail="merge_into_current_doc",
            reasons=["pending_doc_merge_confirmed"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
            reply_type="doc_updated",
            stop_code="document_updated",
            stop_detail="merge_completed",
        )

    if stage == "clarify_merge_location":
        location_mode = None
        section_title = None
        if wants_append_to_end(content):
            location_mode = "append_end"
        elif wants_new_section(content):
            location_mode = "new_section"
        elif lets_system_choose_location(content):
            location_mode = "relevant_section"
        if not location_mode:
            return None
        resolve_pending_action(pending["id"])
        confirm_payload = {
            **payload,
            "stage": "confirm_merge",
            "location_mode": location_mode,
            "section_title": section_title,
        }
        save_pending_action(session_id, "doc_ops", confirm_payload, request_id=request_id)
        target_label = target_doc.get("doc_name") or target_doc.get("doc_id")
        source_label = source_record.get("file_name")
        action_label = "总结后加入当前文档"
        if location_mode == "append_end":
            action_label += "，位置：文档最后"
        elif location_mode == "new_section":
            action_label += "，位置：新建章节"
        else:
            action_label += "，位置：最相关章节后"
        return _build_result(
            reply=build_merge_confirm_reply(target_label, source_label, action_label),
            route_detail="merge_confirm",
            reasons=["merge_location_resolved"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="merge_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_merge_confirmation",
        )

    if stage == "clarify_replace_scope":
        if host is None:
            return _build_result(
                reply="当前文档工具暂时不可用，我先保留了你的替换意图。稍后工具恢复后可以继续执行。",
                route_detail="doc_runtime_unavailable",
                reasons=["replace_scope_clarify", "runtime_unavailable"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="runtime_unavailable",
                stop_detail="document_tools_required",
                clarify_needed=True,
                clarify_reason="runtime_unavailable",
            )
        scope_hint = content if not wants_auto_replace_scope(content) else str(payload.get("user_request") or "")
        preview_payload = await _prepare_replace_preview(
            host,
            target_doc=target_doc,
            source_record=source_record,
            scope_hint=scope_hint,
        )
        resolve_pending_action(pending["id"])
        save_pending_action(
            session_id,
            "doc_ops",
            {
                **payload,
                "stage": "confirm_replace",
                "section": preview_payload["section"],
            },
            request_id=request_id,
        )
        return _build_result(
            reply=build_replace_preview_reply(preview_payload["section"]["title"], preview_payload["preview"]),
            route_detail="replace_preview",
            reasons=["replace_scope_resolved"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="replace_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_replace_confirmation",
        )

    if stage == "confirm_replace":
        if host is None:
            return _build_result(
                reply="当前文档工具暂时不可用，我先保留了你的替换操作。稍后工具恢复后可以继续执行。",
                route_detail="doc_runtime_unavailable",
                reasons=["pending_doc_replace_confirmed", "runtime_unavailable"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="runtime_unavailable",
                stop_detail="document_tools_required",
                clarify_needed=True,
                clarify_reason="runtime_unavailable",
            )
        if not is_affirmative(content):
            return None
        resolve_pending_action(pending["id"])
        await _execute_replace(
            host,
            target_doc=target_doc,
            source_record=source_record,
            section_payload=payload.get("section") or {},
            user_request=str(payload.get("user_request") or ""),
        )
        return _build_result(
            reply=f"已用 `{source_record['file_name']}` 的内容替换目标文档中的相关部分。",
            route_detail="replace_current_doc_section",
            reasons=["pending_doc_replace_confirmed"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
            reply_type="doc_updated",
            stop_code="document_updated",
            stop_detail="replace_completed",
        )

    if stage == "clarify_expand_target":
        if wants_new_section(content):
            title = _extract_explicit_section_title(content)
            if title:
                resolve_pending_action(pending["id"])
                save_pending_action(
                    session_id,
                    "doc_ops",
                    {**payload, "stage": "confirm_expand_title", "new_section_title": title},
                    request_id=request_id,
                )
                return _build_result(
                    reply=build_title_confirm_reply(title),
                    route_detail="expand_title_confirm",
                    reasons=["expand_new_section_title_explicit"],
                    selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                    reply_type="clarify",
                    stop_code="clarify_waiting_user",
                    stop_detail="expand_title_confirmation_needed",
                    clarify_needed=True,
                    clarify_reason="need_expand_title_confirmation",
                )
            if wants_system_generated_title(content):
                if host is None:
                    return _build_result(
                        reply="当前文档工具暂时不可用，我先保留了你的扩写意图。稍后工具恢复后可以继续执行。",
                        route_detail="doc_runtime_unavailable",
                        reasons=["expand_title_generation_requested", "runtime_unavailable"],
                        selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                        reply_type="clarify",
                        stop_code="runtime_unavailable",
                        stop_detail="document_tools_required",
                        clarify_needed=True,
                        clarify_reason="runtime_unavailable",
                    )
                markdown = await get_doc_markdown(host, doc_id=target_doc["doc_id"], doc_url=target_doc.get("doc_url"))
                generated = _generate_section_title(markdown, source_record)
                resolve_pending_action(pending["id"])
                save_pending_action(
                    session_id,
                    "doc_ops",
                    {**payload, "stage": "confirm_expand_title", "new_section_title": generated},
                    request_id=request_id,
                )
                return _build_result(
                    reply=build_title_confirm_reply(generated),
                    route_detail="expand_title_confirm",
                    reasons=["expand_new_section_title_generated"],
                    selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                    reply_type="clarify",
                    stop_code="clarify_waiting_user",
                    stop_detail="expand_title_confirmation_needed",
                    clarify_needed=True,
                    clarify_reason="need_expand_title_confirmation",
                )
            resolve_pending_action(pending["id"])
            save_pending_action(
                session_id,
                "doc_ops",
                {**payload, "stage": "clarify_expand_title"},
                request_id=request_id,
            )
            return _build_result(
                reply="新建这一节时，你想用什么标题？如果愿意，也可以直接说“你自己起个标题吧”。",
                route_detail="expand_title_needed",
                reasons=["expand_new_section_requested", "title_missing"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="expand_title_needed",
                clarify_needed=True,
                clarify_reason="need_expand_title",
            )

        if lets_system_choose_location(content):
            if host is None:
                return _build_result(
                    reply="当前文档工具暂时不可用，我先保留了你的扩写意图。稍后工具恢复后可以继续执行。",
                    route_detail="doc_runtime_unavailable",
                    reasons=["expand_auto_section_selected", "runtime_unavailable"],
                    selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                    reply_type="clarify",
                    stop_code="runtime_unavailable",
                    stop_detail="document_tools_required",
                    clarify_needed=True,
                    clarify_reason="runtime_unavailable",
                )
            resolve_pending_action(pending["id"])
            await _execute_expand(
                host,
                target_doc=target_doc,
                source_record=source_record,
                user_request=str(payload.get("user_request") or ""),
            )
            return _build_result(
                reply=f"已把 `{source_record['file_name']}` 的内容扩写到 `{target_doc.get('doc_name') or target_doc.get('doc_id')}` 的最相关章节里。",
                route_detail="expand_existing_section",
                reasons=["expand_auto_section_selected"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="doc_updated",
                stop_code="document_updated",
                stop_detail="expand_completed",
            )
        return None

    if stage == "clarify_expand_title":
        title = _extract_explicit_section_title(content)
        if title:
            resolve_pending_action(pending["id"])
            save_pending_action(
                session_id,
                "doc_ops",
                {**payload, "stage": "confirm_expand_title", "new_section_title": title},
                request_id=request_id,
            )
            return _build_result(
                reply=build_title_confirm_reply(title),
                route_detail="expand_title_confirm",
                reasons=["expand_new_section_title_explicit"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="expand_title_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_expand_title_confirmation",
            )
        if wants_system_generated_title(content):
            if host is None:
                return _build_result(
                    reply="当前文档工具暂时不可用，我先保留了你的扩写意图。稍后工具恢复后可以继续执行。",
                    route_detail="doc_runtime_unavailable",
                    reasons=["expand_title_generation_requested", "runtime_unavailable"],
                    selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                    reply_type="clarify",
                    stop_code="runtime_unavailable",
                    stop_detail="document_tools_required",
                    clarify_needed=True,
                    clarify_reason="runtime_unavailable",
                )
            markdown = await get_doc_markdown(host, doc_id=target_doc["doc_id"], doc_url=target_doc.get("doc_url"))
            generated = _generate_section_title(markdown, source_record)
            resolve_pending_action(pending["id"])
            save_pending_action(
                session_id,
                "doc_ops",
                {**payload, "stage": "confirm_expand_title", "new_section_title": generated},
                request_id=request_id,
            )
            return _build_result(
                reply=build_title_confirm_reply(generated),
                route_detail="expand_title_confirm",
                reasons=["expand_new_section_title_generated"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="expand_title_confirmation_needed",
                clarify_needed=True,
                clarify_reason="need_expand_title_confirmation",
            )
        return None

    if stage == "confirm_expand_title":
        if host is None:
            return _build_result(
                reply="当前文档工具暂时不可用，我先保留了你的扩写操作。稍后工具恢复后可以继续执行。",
                route_detail="doc_runtime_unavailable",
                reasons=["expand_title_confirmed", "runtime_unavailable"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="runtime_unavailable",
                stop_detail="document_tools_required",
                clarify_needed=True,
                clarify_reason="runtime_unavailable",
            )
        if not is_affirmative(content):
            return None
        resolve_pending_action(pending["id"])
        await _execute_expand(
            host,
            target_doc=target_doc,
            source_record=source_record,
            user_request=str(payload.get("user_request") or ""),
            new_section_title=str(payload.get("new_section_title") or ""),
        )
        return _build_result(
            reply=f"已新建章节并写入 `{source_record['file_name']}` 的扩写内容。",
            route_detail="expand_new_section",
            reasons=["expand_title_confirmed"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
            reply_type="doc_updated",
            stop_code="document_updated",
            stop_detail="expand_completed",
        )

    return None


def _select_source_from_pending(payload: dict[str, Any], content: str) -> dict[str, Any] | None:
    candidates = payload.get("candidates") or []
    index = parse_candidate_selection(content)
    if index is None:
        return None
    return resolve_record_by_index(candidates, index)


async def _continue_with_resolved_operation(
    session_id: str,
    request_id: str,
    *,
    content: str,
    host: MCPHost | None,
    op: str,
    target_doc: dict[str, Any],
    source_record: dict[str, Any],
) -> dict[str, Any] | None:
    target_label = target_doc.get("doc_name") or target_doc.get("doc_id")
    source_label = source_record.get("file_name")

    if op == "merge":
        if not ("总结后" in content or "摘要后" in content):
            save_pending_action(
                session_id,
                "doc_ops",
                {
                    "op": "merge",
                    "stage": "clarify_merge_location",
                    "target_doc": target_doc,
                    "source_record": _serializable_source(source_record),
                    "user_request": content,
                },
                request_id=request_id,
            )
            return _build_result(
                reply=build_action_clarify_reply(),
                route_detail="merge_action_clarify",
                reasons=["merge_requested", "action_mode_not_clear"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="merge_action_needed",
                clarify_needed=True,
                clarify_reason="need_merge_action",
            )

        if wants_append_to_end(content):
            location_mode = "append_end"
        elif wants_new_section(content):
            location_mode = "new_section"
        elif lets_system_choose_location(content):
            location_mode = "relevant_section"
        else:
            save_pending_action(
                session_id,
                "doc_ops",
                {
                    "op": "merge",
                    "stage": "clarify_merge_location",
                    "target_doc": target_doc,
                    "source_record": _serializable_source(source_record),
                    "user_request": content,
                },
                request_id=request_id,
            )
            return _build_result(
                reply=build_location_clarify_reply(),
                route_detail="merge_location_clarify",
                reasons=["merge_requested", "location_not_clear"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="merge_location_needed",
                clarify_needed=True,
                clarify_reason="need_merge_location",
            )

        save_pending_action(
            session_id,
            "doc_ops",
            {
                "op": "merge",
                "stage": "confirm_merge",
                "target_doc": target_doc,
                "source_record": _serializable_source(source_record),
                "user_request": content,
                "location_mode": location_mode,
            },
            request_id=request_id,
        )
        action_label = "总结后加入当前文档"
        if location_mode == "append_end":
            action_label += "，位置：文档最后"
        elif location_mode == "new_section":
            action_label += "，位置：新建章节"
        else:
            action_label += "，位置：最相关章节后"
        return _build_result(
            reply=build_merge_confirm_reply(target_label, source_label, action_label),
            route_detail="merge_confirm",
            reasons=["merge_requested", "ready_to_confirm"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="merge_confirmation_needed",
            clarify_needed=True,
            clarify_reason="need_merge_confirmation",
        )

    if op == "replace":
        save_pending_action(
            session_id,
            "doc_ops",
            {
                "op": "replace",
                "stage": "clarify_replace_scope",
                "target_doc": target_doc,
                "source_record": _serializable_source(source_record),
                "user_request": content,
            },
            request_id=request_id,
        )
        return _build_result(
            reply="你想替换当前文档里的哪一部分？如果你愿意，也可以直接说“你自己看着替换吧”。",
            route_detail="replace_scope_clarify",
            reasons=["replace_requested", "scope_not_clear"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="replace_scope_needed",
            clarify_needed=True,
            clarify_reason="need_replace_scope",
        )

    if op == "expand":
        if host is None:
            save_pending_action(
                session_id,
                "doc_ops",
                {
                    "op": "expand",
                    "stage": "clarify_expand_target",
                    "target_doc": target_doc,
                    "source_record": _serializable_source(source_record),
                    "user_request": content,
                },
                request_id=request_id,
            )
            return _build_result(
                reply=build_section_clarify_reply(),
                route_detail="expand_target_clarify",
                reasons=["expand_requested", "runtime_unavailable_for_structure_check"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="expand_target_needed",
                clarify_needed=True,
                clarify_reason="need_expand_target",
            )
        markdown = await get_doc_markdown(host, doc_id=target_doc["doc_id"], doc_url=target_doc.get("doc_url"))
        sections = parse_markdown_sections(markdown)
        if len(sections) >= 2:
            await _execute_expand(
                host,
                target_doc=target_doc,
                source_record=source_record,
                user_request=content,
            )
            return _build_result(
                reply=f"已把 `{source_record['file_name']}` 的内容扩写到当前文档的最相关章节里。",
                route_detail="expand_existing_section",
                reasons=["expand_requested", "document_structure_clear"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
                reply_type="doc_updated",
                stop_code="document_updated",
                stop_detail="expand_completed",
            )

        save_pending_action(
            session_id,
            "doc_ops",
            {
                "op": "expand",
                "stage": "clarify_expand_target",
                "target_doc": target_doc,
                "source_record": _serializable_source(source_record),
                "user_request": content,
            },
            request_id=request_id,
        )
        return _build_result(
            reply=build_section_clarify_reply(),
            route_detail="expand_target_clarify",
            reasons=["expand_requested", "document_structure_not_clear"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_label),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="expand_target_needed",
            clarify_needed=True,
            clarify_reason="need_expand_target",
        )

    return None


async def handle_document_operation_request(
    session_id: str,
    request_id: str,
    content: str,
    *,
    host: MCPHost | None,
) -> dict[str, Any] | None:
    pending_result = await handle_pending_document_action(session_id, request_id, content, host=host)
    if pending_result:
        return pending_result

    merge_requested = is_merge_kb_doc_request(content)
    replace_requested = is_replace_with_kb_doc_request(content)
    expand_requested = is_expand_from_kb_doc_request(content)
    if not any((merge_requested, replace_requested, expand_requested)):
        return None

    target_doc = _resolve_target_doc(session_id)
    if not target_doc:
        return _build_result(
            reply="我还没有识别到当前绑定的目标文档。你可以先给我当前文档的链接，或者先明确你要编辑哪一份文档。",
            route_detail="target_doc_missing",
            reasons=["document_operation_requested", "target_doc_missing"],
            selected_target=build_selected_target("document", None, None, clear_reason="no_bound_doc"),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="target_doc_needed",
            clarify_needed=True,
            clarify_reason="need_target_doc",
        )

    source_record = _resolve_source_record(session_id, content)
    if not source_record:
        candidates = match_pdf_records(content, limit=3)
        if candidates:
            save_pending_action(
                session_id,
                "doc_ops",
                {
                    "op": "merge" if merge_requested else "replace" if replace_requested else "expand",
                    "stage": "clarify_source_doc",
                    "target_doc": target_doc,
                    "candidates": [_serializable_source(item) for item in candidates],
                    "user_request": content,
                },
                request_id=request_id,
            )
            lines = ["我先匹配到了这些知识库候选文档："]
            for index, item in enumerate(candidates, start=1):
                lines.append(f"{index}. {item['file_name']}：{item.get('match_reason') or '文件名相关'}")
            lines.append("请告诉我你指的是哪一篇。")
            return _build_result(
                reply="\n".join(lines),
                route_detail="source_doc_candidates",
                reasons=["document_operation_requested", "source_doc_ambiguous"],
                selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
                reply_type="clarify",
                stop_code="clarify_waiting_user",
                stop_detail="source_doc_needed",
                clarify_needed=True,
                clarify_reason="need_source_doc",
            )
        return _build_result(
            reply="我还没有匹配到明确的知识库来源文档。你可以直接告诉我文件名，或者给我更具体的关键词。",
            route_detail="source_doc_missing",
            reasons=["document_operation_requested", "source_doc_missing"],
            selected_target=build_selected_target("document", target_doc.get("doc_id"), target_doc.get("doc_name")),
            reply_type="clarify",
            stop_code="clarify_waiting_user",
            stop_detail="source_doc_needed",
            clarify_needed=True,
            clarify_reason="need_source_doc",
        )
    op = "merge" if merge_requested else "replace" if replace_requested else "expand"
    return await _continue_with_resolved_operation(
        session_id,
        request_id,
        content=content,
        host=host,
        op=op,
        target_doc=target_doc,
        source_record=source_record,
    )


def _serializable_source(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_name": record["file_name"],
        "stored_name": record["stored_name"],
        "stored_path": record["stored_path"],
        "source_type": record["source_type"],
        "match_reason": record.get("match_reason", ""),
        "match_score": record.get("match_score", 0),
    }
