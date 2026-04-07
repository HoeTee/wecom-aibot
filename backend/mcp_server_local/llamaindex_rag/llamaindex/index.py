import os
import json
from pathlib import Path

from llama_index.core import (
    StorageContext, 
    load_index_from_storage,
    VectorStoreIndex
)

from .load import LlamaIndexLoader
from .chunk import LlamaIndexChunker

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "persist"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "manifest" / "manifest.json"

class LlamaIndexBuilder:

    def __init__(
            self, 
            loader: LlamaIndexLoader | None = None,
            chunker: LlamaIndexChunker | None = None, 
            persist_dir: str | Path =DEFAULT_PERSIST_DIR,
            manifest_path: str | Path =DEFAULT_MANIFEST_PATH
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

    def build(self) -> VectorStoreIndex: 
        doc_hashes = self._current_doc_hashes()
        manifest = self._read_manifest()
        
        if doc_hashes == manifest.get("doc_hashes", []) and self.persist_dir.exists():
            try:
                storage_context = StorageContext.from_defaults(persist_dir=str(self.persist_dir))
                index = load_index_from_storage(storage_context)
                return index
            except Exception as exc:
                print(f"Failed to load index from storage: {exc}. Rebuilding index.")
        
        nodes = self.chunker.chunk()
        index = VectorStoreIndex(nodes)

        os.makedirs(Path(self.persist_dir).resolve(), exist_ok=True)
        os.makedirs(Path(self.manifest_path).resolve().parent, exist_ok=True)

        index.storage_context.persist(persist_dir=str(self.persist_dir))

        with open(str(self.manifest_path), "w", encoding="utf-8") as f: 
            json.dump(
                {"doc_hashes": doc_hashes}, 
                f, 
                ensure_ascii=False, 
                indent=2
            )

        return index