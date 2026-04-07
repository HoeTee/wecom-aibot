from __future__ import annotations

import json
import os
import traceback
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .config import MCPServerConfig
from .mcp_logger import logger


class MCPServerConnection:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self._tools: List[Dict[str, Any]] = []
        self.logger = logger

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return self._tools

    async def connect(self) -> None:
        try:
            read_stream, write_stream = await self._open_transport()
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self.session.initialize()

            self._tools = await self.list_tools_openai()
            self.logger.info(
                "Connected to MCP server '%s' over %s. Tools: %s",
                self.config.name,
                self.config.transport,
                [tool["function"]["name"] for tool in self._tools],
            )
        except Exception as exc:
            self.logger.error("Error connecting to MCP server '%s': %s", self.config.name, exc)
            traceback.print_exc()
            raise

    async def _open_transport(self):
        cfg = self.config

        if cfg.transport == "streamable_http":
            http_client = None
            if cfg.headers or cfg.timeout_seconds is not None:
                http_client = await self.exit_stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        timeout=cfg.timeout_seconds,
                    )
                )

            read_stream, write_stream, _ = await self.exit_stack.enter_async_context(
                streamable_http_client(
                    cfg.url,
                    http_client=http_client,
                )
            )
            return read_stream, write_stream

        if cfg.transport == "sse":
            read_stream, write_stream = await self.exit_stack.enter_async_context(
                sse_client(
                    cfg.url,
                    headers=cfg.headers or None,
                    timeout=cfg.timeout_seconds or 5,
                )
            )
            return read_stream, write_stream

        env = None
        if cfg.env:
            env = os.environ.copy()
            env.update(cfg.env)

        server_params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=env,
            cwd=cfg.cwd,
        )
        return await self.exit_stack.enter_async_context(stdio_client(server_params))

    async def list_tools_openai(self) -> List[Dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Client not connected")

        response = await self.session.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
            for tool in response.tools
        ]

    async def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        if not self.session:
            raise RuntimeError("Client not connected")

        result = await self.session.call_tool(name, args)
        if hasattr(result, "content") and isinstance(result.content, list):
            texts = []
            for item in result.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
                elif isinstance(item, dict) and "text" in item:
                    texts.append(item["text"])
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        return str(result)

    async def tool_message_from_call(self, tool_call: Any) -> dict[str, Any]:
        args = json.loads(tool_call.function.arguments or "{}")
        content = await self.call_tool(tool_call.function.name, args)
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": content,
        }

    async def cleanup(self) -> None:
        try:
            await self.exit_stack.aclose()
            self.logger.info("Disconnected from MCP server '%s'", self.config.name)
        except Exception as exc:
            self.logger.error("Error during cleanup of MCP server '%s': %s", self.config.name, exc)
            traceback.print_exc()
