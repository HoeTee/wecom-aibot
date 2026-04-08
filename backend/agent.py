"""
Base Agent class: handles LLM communication, tool calling, context management,
token tracking, and conversation logging.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol

from openai import AsyncOpenAI
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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

    max_tool_calls: int = Field(10, alias="MAX_TOOL_CALLS")
    max_context_tokens: int = Field(100000, alias="MAX_CONTEXT_TOKENS")
    max_result_tokens: int = Field(5000, alias="MAX_RESULT_TOKENS")


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
        self.on_tool_result = on_tool_result
        self.on_flow_event = on_flow_event

        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.tool_call_count = 0

        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        if memory_context:
            self.messages.append({"role": "system", "content": memory_context})

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

    def _needs_rag_query_rewrite(self, function_name: str, args_dict: dict[str, Any]) -> bool:
        return (
            function_name.endswith("llamaindex_rag_query")
            and isinstance(args_dict.get("query"), str)
            and bool(str(args_dict.get("query", "")).strip())
        )

    def _rewrite_rag_query(self, query: str) -> str:
        rewritten = str(query or "").strip()
        if not rewritten:
            return rewritten

        replacements = {
            "重新生成一份企业微信文档": "生成一份基于来源材料的文档内容",
            "生成一份企业微信文档": "生成一份基于来源材料的文档内容",
            "给刚才那份文档": "",
            "给刚才那个文档": "",
            "不要新建文档": "",
            "回复要简洁，并明确告诉我是否已经创建文档。": "",
            "回复要简洁，并明确告诉我是否已经创建文档": "",
            "回复要简洁。": "",
            "回复要简洁": "",
        }
        for old, new in replacements.items():
            rewritten = rewritten.replace(old, new)

        filtered_lines: list[str] = []
        for raw_line in rewritten.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "明确告诉我是否已经创建文档" in line:
                continue
            if line.startswith("回复要"):
                continue
            filtered_lines.append(line)

        rewritten = "\n".join(filtered_lines).strip()
        return rewritten or str(query).strip()

    def _latest_user_message(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") == "user":
                return str(message.get("content", "")).strip()
        return ""

    def _is_fresh_document_request(self) -> bool:
        latest_user_message = self._latest_user_message()
        fresh_tokens = ("重新生成", "重新写一份", "重新出一份", "新生成一份", "新建一份")
        return "文档" in latest_user_message and any(token in latest_user_message for token in fresh_tokens)

    def _user_requested_table(self) -> bool:
        latest_user_message = self._latest_user_message()
        return any(token in latest_user_message for token in ("表格", "对比表", "comparison table"))

    def _user_requested_structured_summary(self) -> bool:
        latest_user_message = self._latest_user_message()
        required_tokens = ("背景", "每篇论文摘要", "横向对比", "结论与建议")
        return all(token in latest_user_message for token in required_tokens)

    def _validate_doc_tool_arguments(self, function_name: str, args_dict: dict[str, Any]) -> str | None:
        name = function_name.lower()
        if "edit_doc" not in name and "doc_content" not in name:
            return None

        content = str(args_dict.get("content", "") or "").strip()
        if not content:
            return None

        if "..." in content:
            return "文档内容校验失败：不允许写入占位符 `...`。"

        if self._user_requested_structured_summary():
            required_sections = ("背景", "每篇论文摘要", "横向对比", "结论与建议")
            missing_sections = [section for section in required_sections if section not in content]
            if missing_sections:
                return "文档内容校验失败：缺少必需章节：" + "、".join(missing_sections)

        if not self._user_requested_table():
            forbidden_table_markers = ("## 5.", "### 5.", "技术对比表")
            if any(marker in content for marker in forbidden_table_markers):
                return "文档内容校验失败：当前轮次不允许提前生成对比表。"

        return None

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
        persisted_args = dict(args_dict)

        if self._needs_rag_query_rewrite(function_name, args_dict):
            original_query = str(args_dict["query"]).strip()
            rewritten_query = self._rewrite_rag_query(original_query)
            if rewritten_query and rewritten_query != original_query:
                call_args["query"] = rewritten_query
                persisted_args["rewritten_query"] = rewritten_query
                self._emit_flow(
                    "rag_query_rewritten",
                    {
                        "original_query": original_query,
                        "rewritten_query": rewritten_query,
                    },
                )
                self._log(f"Rewrote RAG query for '{function_name}'")

        validation_error = self._validate_doc_tool_arguments(function_name, call_args)
        if validation_error:
            self._log(validation_error)
            self._emit_flow(
                "guard_hit",
                {
                    "guard_hit": [{"code": "doc_content_validation", "detail": "write_blocked"}],
                    "tool_name": function_name,
                    "reason": validation_error,
                },
            )
            self._emit_flow(
                "tool_called",
                {
                    "tool_name": function_name,
                    "args_summary": self._summarize_args(call_args),
                    "result_summary": validation_error,
                    "result_status": "failure",
                },
            )
            return validation_error

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
        if self.on_tool_result:
            try:
                self.on_tool_result(function_name, persisted_args, result_str)
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
        return result_str

    async def _process_tool_calls(self, tool_calls: list[Any]) -> str | None:
        self.tool_call_count += len(tool_calls)
        self._log(f"Processing {len(tool_calls)} tool calls (total: {self.tool_call_count})")

        if self.tool_call_count > self.max_tool_calls:
            self._emit_flow(
                "guard_hit",
                {
                    "guard_hit": [{"code": "tool_limit", "detail": "max_tool_calls_exceeded"}],
                    "tool_call_count": self.tool_call_count,
                    "max_tool_calls": self.max_tool_calls,
                },
            )
            self._emit_flow(
                "stop_reason",
                {
                    "code": "guard_stop",
                    "detail": "max_tool_calls_exceeded",
                    "layer": "orchestration",
                },
            )
            print(f"[{self.name}] Max tool calls ({self.max_tool_calls}) reached.")
            return "You have used up all your tool calls. Please provide the final answer."

        for tool_call in tool_calls:
            result = await self._execute_a_tool(tool_call)
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

            completion = await self.client.chat.completions.create(
                model=self.settings.model,
                temperature=self.settings.temperature,
                top_p=self.settings.top_p,
                seed=self.settings.seed,
                messages=self.messages,
                tools=self.tools if self.tools else None,
                tool_choice="auto" if self.tools else None,
            )

            response_message = completion.choices[0].message
            self._update_token_usage(completion.usage)

            if response_message.tool_calls:
                self.messages.append(response_message.model_dump(exclude_unset=True))
                self._emit_flow(
                    "assistant_requested_tools",
                    {
                        "tool_names": [call.function.name for call in response_message.tool_calls],
                        "tool_count": len(response_message.tool_calls),
                    },
                )

                forced = await self._process_tool_calls(response_message.tool_calls)
                if forced:
                    self.messages.pop()
                    self.messages.append(
                        {
                            "role": "user",
                            "content": "你已用尽所有工具调用次数，请根据已经收集的信息直接给出最终结论。",
                        }
                    )
                    continue
            else:
                self._emit_flow(
                    "stop_reason",
                    {
                        "code": "final_answer",
                        "detail": "model_response_without_tool_calls",
                        "layer": "orchestration",
                    },
                )
                return response_message.content or ""
