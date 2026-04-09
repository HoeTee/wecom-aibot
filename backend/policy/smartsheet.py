from __future__ import annotations

from typing import Any


def _text(content: str) -> str:
    return str(content or "").strip()


def is_smartsheet_intent(intent_hint: dict[str, Any] | None) -> bool:
    if not isinstance(intent_hint, dict):
        return False
    return str(intent_hint.get("intent_family") or "").strip() == "smartsheet"


def detect_smartsheet_request(content: str, intent_hint: dict[str, Any] | None = None) -> bool:
    if is_smartsheet_intent(intent_hint):
        return True
    text = _text(content)
    has_table = any(token in text.lower() for token in ("smartsheet",)) or "智能表格" in text
    has_create = any(token in text for token in ("生成", "创建", "整理", "汇总"))
    return has_table and has_create


def infer_smartsheet_source_scope(content: str, intent_hint: dict[str, Any] | None = None) -> str:
    params = intent_hint.get("params") if isinstance(intent_hint, dict) else {}
    if isinstance(params, dict):
        scope = str(params.get("source_scope") or "").strip().lower()
        if scope in {"knowledge_base", "knowledge-base", "kb"}:
            return "knowledge_base"

    text = _text(content)
    if "知识库" in text:
        return "knowledge_base"
    return "manual"


def infer_smartsheet_name(content: str, intent_hint: dict[str, Any] | None = None) -> str:
    params = intent_hint.get("params") if isinstance(intent_hint, dict) else {}
    if isinstance(params, dict):
        name = str(params.get("doc_name") or params.get("table_name") or "").strip()
        if name:
            return name

    text = _text(content)
    if "知识库" in text:
        return "知识库文章整理智能表格"
    return "智能表格"


def build_smartsheet_success_reply(doc_name: str, *, row_count: int, doc_url: str | None = None) -> str:
    parts = [f"已创建智能表格 `{doc_name}`。"]
    if row_count > 0:
        parts.append(f"我已经先按知识库内容整理了 {row_count} 条记录。")
    if doc_url:
        parts.append(f"表格链接：{doc_url}")
    return "\n".join(parts)


def build_smartsheet_partial_reply(
    doc_name: str,
    *,
    reason: str,
    doc_url: str | None = None,
) -> str:
    parts = [f"智能表格 `{doc_name}` 已创建，但后续初始化没有完全完成。", f"原因：{reason}"]
    if doc_url:
        parts.append(f"表格链接：{doc_url}")
    return "\n".join(parts)


def build_smartsheet_auth_expired_reply(result_payload: dict[str, Any]) -> str:
    help_message = str(result_payload.get("help_message") or "").strip()
    errmsg = str(result_payload.get("errmsg") or "").strip() or "企业微信文档授权已过期。"
    if help_message:
        return f"{errmsg}\n{help_message}"
    return errmsg


def is_authorization_expired(result_payload: dict[str, Any]) -> bool:
    errcode = result_payload.get("errcode")
    errmsg = str(result_payload.get("errmsg") or "").lower()
    return errcode == 850003 or "authorization expired" in errmsg
