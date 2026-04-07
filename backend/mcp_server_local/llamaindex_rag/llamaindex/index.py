import json
import os
from dataclasses import dataclass
from pathlib import Path

from llama_index.core import SummaryIndex, StorageContext, VectorStoreIndex, load_index_from_storage

from .chunk import LlamaIndexChunker
from .load import LlamaIndexLoader

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "persist"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "manifest" / "manifest.json"


@dataclass
class IndexBundle:
    vector_index: VectorStoreIndex
    summary_index: SummaryIndex


class LlamaIndexBuilder:
    def __init__(
        self,
        loader: LlamaIndexLoader | None = None,
        chunker: LlamaIndexChunker | None = None,
        persist_dir: str | Path = DEFAULT_PERSIST_DIR,
        manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    ) -> None:
        self.loader = loader or LlamaIndexLoader()
        self.chunker = chunker or LlamaIndexChunker(loader=self.loader)
        self.chunker.loader = self.loader
        self.persist_dir = Path(persist_dir).resolve()
        self.manifest_path = Path(manifest_path).resolve()

    def _current_doc_hashes(self) -> list[str]:
        return self.loader._file_sha256(str(self.loader.data_dir))

    def _read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        with self.manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def build(self) -> IndexBundle:
        doc_hashes = self._current_doc_hashes()
        manifest = self._read_manifest()
        documents = self.loader.load()
        nodes = self.chunker.chunk(documents=documents)

        vector_index = None
        if doc_hashes == manifest.get("doc_hashes", []) and self.persist_dir.exists():
            try:
                storage_context = StorageContext.from_defaults(persist_dir=str(self.persist_dir))
                vector_index = load_index_from_storage(storage_context)
            except Exception as exc:
                print(f"Failed to load index from storage: {exc}. Rebuilding index.")

        if vector_index is None:
            vector_index = VectorStoreIndex(nodes)
            os.makedirs(self.persist_dir, exist_ok=True)
            os.makedirs(self.manifest_path.parent, exist_ok=True)

            vector_index.storage_context.persist(persist_dir=str(self.persist_dir))
            with self.manifest_path.open("w", encoding="utf-8") as f:
                json.dump({"doc_hashes": doc_hashes}, f, ensure_ascii=False, indent=2)

        summary_index = SummaryIndex(nodes)
        return IndexBundle(
            vector_index=vector_index,
            summary_index=summary_index,
        )
