from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MCPToolRoute:
    exposed_tool_name: str
    server_name: str
    remote_tool_name: str
