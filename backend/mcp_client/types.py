from dataclasses import dataclass


@dataclass(frozen=True)
class MCPToolRoute:
    exposed_tool_name: str
    server_name: str
    remote_tool_name: str
