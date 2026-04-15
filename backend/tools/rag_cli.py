from __future__ import annotations

import asyncio
from typing import Any

from backend.tools.llamaindex_rag.runtime import search_local_rag, summarize_local_rag


async def execute_rag_action(action: str, **kwargs: Any) -> dict[str, Any]:
    if action not in {"rag.search", "rag.summarize"}:
        raise KeyError(f"Unknown rag action: {action}")

    query = str(kwargs.get("query") or "").strip()
    if not query:
        raise ValueError("rag action requires query")

    if action == "rag.search":
        text = await asyncio.to_thread(search_local_rag, query)
    else:
        text = await asyncio.to_thread(summarize_local_rag, query)
    return {
        "action": action,
        "query": query,
        "text": str(text or ""),
        "length": len(str(text or "")),
    }
