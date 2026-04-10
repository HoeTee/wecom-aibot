from __future__ import annotations

from typing import Any, Protocol


class RAGHost(Protocol):
    tools: list[dict[str, Any]]

    async def call_tool(self, exposed_name: str, args: dict[str, Any]) -> str:
        ...


def _find_rag_tool_name(host: RAGHost) -> str:
    for tool in host.tools:
        name = tool["function"]["name"]
        if name.lower().endswith("llamaindex_rag_query"):
            return name
    raise KeyError("Missing llamaindex_rag query tool")


async def execute_rag_action(action: str, **kwargs: Any) -> dict[str, Any]:
    host = kwargs.get("host")
    if host is None:
        raise ValueError("rag actions require host")

    if action not in {"rag.search", "rag.summarize"}:
        raise KeyError(f"Unknown rag action: {action}")

    query = str(kwargs.get("query") or "").strip()
    if not query:
        raise ValueError("rag action requires query")

    tool_name = _find_rag_tool_name(host)
    text = await host.call_tool(tool_name, {"query": query})
    return {
        "action": action,
        "query": query,
        "text": str(text or ""),
        "length": len(str(text or "")),
    }
