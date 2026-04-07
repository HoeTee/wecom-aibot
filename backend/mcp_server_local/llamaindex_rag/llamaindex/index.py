import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from llama_index.core import Document, SummaryIndex, StorageContext, VectorStoreIndex, load_index_from_storage

from .chunk import LlamaIndexChunker
from .load import LlamaIndexLoader

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "persist"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "manifest" / "manifest.json"


@dataclass
class IndexBundle:
    vector_index: VectorStoreIndex
    summary_index: SummaryIndex
    source_files: list[str]
    summary_documents: list[Document]


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

    def _paper_brief_text(self, file_name: str, full_text: str) -> str:
        normalized_text = "\n".join(line.strip() for line in full_text.splitlines() if line.strip())
        lines = normalized_text.splitlines()
        title = lines[0] if lines else file_name

        abstract_match = re.search(
            r"\bAbstract\b(.*?)(?:\b1\s+Introduction\b|\bIntroduction\b)",
            normalized_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if abstract_match:
            abstract = re.sub(r"\s+", " ", abstract_match.group(1)).strip()
        else:
            abstract = re.sub(r"\s+", " ", normalized_text[:2000]).strip()

        return (
            f"file_name: {file_name}\n"
            f"title: {title}\n"
            f"abstract_or_preview: {abstract[:2000]}"
        )

    def _summary_documents(self, documents: list[Document]) -> list[Document]:
        grouped_text: dict[str, list[str]] = {}
        grouped_metadata: dict[str, dict] = {}

        for document in documents:
            metadata = dict(getattr(document, "metadata", {}) or {})
            file_name = metadata.get("file_name") or metadata.get("filename") or str(getattr(document, "doc_id", "unknown"))
            grouped_text.setdefault(file_name, []).append(document.text)
            grouped_metadata[file_name] = metadata

        summary_documents: list[Document] = []
        for file_name in sorted(grouped_text):
            metadata = grouped_metadata.get(file_name, {})
            metadata["file_name"] = file_name
            summary_documents.append(
                Document(
                    text=self._paper_brief_text(file_name, "\n\n".join(grouped_text[file_name])),
                    metadata=metadata,
                    id_=file_name,
                )
            )

        return summary_documents

    def build(self) -> IndexBundle:
        doc_hashes = self._current_doc_hashes()
        manifest = self._read_manifest()
        documents = self.loader.load()
        summary_documents = self._summary_documents(documents)
        nodes = self.chunker.chunk(documents=documents)
        source_files = [document.metadata.get("file_name", document.doc_id) for document in summary_documents]

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

        summary_index = SummaryIndex.from_documents(summary_documents)
        return IndexBundle(
            vector_index=vector_index,
            summary_index=summary_index,
            source_files=source_files,
            summary_documents=summary_documents,
        )
