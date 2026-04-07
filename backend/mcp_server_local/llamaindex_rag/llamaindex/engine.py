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

    def _content_query(self, query: str) -> str:
        content_query = query
        replacements = {
            "生成一份企业微信文档": "生成一份基于来源材料的文档内容",
            "给刚才那份文档": "",
            "不要新建文档": "",
            "回复要简洁，并明确告诉我是否已经创建文档。": "",
            "回复要简洁，并明确告诉我是否已经创建文档": "",
        }

        for old, new in replacements.items():
            content_query = content_query.replace(old, new)

        filtered_lines: list[str] = []
        for line in content_query.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "明确告诉我是否已经创建文档" in stripped:
                continue
            if stripped.startswith("回复要"):
                continue
            filtered_lines.append(stripped)

        return "\n".join(filtered_lines).strip() or query.strip()

    def query(self, query: str) -> str:
        bundle = self.builder.build()
        if bundle is None:
            return "No index available. Please check the data directory and try again."

        content_query = self._content_query(query)
        source_files = bundle.source_files
        source_file_block = "\n".join(f"- {name}" for name in source_files)
        summary_brief_block = "\n\n".join(
            f"## {document.metadata.get('file_name', document.doc_id)}\n{document.text}"
            for document in bundle.summary_documents
        )

        retriever = bundle.vector_index.as_retriever(similarity_top_k=self.similarity_top_k)
        postprocessors = [self.reranker] if self.reranker else []

        vector_query_engine = RetrieverQueryEngine.from_args(
            retriever=retriever,
            node_postprocessors=postprocessors,
        )
        summary_query = (
            "Answer in Chinese and rely only on the provided paper briefs.\n"
            f"The knowledge base currently contains exactly {len(source_files)} PDF documents:\n{source_file_block}\n\n"
            "Treat each listed PDF as one paper and use all of them unless the user explicitly narrows scope.\n"
            "Do not invent missing-domain constraints such as NLP/CV/multimodal.\n"
            "If the request also contains document-creation, document-editing, or reply-style instructions, ignore those operational instructions here and focus only on the source-grounded content that should go into the document body.\n"
            "Do not introduce a comparison table unless the request explicitly asks for a table.\n"
            "Do not answer with '材料不足' just because the request mentions creating or editing a document.\n"
            "Only mark a field as unknown when the paper brief itself does not provide enough information.\n"
            "When the user requests a multi-paper summary, produce a structured synthesis with these sections when applicable:\n"
            "1. 背景\n"
            "2. 每篇论文摘要（每篇至少包含研究目标、方法、主要发现）\n"
            "3. 横向对比（共同点、主要差异、优缺点）\n"
            "4. 结论与建议\n\n"
            f"Paper briefs:\n{summary_brief_block}\n\n"
            f"Content task:\n{content_query}"
        )

        summary_response = Settings.llm.complete(summary_query)
        vector_response = vector_query_engine.query(content_query)

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
