from __future__ import annotations


def is_fresh_document_request(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    fresh_tokens = ("重新生成", "重新写一份", "重新出一份", "新生成一份", "新建一份")
    return "文档" in text and any(token in text for token in fresh_tokens)


def user_requested_table(content: str) -> bool:
    text = str(content or "").strip()
    return any(token in text for token in ("表格", "对比表", "comparison table"))


def user_requested_structured_summary(content: str) -> bool:
    text = str(content or "").strip()
    required_tokens = ("背景", "每篇论文摘要", "横向对比", "结论与建议")
    return all(token in text for token in required_tokens)


def validate_doc_tool_arguments(
    function_name: str,
    args_dict: dict[str, object],
    latest_user_message: str,
) -> str | None:
    name = function_name.lower()
    if "edit_doc" not in name and "doc_content" not in name:
        return None

    content = str(args_dict.get("content", "") or "").strip()
    if not content:
        return None

    if "..." in content:
        return "文档内容校验失败：不允许写入占位符 `...`。"

    if user_requested_structured_summary(latest_user_message):
        required_sections = ("背景", "每篇论文摘要", "横向对比", "结论与建议")
        missing_sections = [section for section in required_sections if section not in content]
        if missing_sections:
            return "文档内容校验失败：缺少必需章节：" + "、".join(missing_sections)

    if not user_requested_table(latest_user_message):
        forbidden_table_markers = ("## 5.", "### 5.", "技术对比表")
        if any(marker in content for marker in forbidden_table_markers):
            return "文档内容校验失败：当前轮次不允许提前生成对比表。"

    return None
