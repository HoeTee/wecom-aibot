from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core import Settings
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.openai_like import OpenAILikeEmbedding

from .index import LlamaIndexBuilder
from .qwen_reranker import QwenRerankPostprocessor

class LlamaIndexRAGEngine:

    def __init__(
            self, 
            llm_api_key: str,
            llm_base_url: str,
            llm_model: str,
            embed_api_key: str,
            embed_base_url: str,
            embed_model: str,
            rerank_api_key: str,
            rerank_base_url: str,
            rerank_model: str,
            builder: LlamaIndexBuilder | None = None, 
            similarity_top_k: int=5, 
            reranker: QwenRerankPostprocessor | None = None, 
            reranker_top_k: int=3, 

    ): 

        self.builder = builder or LlamaIndexBuilder()
        self.similarity_top_k = similarity_top_k

        self.reranker = reranker or QwenRerankPostprocessor(
            api_key=rerank_api_key,
            base_url=rerank_base_url,
            model=rerank_model, 
            top_n=reranker_top_k, 
            instruct=(
                "Given a search query, retrieve relevant passages that answer the query."
            )
        )

        Settings.llm = OpenAILike(
            api_key=llm_api_key,
            api_base=llm_base_url,
            model=llm_model, 
            is_chat_model=True, 
            is_function_calling_model=True
        )

        Settings.embed_model = OpenAILikeEmbedding(
            api_key=embed_api_key,
            api_base=embed_base_url,
            model_name=embed_model
        )


    def query(self, query: str) -> str: 
        index = self.builder.build()
        if index is None:
            return "No index available. Please check the data directory and try again."
        retriever = index.as_retriever(similarity_top_k=self.similarity_top_k)
        postprocessors = [self.reranker] if self.reranker else []

        query_engine = RetrieverQueryEngine.from_args(
            retriever=retriever, 
            node_postprocessors=postprocessors
        )
        response = query_engine.query(query)

        # Format as structured text for downstream agents
        parts = []
        for i, source_node in enumerate(response.source_nodes, 1):
            score = getattr(source_node, "score", None)
            text = source_node.get_content()
            metadata = getattr(source_node, "metadata", None) or {}

            # Extract clause location from MarkdownNodeParser header_path
            header_path = metadata.get("header_path", "")
            # Clean separator padding: " / A / B / " → "A / B"
            sep = " / "
            location = header_path.strip().strip("/").strip()
            if location:
                # Use the real section path as the header
                header = f"## 所在位置：{location}"
            else:
                header = f"## 检索结果 {i}"
            if score is not None:
                header += f" (相关度: {score:.3f})"
            parts.append(f"{header}\n{text}")

        return "\n\n---\n\n".join(parts) if parts else "No relevant sections found." 
