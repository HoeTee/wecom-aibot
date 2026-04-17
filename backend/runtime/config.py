from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    tool_prefix: str
    transport: str
    required: bool = False
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MCPHostConfig:
    servers: list[MCPServerConfig] = field(default_factory=list)


def _resolve_optional_path(value: str | None, *, base_dir: Path) -> str | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return str(candidate)


def _resolve_command(value: str | None, *, base_dir: Path) -> str | None:
    if not value:
        return None
    if "\\" not in value and "/" not in value and not value.startswith("."):
        return value
    return _resolve_optional_path(value, base_dir=base_dir)


def _coerce_server_config(raw: dict[str, Any], *, base_dir: Path) -> MCPServerConfig:
    return MCPServerConfig(
        name=str(raw.get("name") or "").strip(),
        tool_prefix=str(raw.get("tool_prefix") or "").strip(),
        transport=str(raw.get("transport") or "").strip(),
        required=bool(raw.get("required", False)),
        url=str(raw.get("url") or "").strip() or None,
        headers={str(k): str(v) for k, v in dict(raw.get("headers") or {}).items()},
        timeout_seconds=(
            float(raw["timeout_seconds"])
            if raw.get("timeout_seconds") is not None
            else None
        ),
        command=_resolve_command(
            str(raw.get("command") or "").strip() or None,
            base_dir=base_dir,
        ),
        args=[str(item) for item in list(raw.get("args") or [])],
        cwd=_resolve_optional_path(
            str(raw.get("cwd") or "").strip() or None,
            base_dir=base_dir,
        ),
        env={str(k): str(v) for k, v in dict(raw.get("env") or {}).items()},
    )


def build_single_server_config(url: str) -> MCPServerConfig:
    return MCPServerConfig(
        name="default",
        tool_prefix="wecom_docs",
        transport="streamable_http",
        url=str(url).strip(),
        required=False,
    )


def load_mcp_host_config(path: str | None = None) -> MCPHostConfig:
    raw_path = str(path or os.getenv("MCP_SERVERS_CONFIG") or "").strip()
    if not raw_path:
        return MCPHostConfig()
    config_path = Path(raw_path).expanduser()
    if not config_path.is_absolute():
        config_path = (PROJECT_ROOT / config_path).resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent
    servers = [
        _coerce_server_config(server_payload, base_dir=base_dir)
        for server_payload in list(payload.get("servers") or [])
    ]
    return MCPHostConfig(servers=servers)


def load_mcp_server_configs_from_env() -> list[MCPServerConfig]:
    config_path = str(os.getenv("MCP_SERVERS_CONFIG") or "").strip()
    if config_path:
        candidate = Path(config_path).expanduser()
        if not candidate.is_absolute():
            candidate = (PROJECT_ROOT / candidate).resolve()
        if candidate.exists():
            return load_mcp_host_config(str(candidate)).servers

    fallback_url = str(os.getenv("MCP_SERVER_URL") or "").strip()
    if fallback_url:
        return [build_single_server_config(fallback_url)]

    return []
