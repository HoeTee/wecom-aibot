from __future__ import annotations

import copy
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs" / "cli"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "rag_runtime.log"

LOCAL_RAG_SEARCH_TOOL_NAME = "llamaindex_rag__llamaindex_rag_search"
LOCAL_RAG_SUMMARIZE_TOOL_NAME = "llamaindex_rag__llamaindex_rag_summarize"
LOCAL_RAG_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": LOCAL_RAG_SEARCH_TOOL_NAME,
        "description": (
            "Search the local PDF knowledge base for specific facts, passages, sections, "
            "or file-specific answers. Use this for targeted retrieval questions rather "
            "than full-document or whole-knowledge-base summaries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's retrieval or summarization request.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
LOCAL_RAG_SUMMARIZE_TOOL = {
    "type": "function",
    "function": {
        "name": LOCAL_RAG_SUMMARIZE_TOOL_NAME,
        "description": (
            "Summarize one file, multiple files, or the whole local PDF knowledge base "
            "into a structured Chinese synthesis. Use this for overviews, summaries, "
            "document drafting source material, or cross-document synthesis."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's summarization request.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


logger = logging.getLogger("RAGLocalRuntime")
if not logger.handlers:
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)


load_dotenv(PROJECT_ROOT / ".env")

_rag_engine = None


def is_rag_tool_name(function_name: str) -> bool:
    lowered = str(function_name or "").lower()
    return lowered.endswith("llamaindex_rag_search") or lowered.endswith("llamaindex_rag_summarize")


def get_local_rag_tools() -> list[dict[str, object]]:
    # summarize tool disabled: 40-70s per call due to extra LLM synthesis pass.
    # Code preserved in LOCAL_RAG_SUMMARIZE_TOOL; re-add here when latency is acceptable.
    return [copy.deepcopy(LOCAL_RAG_SEARCH_TOOL)]


def rag_action_for_tool_name(function_name: str) -> str | None:
    lowered = str(function_name or "").lower()
    if lowered.endswith("llamaindex_rag_search"):
        return "rag.search"
    if lowered.endswith("llamaindex_rag_summarize"):
        return "rag.summarize"
    return None


def _llm_model_name() -> str:
    return str(os.getenv("LLM_NAME") or os.getenv("LLM_MODEL") or "").strip()


def _build_rag_engine():
    from backend.tools.llamaindex_rag.llamaindex.engine import LlamaIndexRAGEngine

    logger.info("build_engine_start")
    engine = LlamaIndexRAGEngine(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_model=_llm_model_name(),
        embed_api_key=os.getenv("EMBED_API_KEY"),
        embed_base_url=os.getenv("EMBED_BASE_URL"),
        embed_model=os.getenv("EMBED_MODEL"),
        rerank_api_key=os.getenv("RERANK_API_KEY"),
        rerank_base_url=os.getenv("RERANK_BASE_URL"),
        rerank_model=os.getenv("RERANK_MODEL"),
    )
    logger.info("build_engine_done")
    return engine


def get_rag_engine():
    global _rag_engine

    if _rag_engine is None:
        try:
            _rag_engine = _build_rag_engine()
        except Exception:
            logger.exception("build_engine_failed")
            raise

    return _rag_engine


def _validate_query(query: str) -> str:
    query_text = str(query or "").strip()
    if not query_text:
        raise ValueError("rag query requires query")
    return query_text


def search_local_rag(query: str) -> str:
    query_text = _validate_query(query)
    logger.info("search_start query=%s", query_text[:200])
    try:
        result = get_rag_engine().search(query_text)
    except Exception:
        logger.exception("search_failed query=%s", query_text[:200])
        raise

    text = str(result or "")
    logger.info("search_done length=%s", len(text))
    return text


def summarize_local_rag(query: str) -> str:
    query_text = _validate_query(query)
    logger.info("summarize_start query=%s", query_text[:200])
    try:
        result = get_rag_engine().summarize(query_text)
    except Exception:
        logger.exception("summarize_failed query=%s", query_text[:200])
        raise

    text = str(result or "")
    logger.info("summarize_done length=%s", len(text))
    return text
