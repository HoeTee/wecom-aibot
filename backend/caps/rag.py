from __future__ import annotations

from backend.runtime import MCPHost


def _find_rag_tool_name(host: MCPHost) -> str:
    for tool in host.tools:
        name = tool["function"]["name"]
        if name.lower().endswith("llamaindex_rag_query"):
            return name
    raise KeyError("Missing llamaindex_rag query tool")


async def query_rag(host: MCPHost, query: str) -> str:
    tool_name = _find_rag_tool_name(host)
    return await host.call_tool(tool_name, {"query": query})
