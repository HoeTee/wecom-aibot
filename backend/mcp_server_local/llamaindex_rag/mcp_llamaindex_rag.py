import os
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from backend.mcp_server_local.llamaindex_rag.llamaindex.engine import LlamaIndexRAGEngine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("llamaindex_rag")

rag_engine = LlamaIndexRAGEngine(
    llm_api_key=os.getenv("LLM_API_KEY"), 
    llm_base_url=os.getenv("LLM_BASE_URL"), 
    llm_model=os.getenv("LLM_MODEL"),
    embed_api_key=os.getenv("EMBED_API_KEY"),
    embed_base_url=os.getenv("EMBED_BASE_URL"),
    embed_model=os.getenv("EMBED_MODEL"),
    rerank_api_key=os.getenv("RERANK_API_KEY"),
    rerank_base_url=os.getenv("RERANK_BASE_URL"),
    rerank_model=os.getenv("RERANK_MODEL")
)

@mcp.tool()
async def llamaindex_rag_query(query: str) -> str: 
    """
    Query the LlamaIndex RAG engine with the given query and return the response.
    """
    response = rag_engine.query(query)
    return response

if __name__ == "__main__":
    mcp.run(transport="stdio")
