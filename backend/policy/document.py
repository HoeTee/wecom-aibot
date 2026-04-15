from __future__ import annotations


def is_fresh_document_request(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    fresh_tokens = ("重新生成", "重新写一份", "重新出一份", "新生成一份", "新建一份")
    return "文档" in text and any(token in text for token in fresh_tokens)
