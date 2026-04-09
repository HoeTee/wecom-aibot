import json
import urllib.request
from typing import Optional
from urllib.error import HTTPError
from urllib.parse import urlparse

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle


class QwenRerankPostprocessor(BaseNodePostprocessor):
    
    api_key: str
    api_base: str
    model: str
    top_n: int = 3
    instruct: str = (
        "Given a web search query, retrieve relevant passages that answer the query."
    )
    timeout: int = 30

    def __init__(
        self,
        api_key: str,
        base_url: str, 
        model: str,
        top_n: int = 3,
        instruct: str = (
            "Given a web search query, retrieve relevant passages that answer the query."
        ),
        timeout: int = 30,
        **kwargs,
    ) -> None:
        if not api_key:
            raise RuntimeError("api_key is required for QwenRerankPostprocessor")
        

        super().__init__(
            api_key=api_key,
            api_base=base_url,
            model=model,
            top_n=top_n,
            instruct=instruct,
            timeout=timeout,
            **kwargs,
        )

    @staticmethod
    def normalize_api_base(api_base: str) -> str:
        value = api_base.rstrip("/")
        parsed = urlparse(value)
        path = parsed.path.rstrip("/")

        if value.endswith("/reranks") or value.endswith("/text-rerank/text-rerank"):
            return value
        if path.endswith("/chat/completions"):
            return value[: -len("/chat/completions")] + "/reranks"
        if path.endswith("/embeddings"):
            return value[: -len("/embeddings")] + "/reranks"
        if path.endswith("/compatible-api/v1") or path.endswith("/compatible-mode/v1"):
            return value + "/reranks"
        if parsed.scheme and parsed.netloc and not path:
            return value + "/compatible-api/v1/reranks"
        return value

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> list[NodeWithScore]:
        if not nodes or query_bundle is None:
            return nodes

        documents = [
            node.get_content(metadata_mode=MetadataMode.NONE)
            for node in nodes
        ]

        payload = {
            "model": self.model,
            "query": query_bundle.query_str,
            "documents": documents,
            "top_n": min(self.top_n, len(documents)),
            "instruct": self.instruct,
        }

        body = None
        candidate_urls = [self.api_base]
        default_url = self.normalize_api_base(
            "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
        )
        if default_url not in candidate_urls:
            candidate_urls.append(default_url)

        last_error = None
        for url in candidate_urls:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    break
            except HTTPError as exc:
                last_error = exc
                if exc.code != 404 or url == candidate_urls[-1]:
                    raise

        if body is None:
            raise RuntimeError(f"Rerank request failed: {last_error}")

        if "results" in body:
            results = body["results"]
        elif "output" in body and "results" in body["output"]:
            results = body["output"]["results"]
        else:
            raise RuntimeError(f"Unexpected rerank response: {body}")

        reranked_nodes: list[NodeWithScore] = []
        for item in results:
            original_node = nodes[item["index"]]
            reranked_nodes.append(
                NodeWithScore(
                    node=original_node.node,
                    score=item.get("relevance_score", original_node.score),
                )
            )

        return reranked_nodes
