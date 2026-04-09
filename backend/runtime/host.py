from __future__ import annotations

import json
from typing import Any

from .config import MCPServerConfig
from .connection import MCPServerConnection
from .mcp_logger import logger
from .types import MCPToolRoute


class MCPHost:
    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self.configs = configs
        self.connections: dict[str, MCPServerConnection] = {}
        self._routes: dict[str, MCPToolRoute] = {}
        self._tools: list[dict[str, Any]] = []
        self.logger = logger

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self._tools

    def get_tool_routes(self) -> dict[str, MCPToolRoute]:
        return dict(self._routes)

    async def connect_all(self) -> None:
        self.connections.clear()
        self._routes.clear()
        self._tools.clear()

        for config in self.configs:
            connection = MCPServerConnection(config)
            try:
                await connection.connect()
            except Exception:
                if config.required:
                    raise
                self.logger.warning(
                    "Skipping optional MCP server '%s' after connection failure",
                    config.name,
                )
                await connection.cleanup()
                continue

            self.connections[config.name] = connection
            self._register_tools(connection)

    def _register_tools(self, connection: MCPServerConnection) -> None:
        prefix = connection.config.tool_prefix
        server_name = connection.config.name

        for tool in connection.tools:
            remote_name = tool["function"]["name"]
            exposed_name = f"{prefix}__{remote_name}"
            if exposed_name in self._routes:
                raise ValueError(f"Duplicate exposed MCP tool name: {exposed_name}")

            self._routes[exposed_name] = MCPToolRoute(
                exposed_tool_name=exposed_name,
                server_name=server_name,
                remote_tool_name=remote_name,
            )
            self._tools.append(self._expose_tool(server_name, exposed_name, tool))

        self.logger.info(
            "Registered MCP server '%s' with exposed tools: %s",
            server_name,
            [
                tool["function"]["name"]
                for tool in self._tools
                if tool["function"]["name"].startswith(f"{prefix}__")
            ],
        )

    def _expose_tool(
        self,
        server_name: str,
        exposed_name: str,
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        description = tool["function"].get("description") or f"MCP tool from {server_name}"
        description = self._augment_tool_description(server_name, exposed_name, description)
        return {
            "type": tool["type"],
            "function": {
                "name": exposed_name,
                "description": f"[server:{server_name}] {description}",
                "parameters": tool["function"].get("parameters", {}),
            },
        }

    def _augment_tool_description(
        self,
        server_name: str,
        exposed_name: str,
        description: str,
    ) -> str:
        name = exposed_name.lower()
        server = server_name.lower()

        if "create_doc" in name:
            return (
                f"{description} "
                "Use this only when the user explicitly wants a new document or no existing target document is available. "
                "If the user says to regenerate, rewrite, or create a fresh document, treat that as a new-document request. "
                "When creating a summary document, write the requested core sections first and do not add comparison tables unless the user explicitly asks for a table."
            )

        if any(token in name for token in ("edit_doc", "update_doc", "doc_content", "smartsheet")):
            return (
                f"{description} "
                "For follow-up edits, reuse the existing doc_id/doc_url/doc_name from session memory when available. "
                "Do not use the currently bound document when the user explicitly asks to regenerate or create a fresh document. "
                "Do not create a new document unless the user explicitly asks for one. "
                "If the user asks to add a table or append content, update the existing document instead of rewriting unrelated sections."
            )

        if "doc" in name or "wecom" in server:
            return (
                f"{description} "
                "Prefer continuity: if the user refers to the last document, operate on the bound document when available."
            )

        return description

    async def call_tool(self, exposed_name: str, args: dict[str, Any]) -> str:
        route = self._routes.get(exposed_name)
        if route is None:
            raise KeyError(f"Unknown MCP tool: {exposed_name}")

        connection = self.connections[route.server_name]
        self.logger.info(
            "Routing MCP tool '%s' to server '%s' as '%s'",
            exposed_name,
            route.server_name,
            route.remote_tool_name,
        )
        return await connection.call_tool(route.remote_tool_name, args)

    async def tool_message_from_call(self, tool_call: Any) -> dict[str, Any]:
        args = json.loads(tool_call.function.arguments or "{}")
        content = await self.call_tool(tool_call.function.name, args)
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": content,
        }

    async def cleanup(self) -> None:
        for name in reversed(list(self.connections.keys())):
            await self.connections[name].cleanup()
        self.connections.clear()
        self._routes.clear()
        self._tools.clear()
