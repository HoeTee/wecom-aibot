from llama_index.core.node_parser import SentenceSplitter

from .load import LlamaIndexLoader


class LlamaIndexChunker:
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 100,
        loader: LlamaIndexLoader | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.loader = loader or LlamaIndexLoader()

    def chunk(self, documents=None):
        if documents is None:
            documents = self.loader.load()

        node_parser = SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        return node_parser.get_nodes_from_documents(documents)
