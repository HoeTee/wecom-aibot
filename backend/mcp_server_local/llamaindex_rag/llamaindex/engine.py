from llama_index.core import Settings
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.embeddings.openai_like import OpenAILikeEmbedding
from llama_index.llms.openai_like import OpenAILike

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
        similarity_top_k: int = 5,
        reranker: QwenRerankPostprocessor | None = None,
        reranker_top_k: int = 3,
    ):
        self.builder = builder or LlamaIndexBuilder()
        self.similarity_top_k = similarity_top_k

        self.reranker = reranker or QwenRerankPostprocessor(
            api_key=rerank_api_key,
            base_url=rerank_base_url,
            model=rerank_model,
            top_n=reranker_top_k,
            instruct="Given a search query, retrieve relevant passages that answer the query.",
        )

        Settings.llm = OpenAILike(
            api_key=llm_api_key,
            api_base=llm_base_url,
            model=llm_model,
            is_chat_model=True,
            is_function_calling_model=True,
        )

        Settings.embed_model = OpenAILikeEmbedding(
            api_key=embed_api_key,
            api_base=embed_base_url,
            model_name=embed_model,
        )

    def query(self, query: str) -> str:
        bundle = self.builder.build()
        if bundle is None:
            return "No index available. Please check the data directory and try again."

        retriever = bundle.vector_index.as_retriever(similarity_top_k=self.similarity_top_k)
        postprocessors = [self.reranker] if self.reranker else []

        vector_query_engine = RetrieverQueryEngine.from_args(
            retriever=retriever,
            node_postprocessors=postprocessors,
        )
        summary_query_engine = bundle.summary_index.as_query_engine(
            response_mode="tree_summarize"
        )

        summary_response = summary_query_engine.query(query)
        vector_response = vector_query_engine.query(query)

        parts: list[str] = []
        summary_text = str(summary_response).strip()
        if summary_text:
            parts.append(f"# 综合回答\n{summary_text}")

        evidence_parts: list[str] = []
        for i, source_node in enumerate(vector_response.source_nodes, 1):
            score = getattr(source_node, "score", None)
            text = source_node.get_content()
            metadata = getattr(source_node, "metadata", None) or {}

            filename = metadata.get("file_name") or metadata.get("filename") or metadata.get("source") or ""
            page_label = metadata.get("page_label") or metadata.get("page") or ""

            location = []
            if filename:
                location.append(f"file={filename}")
            if page_label != "":
                location.append(f"page={page_label}")

            header = f"## 证据片段 {i}"
            if location:
                header += f" [{', '.join(location)}]"
            if score is not None:
                header += f" (score={score:.3f})"

            evidence_parts.append(f"{header}\n{text}")

        if evidence_parts:
            parts.append("# 证据片段\n" + "\n\n---\n\n".join(evidence_parts))

        return "\n\n".join(parts) if parts else "No relevant sections found."
