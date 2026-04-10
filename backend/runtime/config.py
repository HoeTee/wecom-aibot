from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MCPServerConfig(BaseModel):
    name: str
    transport: Literal["streamable_http", "sse", "stdio"]

    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    enabled: bool = True
    required: bool = False
    tool_prefix: str | None = None
    timeout_seconds: float | None = None

    @model_validator(mode="after")
    def validate_transport_fields(self) -> "MCPServerConfig":
        if self.transport in {"streamable_http", "sse"}:
            if not self.url:
                raise ValueError(f"{self.transport} transport requires 'url'")
            if self.command:
                raise ValueError(f"{self.transport} transport does not use 'command'")

        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio transport requires 'command'")
            if self.url:
                raise ValueError("stdio transport does not use 'url'")

        return self


class MCPHostConfig(BaseModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)


def _resolve_config_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _resolve_project_path(path_value: str | None) -> str | None:
    if not path_value:
        return path_value

    candidate = Path(path_value)
    if candidate.is_absolute():
        return str(candidate)

    project_candidate = PROJECT_ROOT / candidate
    if project_candidate.exists():
        return str(project_candidate)

    return path_value


def normalize_tool_prefix(name: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in name.strip())
    normalized = normalized.strip("_").lower()
    if not normalized:
        raise ValueError("tool prefix cannot be empty after normalization")
    if normalized[0].isdigit():
        normalized = f"mcp_{normalized}"
    return normalized


def hydrate_server_config(server: MCPServerConfig) -> MCPServerConfig:
    data = server.model_dump()
    data["tool_prefix"] = normalize_tool_prefix(server.tool_prefix or server.name)
    data["cwd"] = _resolve_project_path(server.cwd)
    data["command"] = _resolve_project_path(server.command)
    return MCPServerConfig.model_validate(data)


def load_mcp_host_config(path: str | Path) -> MCPHostConfig:
    config_path = _resolve_config_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"servers": payload}

    config = MCPHostConfig.model_validate(payload)
    return MCPHostConfig(
        servers=[hydrate_server_config(server) for server in config.servers if server.enabled]
    )


def build_legacy_single_server_config(server_target: str) -> MCPServerConfig:
    target = server_target.strip()
    if not target:
        raise ValueError("No MCP server target configured")

    if target.startswith(("http://", "https://")):
        return hydrate_server_config(
            MCPServerConfig(
                name="default",
                transport="streamable_http",
                url=target,
                required=False,
            )
        )

    if target.endswith(".py"):
        return hydrate_server_config(
            MCPServerConfig(
                name="default",
                transport="stdio",
                command=sys.executable,
                args=[target],
                required=False,
            )
        )

    if target.endswith(".js"):
        return hydrate_server_config(
            MCPServerConfig(
                name="default",
                transport="stdio",
                command="node",
                args=[target],
                required=False,
            )
        )

    raise ValueError(
        "Legacy MCP_SERVER_URL must be an http(s) URL or a .py/.js entrypoint. "
        "Use MCP_SERVERS_CONFIG for explicit transport configuration."
    )


def load_mcp_server_configs_from_env(env: dict[str, str] | None = None) -> list[MCPServerConfig]:
    env = env or os.environ

    config_path = str(env.get("MCP_SERVERS_CONFIG", "")).strip()
    if config_path:
        return load_mcp_host_config(config_path).servers

    legacy_target = str(env.get("MCP_SERVER_URL", "")).strip()
    if legacy_target:
        return [build_legacy_single_server_config(legacy_target)]

    return []
