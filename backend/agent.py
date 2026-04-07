"""
Base Agent class — handles LLM communication, tool calling, context
management, token tracking, and conversation logging.
"""
from typing import Any, Callable, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field
from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIConnectionError, InternalServerError
import asyncio
import json
import os

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


class Agent:

    def __init__(
        self,
        system_prompt: str = "",
        name: str = "Agent",
        mcp_client: ToolRuntime | None = None,
        tools=None,
        settings: Settings = None,
        debug: bool = False,
        memory_context: str = "",
        on_tool_result: Callable[[str, dict[str, Any], str], None] | None = None,
    ) -> None:
        """
        Initialize the Agent.

        Args:
            system_prompt: System prompt for the agent.
            name: Name of the agent.
            mcp_client: MCP client for tool calling.
            tools: List of tools for the agent.
            settings: Settings for the agent.
            debug: Whether to enable debug mode.
            MAX_TOOL_CALLS: Maximum number of tool calls.
            MAX_CONTEXT_TOKENS: Maximum number of context tokens.
            MAX_RESULT_TOKENS: Maximum number of result tokens.
        """
        self.settings = settings or Settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
        )
        self.name = name
        self.mcp_client = mcp_client
        self.tools = tools or (mcp_client.tools if mcp_client else [])
        self.messages: list = []
        self.debug = debug
        self.max_tool_calls = self.settings.max_tool_calls
        self.max_context_tokens = self.settings.max_context_tokens
        self.max_result_tokens = self.settings.max_result_tokens
        self.on_tool_result = on_tool_result

        # Token tracking
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.tool_call_count = 0

        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        if memory_context:
            self.messages.append({"role": "system", "content": memory_context})



    # ==================== utils (Logging & Esti Tokens) ====================

    def _log(self, message: str):
        if self.debug:
            print(f"[{self.name}] {message}")
    
    def _estimate_tokens(self, chars: int) -> int:
        return int(chars * 0.3)

    # ==================== Context ====================

    def _check_context_limits(self):
        total_chars = sum(len(str(msg.get("content", ""))) for msg in self.messages)
        estimated = self._estimate_tokens(total_chars)
        self._log(f"Pre-request: {len(self.messages)} messages, ~{estimated} tokens")
        if estimated > self.max_context_tokens:
            print(f"[{self.name}] ⚠️ Context tokens ({estimated}) approaching limit!")

    def _truncate_text(self, text: str, max_tokens: int = None) -> str:
        if max_tokens is None:
            max_tokens = self.max_result_tokens
        estimated = self._estimate_tokens(len(text))
        if estimated <= max_tokens:
            return text
        max_chars = int(max_tokens / 0.3)
        return text[:max_chars] + "\n\n[... Content truncated ...]"

    def _latest_user_message(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") == "user":
                return str(message.get("content", "")).strip()
        return ""

    # ==================== Token Tracking ====================

    def _update_token_usage(self, usage: dict):
        if usage:
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["total_tokens"] += usage.total_tokens

    def get_token_usage(self) -> dict:
        return self.token_usage.copy()

    # ==================== Tool Calls ====================

    ## Parse tool arguments from tool call.
    def _parse_tool_arguments(self, args_str: str, function_name: str) -> dict | None:
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            self._log(f"⚠️ JSON parse error for '{function_name}'")
            start = args_str.find("{")
            end = args_str.rfind("}") + 1
            if start != -1 and end != 0:
                try:
                    return json.loads(args_str[start:end])
                except json.JSONDecodeError:
                    pass
            print(f"[{self.name}] ✗ Failed to parse tool arguments for {function_name}")
            return None

    def _needs_rag_query_rewrite(self, function_name: str, args_dict: dict[str, Any]) -> bool:
        return (
            function_name.endswith("llamaindex_rag_query")
            and isinstance(args_dict.get("query"), str)
            and bool(str(args_dict.get("query", "")).strip())
        )

    async def _rewrite_rag_query(self, query: str) -> str:
        latest_user_message = self._latest_user_message()
        rewrite_prompt = (
            "你是一个 RAG query rewrite helper。\n"
            "任务：把用户请求改写成适合 PDF 知识库检索或总结的 query。\n"
            "要求：\n"
            "1. 保留用户明确提出的内容目标、结构要求、比较要求、表格要求、补充或改写要求。\n"
            "2. 删除纯操作性指令，例如是否创建文档、是否回复简洁、是否告知创建成功。\n"
            "3. 如果用户是在补充已有文档，保留“补什么内容”的要求，但不要写成文档操作指令。\n"
            "4. 不要擅自增加领域约束，不要缩小或放大用户任务范围。\n"
            "5. 输出纯文本 query，不要解释，不要加 markdown。\n\n"
            f"最近一条用户消息：\n{latest_user_message}\n\n"
            f"当前待改写 query：\n{query}"
        )

        completion = await self.client.chat.completions.create(
            model=self.settings.model,
            temperature=0.0,
            top_p=0.01,
            seed=self.settings.seed,
            messages=[
                {"role": "system", "content": "You rewrite user requests into source-grounded RAG queries."},
                {"role": "user", "content": rewrite_prompt},
            ],
        )
        self._update_token_usage(completion.usage)
        rewritten = (completion.choices[0].message.content or "").strip()
        return rewritten or query
    
    ## Execute a tool call and return text message.
    async def _execute_a_tool(self, tool_call: dict) -> str:
        function_name = tool_call.function.name
        self._log(f"→ Calling tool: {function_name}")

        args_dict = self._parse_tool_arguments(tool_call.function.arguments, function_name) # Intercepts tool executions and returns text message.
        if args_dict is None:
            return "Failed to parse tool arguments."

        call_args = dict(args_dict)
        persisted_args = dict(args_dict)
        if self._needs_rag_query_rewrite(function_name, args_dict):
            try:
                rewritten_query = await self._rewrite_rag_query(str(args_dict["query"]))
            except Exception as exc:
                self._log(f"Failed to rewrite RAG query for '{function_name}': {exc}")
            else:
                if rewritten_query.strip() and rewritten_query.strip() != str(args_dict["query"]).strip():
                    call_args["query"] = rewritten_query
                    persisted_args["rewritten_query"] = rewritten_query
                    self._log(f"Rewrote RAG query for '{function_name}'")

        if self.mcp_client:
            if call_args == args_dict:
                tool_msg = await self.mcp_client.tool_message_from_call(tool_call)
                result = tool_msg["content"]
            else:
                result = await self.mcp_client.call_tool(function_name, call_args)
        else:
            return f"No MCP client for tool {function_name}"

        result_str = str(result)
        if self.on_tool_result:
            try:
                self.on_tool_result(function_name, persisted_args, result_str)
            except Exception as exc:
                self._log(f"Failed to persist tool memory for '{function_name}': {exc}")
        estimated = self._estimate_tokens(len(result_str))
        if estimated > self.max_result_tokens:
            result_str = self._truncate_text(result_str)
            self._log(f"← Tool '{function_name}': ~{estimated} tokens (truncated)")
        else:
            self._log(f"← Tool '{function_name}': ~{estimated} tokens")
        return result_str

    ## Append tool calls onto history
    async def _process_tool_calls(self, tool_calls):
        self.tool_call_count += len(tool_calls)
        self._log(f"Processing {len(tool_calls)} tool calls (total: {self.tool_call_count})")

        if self.tool_call_count > self.max_tool_calls: 
            print(f"[{self.name}] ⚠️ Max tool calls ({self.max_tool_calls}) reached. Aborting task and marking review invalid.")
            return "You have used up all your tool calls. Please provide the final answer."

        for tool_call in tool_calls:
            result = await self._execute_a_tool(tool_call)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

        return None

    # ==================== Main Loop ====================

    async def chat(self, message="") -> str:
        if message:
            self.messages.append({"role": "user", "content": message})

        result = await self.execute()
        if result is not None:
            self.messages.append({"role": "assistant", "content": result})

        else:
            raise ValueError("No final assistant content returned.")
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
                tool_choice="auto" if self.tools else None
            )

            response_message = completion.choices[0].message
            self._update_token_usage(completion.usage)

            if response_message.tool_calls:
                self.messages.append(response_message.model_dump(exclude_unset=True)) # Append tool calls onto history

                forced = await self._process_tool_calls(response_message.tool_calls)
                if forced:
                    self.messages.pop()  # Remove unresolved tool_calls message preventing API errors
                    self.messages.append(
                        {"role": "user", "content": "你已用尽所有工具调用次数，请根据已收集的信息直接给出最终结论。"}
                    )

                    continue
            else:
                return response_message.content

