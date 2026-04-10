import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs" / "mcp"
STDERR_LOG_PATH = LOG_DIR / "llamaindex_rag_stderr.log"


def _configure_stderr_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stderr_stream = open(STDERR_LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stderr = stderr_stream


_configure_stderr_log()
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("llamaindex_rag")
_rag_engine = None


def _build_rag_engine():
    from backend.tools.llamaindex_rag.llamaindex.engine import LlamaIndexRAGEngine

    return LlamaIndexRAGEngine(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_model=os.getenv("LLM_MODEL"),
        embed_api_key=os.getenv("EMBED_API_KEY"),
        embed_base_url=os.getenv("EMBED_BASE_URL"),
        embed_model=os.getenv("EMBED_MODEL"),
        rerank_api_key=os.getenv("RERANK_API_KEY"),
        rerank_base_url=os.getenv("RERANK_BASE_URL"),
        rerank_model=os.getenv("RERANK_MODEL"),
    )


def _get_rag_engine():
    global _rag_engine

    if _rag_engine is None:
        try:
            _rag_engine = _build_rag_engine()
        except Exception as exc:  # pragma: no cover - defensive logging path
            traceback.print_exc(file=sys.stderr)
            raise RuntimeError(
                f"Failed to initialize llamaindex_rag engine. "
                f"See stderr log: {STDERR_LOG_PATH}. Root cause: {exc}"
            ) from exc

    return _rag_engine


@mcp.tool()
async def llamaindex_rag_query(query: str) -> str:
    """
    Query the local PDF knowledge base and return:
    1. a synthesized answer across the PDFs
    2. supporting evidence snippets for grounding

    Use this tool for source-based summarization, comparison, and document drafting.
    For summary requests, prefer structured output that can be turned into:
    背景、每篇论文摘要、横向对比、结论与建议。
    """
    return _get_rag_engine().query(query)


if __name__ == "__main__":
    mcp.run(transport="stdio")
