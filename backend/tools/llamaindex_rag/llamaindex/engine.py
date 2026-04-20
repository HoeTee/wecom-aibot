from __future__ import annotations

from llama_index.core import Settings
from llama_index.core.schema import QueryBundle
from llama_index.embeddings.openai_like import OpenAILikeEmbedding
from llama_index.llms.openai_like import OpenAILike

from .index import LlamaIndexBuilder
from .qwen_reranker import QwenRerankPostprocessor


MIN_RELEVANCE_SCORE = 0.10


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
        similarity_top_k: int = 15,
        reranker: QwenRerankPostprocessor | None = None,
        reranker_top_k: int = 5,
        min_relevance_score: float = MIN_RELEVANCE_SCORE,
    ) -> None:
        self.min_relevance_score = min_relevance_score
        self.builder = builder or LlamaIndexBuilder()
        self.similarity_top_k = similarity_top_k

        self.reranker = reranker
        if self.reranker is None and rerank_api_key and rerank_model:
            self.reranker = QwenRerankPostprocessor(
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
        content_query = str(query or "")
        replacements = {
            "重新生成一份企业微信文档": "生成一份基于来源材料的文档内容",
            "给刚才那份文档": "",
            "给刚才那个文档": "",
            "不要新建文档": "",
            "回复要简洁，并明确告诉我是否已经创建文档。": "",
            "回复要简洁。": "",
        }

        for old, new in replacements.items():
            content_query = content_query.replace(old, new)

        filtered_lines: list[str] = []
        for raw_line in content_query.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "明确告诉我是否已经创建文档" in line:
                continue
            if line.startswith("回复要"):
                continue
            filtered_lines.append(line)

        return "\n".join(filtered_lines).strip() or str(query or "").strip()

    def _build_summary_prompt(self, bundle, content_query: str) -> str:
        source_files = bundle.source_files
        source_file_block = "\n".join(f"- {name}" for name in source_files)
        summary_brief_block = "\n\n".join(
            f"## {document.metadata.get('file_name', document.doc_id)}\n{document.text}"
            for document in bundle.summary_documents
        )

        return (
            "Answer in Chinese and rely only on the provided paper briefs.\n"
            f"The knowledge base currently contains exactly {len(source_files)} PDF documents:\n{source_file_block}\n\n"
            "Treat each listed PDF as one paper and use all of them unless the user explicitly narrows scope.\n"
            "Do not invent missing-domain constraints such as NLP, CV, or multimodal unless the source material says so.\n"
            "If the request also contains document-creation, document-editing, or reply-style instructions, ignore those operational instructions here and focus only on the source-grounded content that should go into the document body.\n"
            "Do not introduce a comparison table unless the request explicitly asks for a table.\n"
            "Only mark a field as unknown when the paper brief itself does not provide enough information.\n"
            "When the user requests a multi-paper summary, produce a structured synthesis with these sections when applicable:\n"
            "1. 背景\n"
            "2. 每篇论文摘要（每篇至少包含研究目标、方法、主要发现）\n"
            "3. 横向对比（共同点、主要差异、优缺点）\n"
            "4. 结论与建议\n\n"
            f"Paper briefs:\n{summary_brief_block}\n\n"
            f"Content task:\n{content_query}"
        )

    def _format_retrieved_nodes(self, nodes) -> str:
        if not nodes:
            return "No relevant sections found."

        parts: list[str] = []
        for i, source_node in enumerate(nodes, 1):
            score = getattr(source_node, "score", None)
            text = source_node.get_content()
            metadata = getattr(source_node, "metadata", None) or {}

            filename = metadata.get("file_name") or metadata.get("filename") or metadata.get("source") or ""
            page_label = metadata.get("page_label") or metadata.get("page") or ""

            location: list[str] = []
            if filename:
                location.append(f"file={filename}")
            if page_label != "":
                location.append(f"page={page_label}")

            header = f"## Evidence {i}"
            if location:
                header += f" [{', '.join(location)}]"
            if score is not None:
                header += f" (score={score:.3f})"

            parts.append(f"{header}\n{text}")

        return "# Retrieved Passages\n" + "\n\n---\n\n".join(parts)

    def summarize(self, query: str) -> str:
        bundle = self.builder.build()
        content_query = self._content_query(query)
        summary_query = self._build_summary_prompt(bundle, content_query)
        summary_response = Settings.llm.complete(summary_query)
        summary_text = str(summary_response).strip()
        return summary_text or "No summary generated."

    def search(self, query: str) -> str:
        bundle = self.builder.build_or_fail()
        content_query = self._content_query(query)

        retriever = bundle.vector_index.as_retriever(similarity_top_k=self.similarity_top_k)
        nodes = retriever.retrieve(content_query)

        if self.reranker:
            nodes = self.reranker.postprocess_nodes(
                nodes,
                query_bundle=QueryBundle(query_str=content_query),
            )

        if self.min_relevance_score > 0:
            nodes = [
                n for n in nodes
                if getattr(n, "score", None) is None or n.score >= self.min_relevance_score
            ]

        return self._format_retrieved_nodes(nodes)

    def query(self, query: str) -> str:
        return self.summarize(query)
