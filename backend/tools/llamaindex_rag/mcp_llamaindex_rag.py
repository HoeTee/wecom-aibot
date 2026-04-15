import sys
import traceback
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from backend.tools.llamaindex_rag.runtime import search_local_rag, summarize_local_rag

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs" / "mcp"
STDERR_LOG_PATH = LOG_DIR / "llamaindex_rag_stderr.log"


def _configure_stderr_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stderr_stream = open(STDERR_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stderr = stderr_stream


_configure_stderr_log()

mcp = FastMCP("llamaindex_rag")


@mcp.tool()
async def llamaindex_rag_search(query: str) -> str:
    """
    Search the local PDF knowledge base for specific facts, sections, and evidence passages.
    Use this for targeted retrieval questions, not whole-knowledge-base summaries.
    """
    try:
        return search_local_rag(query)
    except Exception as exc:  # pragma: no cover - defensive logging path
        traceback.print_exc(file=sys.stderr)
        raise RuntimeError(
            f"Failed to search llamaindex_rag locally. "
            f"See stderr log: {STDERR_LOG_PATH}. Root cause: {exc}"
        ) from exc


@mcp.tool()
async def llamaindex_rag_summarize(query: str) -> str:
    """
    Summarize one file, multiple files, or the whole local PDF knowledge base.
    Use this for overviews, synthesis, and document drafting source material.
    """
    try:
        return summarize_local_rag(query)
    except Exception as exc:  # pragma: no cover - defensive logging path
        traceback.print_exc(file=sys.stderr)
        raise RuntimeError(
            f"Failed to summarize llamaindex_rag locally. "
            f"See stderr log: {STDERR_LOG_PATH}. Root cause: {exc}"
        ) from exc


if __name__ == "__main__":
    mcp.run(transport="stdio")
