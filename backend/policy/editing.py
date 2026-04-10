from __future__ import annotations

from typing import Any


def _text(content: str) -> str:
    return str(content or "").strip()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def is_merge_kb_doc_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("知识库",)) and _contains_any(normalized, ("加入当前文档", "加入当前正在编辑的文档", "加到当前文档"))


def is_replace_with_kb_doc_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("知识库", "当前文档")) and _contains_any(normalized, ("替换", "替换掉")) and _contains_any(
        normalized,
        ("相关部分", "这一部分", "那一部分"),
    )


def is_expand_from_kb_doc_request(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("知识库", "当前文档")) and _contains_any(normalized, ("扩写", "扩展")) and _contains_any(
        normalized,
        ("一节", "一个章节", "章节"),
    )


def wants_append_to_end(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("文档最后", "最后面", "最后一节后面", "末尾"))


def lets_system_choose_location(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("你看着加", "你自己决定位置", "看情况加", "自动选择位置"))


def wants_new_section(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("新建一节", "新建章节", "加一个新章节"))


def wants_system_generated_title(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("你自己起个标题", "你来起标题", "你定标题"))


def wants_auto_replace_scope(text: str) -> bool:
    normalized = _text(text)
    return _contains_any(normalized, ("你自己看着替换", "你自己判断替换", "你看着替换"))


def is_affirmative(text: str) -> bool:
    normalized = _text(text)
    return normalized in {"是", "好", "好的", "可以", "行", "行，就这样", "就这样", "确认"}


def build_doc_target_confirm_reply(doc_name: str | None, doc_url: str | None) -> str:
    label = doc_name or doc_url or "当前绑定文档"
    return f"我理解你现在指的是这份目标文档：`{label}`。如果不是，请直接告诉我正确的文档。"


def build_merge_confirm_reply(target_label: str, source_label: str, action_label: str) -> str:
    return (
        "我先确认一下这次操作：\n"
        f"- 目标文档：`{target_label}`\n"
        f"- 来源文档：`{source_label}`\n"
        f"- 动作：{action_label}\n"
        "如果没问题，你可以直接回复“确认”。"
    )


def build_replace_preview_reply(section_title: str, excerpt: str) -> str:
    return (
        "我准备替换当前文档里的这部分内容：\n"
        f"- 章节：`{section_title}`\n\n"
        f"{excerpt}\n\n"
        "如果没问题，请直接回复“确认”。"
    )


def build_title_confirm_reply(title: str) -> str:
    return f"我准备把新章节标题定为：`{title}`。如果没问题，请直接回复“确认”。"


def build_location_clarify_reply() -> str:
    return "你想把这部分内容加到哪里？例如：文档最后、某个章节后面，或者让我根据当前结构自动判断。"


def build_action_clarify_reply() -> str:
    return "这里的“加入”我先不擅自解释。你是希望我总结后写进去，还是按原文内容并入？"


def build_section_clarify_reply() -> str:
    return "你想把它扩写成当前文档里的哪一节？如果你愿意，我也可以先根据当前结构帮你找最相关的章节。"
