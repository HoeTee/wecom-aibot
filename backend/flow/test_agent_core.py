from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from backend.flow.agent_core import Agent, Settings
from backend.runtime.local_tools import AGENT_NO_TOOL_NEEDED_TOOL


class _FakeToolFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _FakeToolFunction(name, arguments)


class _FakeMessage:
    def __init__(self, *, content: str = "", tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_unset: bool = True) -> dict[str, object]:
        del exclude_unset
        payload: dict[str, object] = {"role": "assistant"}
        if self.content:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return payload


class _FakeCompletion:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [SimpleNamespace(message=message)]
        self.usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)


class _FakeCompletions:
    def __init__(self, responses: list[_FakeCompletion]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No fake completion response left.")
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses: list[_FakeCompletion]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


class AgentInvalidToolArgumentsTests(unittest.TestCase):
    def _build_settings(self) -> Settings:
        return Settings.model_construct(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="test-model",
            temperature=0.0,
            top_p=0.01,
            seed=42,
            max_tool_calls=0,
            max_context_tokens=100000,
            max_result_tokens=5000,
            routing_timeout_seconds=15.0,
            agent_timeout_seconds=180.0,
            max_invalid_tool_argument_rounds=2,
        )

    def test_invalid_tool_arguments_are_retried_without_replaying_bad_tool_call(self) -> None:
        agent = Agent(
            system_prompt="test",
            tools=[AGENT_NO_TOOL_NEEDED_TOOL],
            settings=self._build_settings(),
        )
        agent.client = _FakeClient(
            [
                _FakeCompletion(
                    _FakeMessage(
                        tool_calls=[_FakeToolCall("call-1", "agent__no_tool_needed", "{reason:'bad'}")]
                    )
                ),
                _FakeCompletion(
                    _FakeMessage(
                        tool_calls=[
                            _FakeToolCall(
                                "call-2",
                                "agent__no_tool_needed",
                                '{"reason":"No external tool state needed."}',
                            )
                        ]
                    )
                ),
                _FakeCompletion(_FakeMessage(content="final answer")),
            ]
        )

        result = asyncio.run(agent.chat("test input"))

        self.assertEqual(result, "final answer")
        self.assertFalse(
            any(
                message.get("tool_calls")
                and "call-1" in str(message.get("tool_calls"))
                for message in agent.messages
                if isinstance(message, dict)
            )
        )
        self.assertTrue(
            any(
                message.get("role") == "user" and "不是合法 JSON" in str(message.get("content", ""))
                for message in agent.messages
                if isinstance(message, dict)
            )
        )

    def test_repeated_invalid_tool_arguments_stop_after_second_round(self) -> None:
        agent = Agent(
            system_prompt="test",
            tools=[AGENT_NO_TOOL_NEEDED_TOOL],
            settings=self._build_settings(),
        )
        agent.client = _FakeClient(
            [
                _FakeCompletion(
                    _FakeMessage(
                        tool_calls=[_FakeToolCall("call-1", "agent__no_tool_needed", "{reason:'bad'}")]
                    )
                ),
                _FakeCompletion(
                    _FakeMessage(
                        tool_calls=[_FakeToolCall("call-2", "agent__no_tool_needed", "{reason:'still bad'}")]
                    )
                ),
            ]
        )

        result = asyncio.run(agent.chat("test input"))

        self.assertIn("工具调用参数连续生成失败", result)


if __name__ == "__main__":
    unittest.main()
