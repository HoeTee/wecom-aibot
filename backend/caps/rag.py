from __future__ import annotations

from typing import Any

from backend.runtime import async_dispatch_cli_action
from backend.tools.llamaindex_rag.scheduler import get_scheduler


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


def schedule_index_rebuild(file_name: str | None = None) -> dict[str, object]:
    return get_scheduler().schedule_rebuild(file_name)


def index_rebuild_status() -> dict[str, object]:
    return get_scheduler().status()
