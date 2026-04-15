from __future__ import annotations

from typing import Any

from backend.runtime import async_dispatch_cli_action


async def query_rag(host: Any | None, query: str) -> str:
    result = await async_dispatch_cli_action(
        "rag.search",
        query=query,
    )
    return str(result.get("text") or "")


async def summarize_rag(host: Any | None, query: str) -> str:
    result = await async_dispatch_cli_action(
        "rag.summarize",
        query=query,
    )
    return str(result.get("text") or "")
