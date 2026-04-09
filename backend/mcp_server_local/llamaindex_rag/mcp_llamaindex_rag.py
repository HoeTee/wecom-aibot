from backend.tools.llamaindex_rag.mcp_llamaindex_rag import llamaindex_rag_query, mcp

__all__ = ["llamaindex_rag_query", "mcp"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
