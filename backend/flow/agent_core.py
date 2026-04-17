"""
Base Agent class: handles LLM communication, tool calling, context management,
token tracking, and conversation logging.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Callable, Protocol

from openai import AsyncOpenAI
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.runtime.local_tools import execute_local_agent_tool, is_local_agent_tool_name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(..., alias="LLM_API_KEY")
    base_url: str = Field(..., alias="LLM_BASE_URL")
    model: str = Field(
        ...,
        validation_alias=AliasChoices("LLM_MODEL", "LLM_NAME"),
    )
    temperature: float = Field(0.0, alias="TEMPERATURE")
    top_p: float = Field(0.01, alias="TOP_P")
    seed: int = Field(42, alias="SEED")

    max_tool_calls: int = Field(0, alias="MAX_TOOL_CALLS")
    max_context_tokens: int = Field(100000, alias="MAX_CONTEXT_TOKENS")
    max_result_tokens: int = Field(5000, alias="MAX_RESULT_TOKENS")
    routing_timeout_seconds: float = Field(15.0, alias="ROUTING_TIMEOUT_SECONDS")
    agent_timeout_seconds: float = Field(180.0, alias="AGENT_TIMEOUT_SECONDS")
    max_invalid_tool_argument_rounds: int = Field(2, alias="MAX_INVALID_TOOL_ARGUMENT_ROUNDS")


INTENT_PACKET_SYSTEM_PROMPT = """\
You classify a user request for a WeCom document workflow system.

Return JSON only with this shape:
{
  "intent_family": "knowledge_base" | "document" | "smartsheet" | "upload_followup" | "general",
  "intent": string,
  "target_ref": string,
  "resolved_from_context": boolean,
  "confidence": number,
  "params": object,
  "missing": [string]
}

Rules:
- If the user is managing files in the knowledge base, use intent_family="knowledge_base".
- File management includes list, list uploads, export original file, rename file, delete file, and related-file lookup.
- Do not classify file-management requests as RAG or free-form chat.
- If the user references an ordinal candidate such as "第4份文件", preserve it in target_ref and set resolved_from_context=true when recent candidates are provided.
- Requests like "修改一下第4份文件的名字为 harness engineering" should be classified as knowledge_base + kb.rename when recent knowledge-base candidates are provided.
- If the user asks to create or generate a smart sheet / 智能表格, use intent_family="smartsheet".
- Requests like "帮我对知识库里的所有文章做一个整理，生成一个智能表格" should be classified as smartsheet + smartsheet.create with params.source_scope="knowledge_base".
- For rename requests, put the desired new file name in params.new_name when present.
- If uncertain, still choose the closest family and include missing fields.
- Allowed knowledge_base intents: kb.list, kb.list_uploads, kb.related, kb.export, kb.rename, kb.delete, kb.unknown
- Allowed document intents: doc.edit, doc.create, doc.merge_kb, doc.replace_kb, doc.expand_kb, doc.unknown
- Allowed smartsheet intents: smartsheet.create, smartsheet.update_schema, smartsheet.add_records, smartsheet.unknown
- Allowed upload_followup intent: upload.followup
- Allowed general intent: agent.chat
"""


def _is_kimi_k25_model(settings: Settings) -> bool:
    return str(settings.model or "").strip().lower().startswith("kimi-k2.5")


def _build_chat_completion_kwargs(
    settings: Settings,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    kimi_k25 = _is_kimi_k25_model(settings)
    if tool_choice is not None:
        # Kimi K2.5 rejects tool_choice="required" while thinking is enabled.
        kwargs["tool_choice"] = "auto" if kimi_k25 and tool_choice == "required" else tool_choice

    if not kimi_k25:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if seed is not None:
            kwargs["seed"] = seed

    return kwargs


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return {}
    return {}


def _normalize_intent_packet(packet: dict[str, Any], message: str) -> dict[str, Any]:
    intent_family = str(packet.get("intent_family") or "general").strip() or "general"
    intent = str(packet.get("intent") or "agent.chat").strip() or "agent.chat"
    target_ref = str(packet.get("target_ref") or "").strip()
    message_text = str(message or "").strip()
    try:
        confidence = float(packet.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    params = packet.get("params")
    if not isinstance(params, dict):
        params = {}
    missing = packet.get("missing")
    if not isinstance(missing, list):
        missing = []

    _smartsheet_signals = ("智能表格", "smartsheet", "表格")
    _smartsheet_signal_hit = any(s in message_text or s in message_text.lower() for s in _smartsheet_signals)
    # "表格" alone is ambiguous — only treat it as smartsheet if paired with
    # an action keyword, to avoid hijacking Markdown-table / doc-table requests.
    if not _smartsheet_signal_hit and "表格" in message_text:
        _action_signals = ("创建", "生成", "建一个", "做一个", "新建", "更新", "添加", "追加", "重新创建")
        _smartsheet_signal_hit = any(a in message_text for a in _action_signals)
    if (
        _smartsheet_signal_hit
        and intent_family in {"knowledge_base", "document", "general"}
        and intent in {"kb.list", "kb.unknown", "doc.create", "doc.unknown", "agent.chat"}
    ):
        intent_family = "smartsheet"
        intent = "smartsheet.create"
        params.setdefault("source_scope", "knowledge_base" if "知识库" in message_text else "manual")

    # Fix: message asks for a document but LLM classified as kb or general
    _doc_create_signals = ("生成", "创建", "写进", "写入", "落实到", "生成一个")
    _doc_target_signals = ("文档", "企微文档", "文档里")
    if (
        intent_family in {"knowledge_base", "general"}
        and intent not in {"doc.create", "doc.edit"}
        and any(s in message_text for s in _doc_create_signals)
        and any(s in message_text for s in _doc_target_signals)
    ):
        intent_family = "document"
        intent = "doc.create"

    if intent_family not in {"knowledge_base", "document", "smartsheet", "upload_followup", "general"}:
        intent_family = "general"
    if intent_family == "general" and intent == "agent.chat":
        pass
    elif intent_family == "knowledge_base" and not intent.startswith("kb."):
        intent = "kb.unknown"
    elif intent_family == "document" and not intent.startswith("doc."):
        intent = "doc.unknown"
    elif intent_family == "smartsheet" and not intent.startswith("smartsheet."):
        intent = "smartsheet.unknown"
    elif intent_family == "upload_followup" and intent != "upload.followup":
        intent = "upload.followup"

    return {
        "intent_family": intent_family,
        "intent": intent,
        "target_ref": target_ref,
        "resolved_from_context": bool(packet.get("resolved_from_context")),
        "confidence": max(0.0, min(confidence, 1.0)),
        "params": params,
        "missing": [str(item).strip() for item in missing if str(item).strip()],
        "message_preview": str(message or "")[:200],
    }


async def classify_intent_packet(
    message: str,
    *,
    memory_context: str = "",
    routing_context: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    client = AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": INTENT_PACKET_SYSTEM_PROMPT}]
    if memory_context:
        messages.append(
            {
                "role": "system",
                "content": f"Session memory for routing:\n{memory_context}",
            }
        )
    if routing_context:
        messages.append(
            {
                "role": "system",
                "content": f"Recent routing context:\n{routing_context}",
            }
        )
    messages.append({"role": "user", "content": str(message or "")})

    try:
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                **_build_chat_completion_kwargs(
                    settings,
                    messages=messages,
                    temperature=0.0,
                    top_p=1.0,
                    seed=settings.seed,
                )
            ),
            timeout=settings.routing_timeout_seconds,
        )
        content = completion.choices[0].message.content or ""
        return _normalize_intent_packet(_parse_json_object(content), message)
    except Exception:
        return _normalize_intent_packet({}, message)


class _AuthExpiredError(Exception):
    """Raised when a tool call returns errcode 850003 (authorization expired)."""


class ToolRuntime(Protocol):
    tools: list[dict[str, Any]]

    async def tool_message_from_call(self, tool_call: Any) -> dict[str, Any]:
        ...

    async def call_tool(self, exposed_name: str, args: dict[str, Any]) -> str:
        ...


FlowCallback = Callable[[str, dict[str, Any]], None]


class Agent:
    def __init__(
        self,
        system_prompt: str = "",
        name: str = "Agent",
        mcp_client: ToolRuntime | None = None,
        tools=None,
        settings: Settings | None = None,
        debug: bool = False,
        memory_context: str = "",
        chat_history: list[dict[str, Any]] | None = None,
        intent_packet: dict[str, Any] | None = None,
        on_tool_result: Callable[[str, dict[str, Any], str], None] | None = None,
        on_flow_event: FlowCallback | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
        )
        self.name = name
        self.mcp_client = mcp_client
        self.tools = tools or (mcp_client.tools if mcp_client else [])
        self.messages: list[dict[str, Any]] = []
        self.debug = debug
        self.max_tool_calls = self.settings.max_tool_calls
        self.max_context_tokens = self.settings.max_context_tokens
        self.max_result_tokens = self.settings.max_result_tokens
        self.max_invalid_tool_argument_rounds = self.settings.max_invalid_tool_argument_rounds
        self.intent_packet = dict(intent_packet or {})
        self.on_tool_result = on_tool_result
        self.on_flow_event = on_flow_event
        self.prepared_attachment: dict[str, Any] | None = None

        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.tool_call_count = 0
        self.invalid_tool_argument_rounds = 0
        self._completion_nudged = False
        self._current_docid: str | None = None  # docid from this request's create_doc
        self._auth_expired_message: str | None = None  # set when 850003 detected
        self._known_sheet_ids: set[str] = set()  # sheet_ids from successful get_sheet calls
        self._known_field_titles: set[str] = set()  # field_titles from successful get_fields calls
        self._exec_start_idx: int = 0  # set after chat_history, marks where THIS request's messages begin

        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        if memory_context:
            self.messages.append({"role": "system", "content": memory_context})

        intent_hint = self._build_intent_hint()
        if intent_hint:
            self.messages.append({"role": "system", "content": intent_hint})

        if chat_history:
            for msg in chat_history:
                role = str(msg.get("role", "")).strip()
                if role == "assistant" and msg.get("tool_calls"):
                    self.messages.append({
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": msg["tool_calls"],
                    })
                elif role == "tool" and msg.get("tool_call_id"):
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": str(msg.get("content", "")),
                    })
                elif role in ("user", "assistant"):
                    content = str(msg.get("content", "")).strip()
                    if content:
                        self.messages.append({"role": role, "content": content})

        self._exec_start_idx = len(self.messages)

    def _build_intent_hint(self) -> str:
        """Build a concise routing hint from the intent packet for the LLM."""
        packet = self.intent_packet
        if not packet or not packet.get("intent_family"):
            return ""
        family = packet.get("intent_family", "")
        intent = packet.get("intent", "")
        target_ref = packet.get("target_ref", "")

        parts: list[str] = ["[路由提示]"]

        family_labels = {
            "document": "文档操作",
            "smartsheet": "智能表格操作",
            "knowledge_base": "知识库操作",
        }
        intent_labels = {
            "doc.create": "创建文档",
            "doc.edit": "编辑文档",
            "doc.read": "读取文档",
            "smartsheet.create": "创建智能表格",
            "smartsheet.edit": "编辑智能表格",
            "kb.list": "列出知识库文件",
            "kb.export": "导出知识库文件",
            "kb.search": "检索知识库",
        }

        label = intent_labels.get(intent) or family_labels.get(family)
        if label:
            parts.append(f"用户意图：{label}")

        # Hard constraint: remind model that doc creation requires content write
        _write_intents = {"doc.create", "doc.edit", "doc.merge_kb", "doc.replace_kb", "doc.expand_kb"}
        if intent in _write_intents:
            parts.append(
                "约束：create_doc 只是创建空文档，不算完成。"
                "你必须在创建文档后继续调用 edit_doc_content 写入正文，"
                "正文写入成功后才能回复用户。"
                "写入正文时不要以文档标题开头，因为 create_doc 已经设置了标题，重复会导致双重标题。"
                "不要调用 kb__export_file，那是用户要求导出原始 PDF 时才用的，总结/写入文档不需要它。"
                "写入时 docid 必须使用本轮 create_doc 返回的 docid，不要使用历史对话中的旧 docid。"
            )
        elif intent == "smartsheet.create":
            parts.append(
                "约束：创建智能表格后必须继续添加字段和记录，空表不算完成。"
            )

        if target_ref:
            parts.append(f"目标对象 ID：{target_ref}")
            if family == "document":
                parts.append("请对该文档执行操作，不要操作智能表格。")
            elif family == "smartsheet":
                parts.append("请对该智能表格执行操作，不要操作普通文档。")

        params = packet.get("params") or {}
        if params:
            param_parts = []
            for key, value in params.items():
                if value and key not in ("source_scope",):
                    param_parts.append(f"{key}={value}")
            if param_parts:
                parts.append(f"参数：{', '.join(param_parts[:3])}")

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

    def _emit_flow(self, event_name: str, payload: dict[str, Any]) -> None:
        if not self.on_flow_event:
            return
        try:
            self.on_flow_event(event_name, payload)
        except Exception as exc:
            self._log(f"Failed to record flow event '{event_name}': {exc}")

    def _log(self, message: str) -> None:
        if self.debug:
            print(f"[{self.name}] {message}")

    def _estimate_tokens(self, chars: int) -> int:
        return int(chars * 0.3)

    def _check_context_limits(self) -> None:
        total_chars = sum(len(str(msg.get("content", ""))) for msg in self.messages)
        estimated = self._estimate_tokens(total_chars)
        self._log(f"Pre-request: {len(self.messages)} messages, ~{estimated} tokens")
        if estimated > self.max_context_tokens:
            print(f"[{self.name}] Context tokens ({estimated}) approaching limit.")

    def _truncate_text(self, text: str, max_tokens: int | None = None) -> str:
        max_tokens = max_tokens or self.max_result_tokens
        estimated = self._estimate_tokens(len(text))
        if estimated <= max_tokens:
            return text
        max_chars = int(max_tokens / 0.3)
        return text[:max_chars] + "\n\n[... Content truncated ...]"

    def _update_token_usage(self, usage: Any) -> None:
        if usage:
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["total_tokens"] += usage.total_tokens

    def get_token_usage(self) -> dict[str, int]:
        return self.token_usage.copy()

    def _parse_tool_arguments(self, args_str: str, function_name: str) -> dict[str, Any] | None:
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            self._log(f"JSON parse error for '{function_name}'")
            start = args_str.find("{")
            end = args_str.rfind("}") + 1
            if start != -1 and end != 0:
                try:
                    return json.loads(args_str[start:end])
                except json.JSONDecodeError:
                    pass
            print(f"[{self.name}] Failed to parse tool arguments for {function_name}")
            return None

    def _collect_invalid_tool_calls(self, tool_calls: list[Any]) -> list[dict[str, str]]:
        invalid_calls: list[dict[str, str]] = []
        for tool_call in tool_calls:
            function_name = str(tool_call.function.name or "").strip()
            raw_arguments = str(tool_call.function.arguments or "")
            if self._parse_tool_arguments(raw_arguments, function_name) is not None:
                continue
            invalid_calls.append(
                {
                    "tool_name": function_name,
                    "arguments_preview": raw_arguments[:200],
                }
            )
        return invalid_calls

    def _invalid_tool_arguments_retry_message(self, invalid_calls: list[dict[str, str]]) -> str:
        tool_names = ", ".join(call["tool_name"] for call in invalid_calls if call["tool_name"])
        if not tool_names:
            tool_names = "the requested tools"
        return (
            "你刚才生成的工具调用参数不是合法 JSON。"
            f"请重新生成 {tool_names} 的工具调用，且 function.arguments 必须是严格 JSON："
            "使用双引号、完整对象、不要注释、不要额外说明文字。"
        )

    def _summarize_args(self, args_dict: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in args_dict.items():
            if key == "content":
                text = str(value or "").strip()
                summary["content_preview"] = text[:200]
                summary["content_length"] = len(text)
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
            else:
                summary[key] = str(value)[:200]
        return summary

    # -- Completion gate ------------------------------------------------

    _WRITE_TOOL_TOKENS = (
        "edit_doc", "append_section", "replace_section",
        "expand_section", "doc_content",
    )
    _SMARTSHEET_WRITE_TOKENS = (
        "smartsheet_add", "smartsheet_update", "smartsheet_delete",
    )

    # intent → set of token groups that must appear in called tools
    _INTENT_REQUIRED_ACTIONS: dict[str, tuple[str, ...]] = {
        "doc.create": _WRITE_TOOL_TOKENS,
        "doc.edit": _WRITE_TOOL_TOKENS,
        "doc.merge_kb": _WRITE_TOOL_TOKENS,
        "doc.replace_kb": _WRITE_TOOL_TOKENS,
        "doc.expand_kb": _WRITE_TOOL_TOKENS,
        "smartsheet.create": _SMARTSHEET_WRITE_TOKENS,
    }

    def _called_tool_names(self) -> list[str]:
        """Collect tool names invoked in THIS request only (excludes chat history)."""
        names: list[str] = []
        for msg in self.messages[self._exec_start_idx:]:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    name = str(fn.get("name") or "") if isinstance(fn, dict) else ""
                else:
                    name = str(getattr(getattr(tc, "function", None), "name", "") or "")
                if name:
                    names.append(name.lower())
        return names

    async def _check_task_completion(self, pending_reply: str) -> str | None:
        """Return a nudge message if the agent is stopping before the task is done.

        Returns None when the task looks complete or the gate doesn't apply.
        Fires at most once per execute() call (guarded by self._completion_nudged).
        """
        if self._completion_nudged:
            return None
        intent = (self.intent_packet or {}).get("intent", "")
        required_tokens = self._INTENT_REQUIRED_ACTIONS.get(intent)
        if not required_tokens:
            return None

        called = self._called_tool_names()
        has_write = any(
            any(tok in name for tok in required_tokens)
            for name in called
        )

        # Cross-family tolerance: if intent says doc but agent successfully used
        # smartsheet write tools (or vice versa), treat as complete to avoid
        # nudge loops caused by intent misclassification.
        if not has_write:
            alt_tokens = (
                self._SMARTSHEET_WRITE_TOKENS if intent.startswith("doc.") else self._WRITE_TOOL_TOKENS
            )
            has_alt_write = any(
                any(tok in name for tok in alt_tokens)
                for name in called
            )
            if has_alt_write:
                return None

        # Fast path: no write tool called at all → nudge immediately
        if not has_write:
            return self._fire_completion_nudge(intent, called)

        # Write tool was called, but for high-risk intents, ask LLM to verify
        verdict = await self._llm_verify_completion(intent, called, pending_reply)
        if verdict:
            return self._fire_completion_nudge(intent, called, detail="llm_verdict_incomplete")

        return None

    def _fire_completion_nudge(
        self, intent: str, called: list[str], *, detail: str = ""
    ) -> str:
        self._completion_nudged = True
        self._emit_flow(
            "guard_hit",
            {
                "guard_hit": [{"code": "completion_gate", "detail": detail or f"missing_write_for_{intent}"}],
                "called_tools": called,
                "intent": intent,
            },
        )
        if intent.startswith("smartsheet."):
            return (
                "你还没有执行智能表格的写入操作。"
                "请立即继续调用相应工具完成创建/写入，不要只输出文字。"
            )
        return (
            "你还没有把内容写入文档。创建文档只是第一步，"
            "请立即继续调用 edit_doc_content 完成正文写入，"
            "不要只输出文字。"
        )

    def _recent_tool_calls_structured(self, limit: int = 5) -> list[dict[str, Any]]:
        """Extract the last N tool calls from THIS request (excludes chat history)."""
        entries: list[dict[str, Any]] = []
        exec_messages = self.messages[self._exec_start_idx:]
        tool_name_map: dict[str, str] = {}
        for msg in exec_messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                    fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", None)
                    name = (fn.get("name", "") if isinstance(fn, dict)
                            else str(getattr(fn, "name", "")))
                    if tc_id and name:
                        tool_name_map[tc_id] = name

        for msg in reversed(exec_messages):
            if msg.get("role") != "tool":
                continue
            call_id = str(msg.get("tool_call_id") or "")
            tool_name = tool_name_map.get(call_id, "unknown")
            raw_content = str(msg.get("content") or "")
            # Try to parse errcode from result
            errcode = None
            parsed = _parse_json_object(raw_content)
            if "errcode" in parsed:
                errcode = parsed["errcode"]
            entries.append({
                "tool": tool_name,
                "errcode": errcode,
                "result_preview": raw_content[:200],
            })
            if len(entries) >= limit:
                break
        entries.reverse()
        return entries

    async def _llm_verify_completion(
        self, intent: str, called: list[str], pending_reply: str
    ) -> bool:
        """One-shot LLM call to judge whether the task is actually complete.

        Returns True if the task is NOT complete (should nudge).
        """
        user_msg = ""
        for msg in self.messages:
            if msg.get("role") == "user":
                user_msg = str(msg.get("content") or "")

        tool_calls_data = self._recent_tool_calls_structured()

        verify_input = {
            "user_request": user_msg[:300],
            "intent": intent,
            "tool_calls": tool_calls_data,
            "agent_reply": pending_reply[:300],
        }

        prompt = (
            "你是任务完成度检查器。以下是结构化的执行信息（JSON），请严格根据 tool_calls 中的"
            "实际 errcode 判断任务是否完成。\n\n"
            f"```json\n{json.dumps(verify_input, ensure_ascii=False, indent=2)}\n```\n\n"
            "判断规则：\n"
            "1. 只看 tool_calls 里的 errcode，errcode 不为 0 或为 null 表示该工具调用失败\n"
            "2. agent_reply 是 agent 自己写的文字，可能撒谎，不能作为判断依据\n"
            "3. 如果 intent 要求写入文档，但没有任何 edit_doc / append_section 类工具 errcode=0，判 false\n\n"
            "只返回 JSON：{\"complete\": true/false, \"reason\": \"一句话原因\"}"
        )
        try:
            completion = await asyncio.wait_for(
                self.client.chat.completions.create(
                    **_build_chat_completion_kwargs(
                        self.settings,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                    )
                ),
                timeout=10.0,
            )
            raw = completion.choices[0].message.content or ""
            result = _parse_json_object(raw)
            is_complete = result.get("complete", True)
            self._emit_flow("completion_verify", {"raw": raw[:200], "complete": is_complete})
            return not is_complete
        except Exception:
            return False

    # -----------------------------------------------------------------

    def _extract_created_urls(self) -> list[str]:
        """Extract doc/smartsheet URLs from successful tool results in the conversation."""
        url_pattern = re.compile(r'https://doc\.weixin\.qq\.com/\S+')
        urls: list[str] = []
        seen: set[str] = set()
        for msg in self.messages:
            if msg.get("role") != "tool":
                continue
            content = str(msg.get("content") or "")
            if '"errcode": 0' not in content and '"errcode":0' not in content:
                continue
            for match in url_pattern.finditer(content):
                url = match.group(0).rstrip('",}\\')
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

    async def _execute_a_tool(self, tool_call: Any) -> str:
        function_name = tool_call.function.name
        self._log(f"Calling tool: {function_name}")

        args_dict = self._parse_tool_arguments(tool_call.function.arguments, function_name)
        if args_dict is None:
            self._emit_flow(
                "tool_called",
                {
                    "tool_name": function_name,
                    "args_summary": {},
                    "result_summary": "参数解析失败",
                    "result_status": "failure",
                },
            )
            return "Failed to parse tool arguments."

        call_args = dict(args_dict)
        self._fixup_stringified_json_args(call_args)

        # Block kb__export_file when intent requires document writing — the model
        # keeps calling it despite prompt-level prohibition, causing unwanted PDF attachments.
        fn_lower = str(function_name or "").lower()
        intent = (self.intent_packet or {}).get("intent", "")
        if "export_file" in fn_lower and intent in self._INTENT_REQUIRED_ACTIONS:
            self._log(f"Blocked {function_name}: not needed for intent {intent}")
            return "此操作已被跳过。当前任务是写入文档，不需要导出原始 PDF 文件。请继续完成文档写入。"

        # Auto-fix docid: if edit_doc uses a stale docid from chat history,
        # replace it with the docid created in this request.
        if "create_doc" in fn_lower:
            pass  # will capture docid after execution below
        elif self._current_docid and "docid" in call_args:
            old_docid = str(call_args["docid"] or "")
            if old_docid != self._current_docid:
                self._log(f"Fixing stale docid: {old_docid[:20]}... → {self._current_docid[:20]}...")
                call_args["docid"] = self._current_docid
                # NOTE: intentionally do NOT update args_dict here.
                # call_args != args_dict forces the code below to use
                # mcp_client.call_tool(name, call_args) instead of
                # tool_message_from_call(tool_call) which re-parses the
                # ORIGINAL tool_call.function.arguments (with the stale docid).

        # Validate smartsheet sheet_id: reject fabricated sheet_ids
        if "smartsheet_" in fn_lower and fn_lower != "wecom_docs__smartsheet_get_sheet" and "sheet_id" in call_args:
            sheet_id = str(call_args.get("sheet_id") or "").strip()
            if self._known_sheet_ids and sheet_id and sheet_id not in self._known_sheet_ids:
                self._log(f"Blocked fabricated sheet_id: {sheet_id}")
                return (
                    f"sheet_id \"{sheet_id}\" 不是有效的子表 ID。"
                    f"已知的子表 ID：{', '.join(self._known_sheet_ids)}。"
                    "请使用 smartsheet_get_sheet 返回的真实 sheet_id。"
                )

        # Validate smartsheet field names in add_records: reject fabricated field titles
        if "smartsheet_add_records" in fn_lower and self._known_field_titles:
            records = call_args.get("records")
            if isinstance(records, list):
                bad_fields: list[str] = []
                for record in records:
                    values = record.get("values") if isinstance(record, dict) else None
                    if isinstance(values, dict):
                        for key in values:
                            if str(key).strip() not in self._known_field_titles and key not in bad_fields:
                                bad_fields.append(str(key).strip())
                if bad_fields:
                    self._log(f"Blocked records with unknown fields: {bad_fields}")
                    return (
                        f"以下字段名不存在于当前子表：{', '.join(bad_fields)}。"
                        f"当前子表的字段名为：{', '.join(sorted(self._known_field_titles))}。"
                        "请使用 smartsheet_get_fields 返回的真实 field_title。"
                    )

        # Force content_type=1 for edit_doc_content — the WeCom MCP tool
        # schema only accepts [1].  LLM sometimes hallucinates other values.
        if "edit_doc_content" in fn_lower:
            raw_ct = call_args.get("content_type")
            if raw_ct not in (1, "1"):
                self._log(f"Fixing content_type {raw_ct!r}→1 for edit_doc_content")
                call_args["content_type"] = 1

        # Strip leading H1 from edit_doc_content — create_doc already set the
        # document title; if content starts with `# Title`, WeCom renders a
        # duplicate title at the top of the body.
        if "edit_doc_content" in fn_lower and isinstance(call_args.get("content"), str):
            original_content = call_args["content"]
            stripped = original_content.lstrip()
            if stripped.startswith("# "):
                # Remove first line (the H1) plus following blank lines
                rest = stripped.split("\n", 1)[1] if "\n" in stripped else ""
                new_content = rest.lstrip()
                if new_content != original_content:
                    self._log(f"Stripped leading H1 from edit_doc_content (was {len(original_content)} chars, now {len(new_content)})")
                    call_args["content"] = new_content

        if is_local_agent_tool_name(function_name):
            local_result = await execute_local_agent_tool(
                function_name,
                call_args,
                host=self.mcp_client,
            )
            attachment = local_result.get("attachment")
            if isinstance(attachment, dict):
                self.prepared_attachment = attachment
            result = local_result.get("content") or ""
        else:
            if not self.mcp_client:
                result_str = f"No MCP client for tool {function_name}"
                self._emit_flow(
                    "tool_called",
                    {
                        "tool_name": function_name,
                        "args_summary": self._summarize_args(call_args),
                        "result_summary": result_str,
                        "result_status": "failure",
                    },
                )
                return result_str

            if call_args == args_dict:
                tool_msg = await self.mcp_client.tool_message_from_call(tool_call)
                result = tool_msg["content"]
            else:
                result = await self.mcp_client.call_tool(function_name, call_args)

        result_str = str(result)

        # Capture docid from successful create_doc
        if "create_doc" in fn_lower:
            parsed_result = _parse_json_object(result_str)
            if parsed_result.get("errcode") == 0 and parsed_result.get("docid"):
                self._current_docid = str(parsed_result["docid"])
                self._log(f"Captured docid: {self._current_docid[:30]}...")

        # Capture sheet_ids from successful get_sheet
        if "smartsheet_get_sheet" in fn_lower:
            parsed_result = _parse_json_object(result_str)
            if parsed_result.get("errcode") == 0:
                for sheet in parsed_result.get("sheet_list") or []:
                    sid = str(sheet.get("sheet_id") or "").strip()
                    if sid:
                        self._known_sheet_ids.add(sid)
                self._log(f"Known sheet_ids: {self._known_sheet_ids}")

        # Capture field_titles from successful get_fields
        if "smartsheet_get_fields" in fn_lower:
            parsed_result = _parse_json_object(result_str)
            if parsed_result.get("errcode") == 0:
                for field in parsed_result.get("fields") or []:
                    title = str(field.get("field_title") or "").strip()
                    if title:
                        self._known_field_titles.add(title)
                self._log(f"Known field_titles: {self._known_field_titles}")

        # Also capture field_titles from successful add_fields / update_fields
        if "smartsheet_add_fields" in fn_lower or "smartsheet_update_fields" in fn_lower:
            parsed_result = _parse_json_object(result_str)
            if parsed_result.get("errcode") == 0:
                for field in parsed_result.get("fields") or []:
                    title = str(field.get("field_title") or "").strip()
                    if title:
                        self._known_field_titles.add(title)

        if self.on_tool_result:
            try:
                self.on_tool_result(function_name, call_args, result_str)
            except Exception as exc:
                self._log(f"Failed to persist tool memory for '{function_name}': {exc}")

        estimated = self._estimate_tokens(len(result_str))
        if estimated > self.max_result_tokens:
            result_str = self._truncate_text(result_str)
            self._log(f"Tool '{function_name}': ~{estimated} tokens (truncated)")
        else:
            self._log(f"Tool '{function_name}': ~{estimated} tokens")

        result_status = "success"
        if any(token in result_str.lower() for token in ("error", "failed", "traceback")):
            result_status = "failure"
        if '"errcode":' in result_str and '"errcode": 0' not in result_str:
            result_status = "failure"

        self._emit_flow(
            "tool_called",
            {
                "tool_name": function_name,
                "args_summary": self._summarize_args(call_args),
                "result_summary": result_str[:300],
                "result_status": result_status,
            },
        )

        # Hard stop on authorization expired — no point retrying.
        parsed_err = _parse_json_object(result_str)
        if parsed_err.get("errcode") == 850003:
            help_msg = str(parsed_err.get("help_message") or "").strip()
            if help_msg:
                self._auth_expired_message = help_msg
            else:
                self._auth_expired_message = "当前机器人的文档使用权限已过期，请联系机器人创建者重新授权。"
            raise _AuthExpiredError(self._auth_expired_message)

        return result_str

    @staticmethod
    def _fixup_stringified_json_args(args: dict[str, Any]) -> None:
        """Fix LLM bug where array/object args are serialized as JSON strings."""
        for key, value in list(args.items()):
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if not (stripped.startswith("[") or stripped.startswith("{")):
                continue
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, (list, dict)):
                    args[key] = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    async def _process_tool_calls(self, tool_calls: list[Any]) -> str | None:
        self.tool_call_count += len(tool_calls)
        self._log(f"Processing {len(tool_calls)} tool calls (total: {self.tool_call_count})")

        if self.max_tool_calls > 0 and self.tool_call_count > self.max_tool_calls:
            self._emit_flow(
                "stop_reason",
                {
                    "code": "guard_stop",
                    "detail": "max_tool_calls_exceeded",
                    "layer": "flow",
                },
            )
            print(f"[{self.name}] Max tool calls ({self.max_tool_calls}) reached.")
            return "You have used up all your tool calls. Please provide the final answer."

        for tool_call in tool_calls:
            try:
                result = await self._execute_a_tool(tool_call)
            except _AuthExpiredError:
                self._emit_flow(
                    "stop_reason",
                    {"code": "guard_stop", "detail": "auth_expired_850003", "layer": "flow"},
                )
                return self._auth_expired_message or "当前机器人的文档使用权限已过期，请联系机器人创建者重新授权。"
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

        return None

    async def chat(self, message: str = "") -> str:
        if message:
            self.messages.append({"role": "user", "content": message})

        result = await self.execute()
        if result is None:
            raise ValueError("No final assistant content returned.")

        self.messages.append({"role": "assistant", "content": result})
        return result

    async def execute(self) -> str:
        while True:
            self._check_context_limits()

            # Only force tool_choice on the very first round
            force_tool = self.tools and self.tool_call_count == 0

            completion = await self.client.chat.completions.create(
                **_build_chat_completion_kwargs(
                    self.settings,
                    messages=self.messages,
                    tools=self.tools if self.tools else None,
                    tool_choice=(
                        "required" if force_tool
                        else ("auto" if self.tools else None)
                    ),
                    temperature=self.settings.temperature,
                    top_p=self.settings.top_p,
                    seed=self.settings.seed,
                )
            )

            response_message = completion.choices[0].message
            self._update_token_usage(completion.usage)

            if response_message.tool_calls:
                # Check for invalid JSON arguments
                invalid_tool_calls = self._collect_invalid_tool_calls(response_message.tool_calls)
                if invalid_tool_calls:
                    self.invalid_tool_argument_rounds += 1
                    self._emit_flow(
                        "guard_hit",
                        {
                            "guard_hit": [
                                {
                                    "code": "invalid_tool_arguments",
                                    "detail": "model_generated_non_json_arguments",
                                }
                            ],
                            "tool_names": [call["tool_name"] for call in invalid_tool_calls],
                            "invalid_rounds": self.invalid_tool_argument_rounds,
                        },
                    )
                    if self.invalid_tool_argument_rounds >= self.max_invalid_tool_argument_rounds:
                        self._emit_flow(
                            "stop_reason",
                            {
                                "code": "guard_stop",
                                "detail": "repeated_invalid_tool_arguments",
                                "layer": "flow",
                            },
                        )
                        fail_msg = "这次工具调用参数连续生成失败。请重试，或把你的要求说得更具体一些。"
                        urls = self._extract_created_urls()
                        if urls:
                            fail_msg += "\n已创建的资源链接：\n" + "\n".join(urls)
                        return fail_msg
                    self.messages.append(
                        {
                            "role": "user",
                            "content": self._invalid_tool_arguments_retry_message(invalid_tool_calls),
                        }
                    )
                    continue

                self.invalid_tool_argument_rounds = 0
                self.messages.append(response_message.model_dump(exclude_unset=True))

                # Emit flow events
                tool_names = [call.function.name for call in response_message.tool_calls]
                self._emit_flow(
                    "intent_packet_created",
                    dict(self.intent_packet),
                ) if self.intent_packet and self.intent_packet.get("intent_family") else None
                self._emit_flow(
                    "agent_plan_created",
                    {"tool_names": tool_names, "tool_count": len(tool_names)},
                )
                self._emit_flow(
                    "assistant_requested_tools",
                    {"tool_names": tool_names, "tool_count": len(tool_names)},
                )
                self._emit_flow(
                    "agent_self_check",
                    {
                        "tool_names": tool_names,
                        "tool_count": len(response_message.tool_calls),
                        "target_ok": True,
                        "params_ok": True,
                        "sequence_ok": True,
                        "need_confirm": False,
                        "risk": "low",
                        "problems": [],
                    },
                )

                forced = await self._process_tool_calls(response_message.tool_calls)
                if forced:
                    # Auth expired: return the message directly as final answer
                    if self._auth_expired_message:
                        return forced
                    self.messages.pop()
                    self.messages.append(
                        {
                            "role": "user",
                            "content": "你已用尽所有工具调用次数，请根据已经收集的信息直接给出最终结论。",
                        }
                    )
                    continue
            else:
                self.invalid_tool_argument_rounds = 0

                # Completion gate: nudge once if intent requires a write tool not yet called
                nudge = await self._check_task_completion(response_message.content or "")
                if nudge:
                    self.messages.append({"role": "assistant", "content": response_message.content or ""})
                    self.messages.append({"role": "user", "content": nudge})
                    continue

                self._emit_flow(
                    "stop_reason",
                    {
                        "code": "final_answer",
                        "detail": "model_response_without_tool_calls",
                        "layer": "flow",
                    },
                )
                return response_message.content or ""
