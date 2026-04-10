from __future__ import annotations

import re
from typing import Any


ORDINAL_RE = re.compile(r"第\s*([0-9]{1,2})\s*(?:个|篇|份)?")
RENAME_TARGET_RE = re.compile(
    r"(?:改名为|重命名为|名字为|名称为|名字改成|名称改成|改成|换成|改为|命名为|叫做|叫)\s*[`\"']?([^\n`\"']+?)(?:[`\"']?\s*$|[`\"']?\s*[，。,！!？?])"
)
RENAME_NAME_STYLE_RE = re.compile(
    r"(?:名字|名称|文件名|文档名)\s*(?:为|改为|改成|换成|叫做|叫)\s*[`\"']?([^\n`\"']+?)(?:[`\"']?\s*$|[`\"']?\s*[，。,！!？?])"
)
KB_FILE_MANAGEMENT_INTENTS = {"kb.export", "kb.rename", "kb.delete"}


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
    if _contains_any(normalized, ("全列出来", "全部列出来", "所有文件", "全部文件", "知识库现有哪些文件")):
        return True
    if not _contains_any(normalized, ("知识库",)):
        return False
    return _contains_any(normalized, ("几篇", "列一下", "列表", "文件", "文章"))


def is_kb_list_followup_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("全列出来", "全部列出来", "都列出来", "所有", "全部", "不是只有前"))


def wants_full_list(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("所有", "全部", "全列", "都列出来", "不是只有前"))


def wants_brief_answer(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("简略", "简短", "简单说", "只告诉我数量", "先说数量"))


def asks_upload_label(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("哪个是上传文档", "哪个是我上传的", "哪个是刚上传的"))


def asks_recent_uploaded_file(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("刚上传的文档", "刚上传的文件", "刚上传的 pdf", "刚上传的PDF"))


def is_uploaded_file_list_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(
        normalized,
        ("我上传的", "已上传的", "上传过的", "之前上传过", "上传的文件", "上传的文档"),
    )


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


def is_rename_request(text: str) -> bool:
    normalized = _text(text)
    direct_rename = _contains_any(normalized, ("改名", "重命名", "换个名字", "改个名字"))
    rename_with_name_field = (
        _contains_any(normalized, ("名字", "名称", "文件名", "文档名"))
        and _contains_any(normalized, ("修改", "改一下", "改下", "改为", "改成", "换成", "命名"))
    )
    target_hint = _contains_any(
        normalized,
        ("知识库", "文件", "文档", ".pdf", "PDF", "这些文件", "那篇", "第", "份", "篇", "这个"),
    )
    return target_hint and (direct_rename or rename_with_name_field)


def parse_candidate_selection(text: str) -> int | None:
    normalized = _text(text)
    match = ORDINAL_RE.search(normalized)
    if match:
        return max(int(match.group(1)) - 1, 0)
    if normalized in {"这个", "就这个"}:
        return 0
    return None


def is_kb_file_management_intent(intent_packet: dict[str, Any] | None) -> bool:
    if not isinstance(intent_packet, dict):
        return False
    family = str(intent_packet.get("intent_family") or "").strip()
    intent = str(intent_packet.get("intent") or "").strip()
    return family == "knowledge_base" and intent in KB_FILE_MANAGEMENT_INTENTS


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


def parse_new_file_name(text: str) -> str | None:
    normalized = _text(text)
    explicit_pdfs = re.findall(r"([0-9A-Za-z\u4e00-\u9fff._-]+\.pdf)", normalized, flags=re.IGNORECASE)
    if len(explicit_pdfs) >= 2:
        return explicit_pdfs[-1]

    match = RENAME_TARGET_RE.search(normalized)
    if not match:
        match = RENAME_NAME_STYLE_RE.search(normalized)
    if not match:
        return None
    candidate = match.group(1).strip().strip("`\"'")
    candidate = candidate.rstrip("，。,！!？?")
    return candidate or None


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
    show_all: bool = False,
    scope_label: str = "知识库",
) -> str:
    total = len(records)
    if show_only_count:
        return f"{scope_label}里目前共有 {total} 个 PDF 文件。"

    lines = [f"{scope_label}里目前共有 {total} 个 PDF 文件。"]
    if total:
        selected_records = records if show_all else records[:limit]
        lines.append("全部列出如下：" if show_all or total <= limit else f"先列前 {min(limit, total)} 个：")
        for index, item in enumerate(selected_records, start=1):
            lines.append(f"{index}. {item['file_name']}")
        if not show_all and total > limit:
            lines.append(f"如果你要看全部 {total} 个文件，直接说“把所有文件都列出来”。")
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


def build_rename_intro_reply() -> str:
    return (
        "可以处理知识库文件改名，但当前只支持重命名你上传进知识库的 PDF。"
        "请告诉我你想改的文件名，以及新名称。"
    )


def build_rename_new_name_reply(file_name: str) -> str:
    return f"你想把 `{file_name}` 改成什么新名字？请直接告诉我新的文件名。"


def build_rename_candidates_reply(candidates: list[dict[str, Any]]) -> str:
    lines = ["我先匹配到了这些候选文件：", build_candidate_lines(candidates, limit=3)]
    lines.append("请告诉我要改哪一个文件，以及你想改成什么名字。")
    return "\n".join(lines)


def build_rename_confirm_reply(old_file_name: str, new_file_name: str) -> str:
    return f"我准备把 `{old_file_name}` 改名为 `{new_file_name}`。如果确认，请直接回复“确认改名”。"


def build_rename_unsupported_reply(file_name: str) -> str:
    return f"`{file_name}` 属于固定知识库材料，当前不支持直接改名。你上传的 PDF 文件支持改名。"


def build_recent_upload_reply(record: dict[str, Any] | None, fallback_candidates: list[dict[str, Any]] | None = None) -> str:
    if record:
        return f"你最近上传的文档是 `{record['file_name']}`。"

    if fallback_candidates:
        lines = ["我没有找到明确的最近上传记录，但有这些候选文件："]
        lines.append(build_candidate_lines(fallback_candidates, limit=3))
        return "\n".join(lines)

    return "我当前没有识别到明确的最近上传文件。"
