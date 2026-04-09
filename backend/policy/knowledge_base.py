from __future__ import annotations

import re
from typing import Any


ORDINAL_RE = re.compile(r"第\s*([0-9]{1,2})\s*[个篇份]?")


def _text(content: str) -> str:
    return str(content or "").strip()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def is_affirmative(text: str) -> bool:
    normalized = _text(text)
    return normalized in {
        "是",
        "好的",
        "好",
        "可以",
        "行",
        "行，就这个",
        "就这个",
        "就这样",
        "可以，就这样",
        "确认",
    }


def is_kb_list_request(text: str) -> bool:
    normalized = _text(text)
    if not _contains_any(normalized, ("知识库",)):
        return False
    return _contains_any(normalized, ("几篇", "列一下", "列表", "文件", "文章"))


def wants_brief_answer(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("简略", "简短", "简单说", "只告诉我数量", "先说数量"))


def asks_upload_label(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("哪个是上传文档", "哪个是我上传的", "哪个是刚上传的"))


def asks_recent_uploaded_file(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("刚上传的文档", "刚上传的文件", "刚上传的 pdf", "刚上传的PDF"))


def is_related_doc_query(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("相关的文档", "相关材料", "有没有讲这个方向", "有没有和")) and _contains_any(
        normalized,
        ("知识库", "文档", "材料"),
    )


def is_best_doc_query(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("最适合回答", "最相关的文档", "最推荐的文档"))


def is_export_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("发给我", "给我原文", "给我原文件", "导出")) and _contains_any(
        normalized,
        ("知识库", "PDF", "pdf", "文档"),
    )


def is_delete_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("删掉", "删除", "移除")) and _contains_any(
        normalized,
        ("知识库", "文档", "文件", "那篇"),
    )


def parse_candidate_selection(text: str) -> int | None:
    normalized = _text(text)
    match = ORDINAL_RE.search(normalized)
    if match:
        return max(int(match.group(1)) - 1, 0)
    if normalized in {"这个", "就这个"}:
        return 0
    return None


def wants_original_file(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("原文件", "原 pdf", "原PDF", "原文给我", "发原文", "发文件"))


def wants_summary(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("摘要", "总结", "概述", "主要内容"))


def wants_generate_doc(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("生成文档", "写成文档", "生成一份文档", "出一份文档"))


def wants_summary_and_doc(text: str) -> bool:
    normalized = _text(text)
    return wants_summary(normalized) and wants_generate_doc(normalized)


def candidate_action_is_clear(text: str) -> bool:
    return wants_original_file(text) or wants_summary(text) or wants_generate_doc(text)


def build_candidate_lines(
    candidates: list[dict[str, Any]],
    *,
    reasons: list[str] | None = None,
    limit: int = 3,
) -> str:
    lines: list[str] = []
    reason_list = reasons or []
    for index, item in enumerate(candidates[:limit], start=1):
        line = f"{index}. {item['file_name']}"
        if index - 1 < len(reason_list) and reason_list[index - 1]:
            line += f"：{reason_list[index - 1]}"
        lines.append(line)
    return "\n".join(lines)


def build_kb_list_reply(
    records: list[dict[str, Any]],
    *,
    show_only_count: bool = False,
    limit: int = 10,
) -> str:
    total = len(records)
    if show_only_count:
        return f"知识库里目前有 {total} 篇 PDF。如需我可以继续列出前 {min(limit, total)} 篇。"

    lines = [f"知识库里目前有 {total} 篇 PDF。"]
    if total:
        lines.append(f"先列前 {min(limit, total)} 篇：")
        for index, item in enumerate(records[:limit], start=1):
            lines.append(f"{index}. {item['file_name']}")
    return "\n".join(lines)


def build_related_candidates_reply(
    query: str,
    candidates: list[dict[str, Any]],
    reasons: list[str],
    *,
    recommended_index: int | None = None,
    intro: str | None = None,
) -> str:
    lines: list[str] = []
    if intro:
        lines.append(intro)
    else:
        lines.append(f"我先找到了和“{query}”比较相关的候选文档：")
    lines.append(build_candidate_lines(candidates, reasons=reasons, limit=3))
    if recommended_index is not None and 0 <= recommended_index < min(3, len(candidates)):
        lines.append(
            f"我目前最推荐的是第 {recommended_index + 1} 个：{candidates[recommended_index]['file_name']}。"
        )
    lines.append("请告诉我你想针对哪一篇文档做什么操作。")
    return "\n".join(lines)


def build_export_clarify_reply(file_name: str) -> str:
    return (
        f"你是要我把 `{file_name}` 的原 PDF 发回聊天，还是要我先给你摘要/主要内容？"
    )


def build_delete_confirm_reply(file_name: str) -> str:
    return f"我匹配到的是 `{file_name}`。如果确认删除，请直接回复“确认删除”。"


def build_recent_upload_reply(record: dict[str, Any] | None, fallback_candidates: list[dict[str, Any]] | None = None) -> str:
    if record:
        return f"你最近上传的文档是 `{record['file_name']}`。"

    if fallback_candidates:
        lines = ["我没有找到明确的最近上传记录，但有这些候选文件："]
        lines.append(build_candidate_lines(fallback_candidates, limit=3))
        return "\n".join(lines)

    return "我当前没有识别到明确的最近上传文件。"
