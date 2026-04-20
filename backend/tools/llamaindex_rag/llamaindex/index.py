import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from llama_index.core import Document, SummaryIndex, StorageContext, VectorStoreIndex, load_index_from_storage

from .chunk import LlamaIndexChunker
from .load import LlamaIndexLoader

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "data" / "index" / "persist"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "index" / "manifest.json"
MANIFEST_VERSION = 2
DEFAULT_LOAD_WORKERS = 4


_BUILD_LOCK = threading.Lock()


class IndexBusy(Exception):
    def __init__(self) -> None:
        super().__init__("index rebuild in progress")


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

    def _current_file_hashes(self) -> dict[str, str]:
        return self.loader._file_sha256_map(str(self.loader.data_dir))

    def _read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        with self.manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write_manifest(self, payload: dict) -> None:
        os.makedirs(self.manifest_path.parent, exist_ok=True)
        with self.manifest_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

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

    def _summary_documents_from_manifest(self, manifest_files: dict[str, dict], source_files: list[str]) -> list[Document]:
        summary_documents: list[Document] = []
        for file_name in source_files:
            entry = manifest_files[file_name]
            summary_documents.append(
                Document(
                    text=entry["summary_text"],
                    metadata={"file_name": file_name},
                    id_=file_name,
                )
            )
        return summary_documents

    def _load_existing_vector_index(self) -> VectorStoreIndex:
        storage_context = StorageContext.from_defaults(persist_dir=str(self.persist_dir))
        return load_index_from_storage(storage_context)

    def _persist_vector_index(self, vector_index: VectorStoreIndex) -> None:
        os.makedirs(self.persist_dir, exist_ok=True)
        vector_index.storage_context.persist(persist_dir=str(self.persist_dir))

    def _full_rebuild(self, current_hashes: dict[str, str]) -> IndexBundle:
        documents = self.loader.load()
        summary_documents = self._summary_documents(documents)
        nodes = self.chunker.chunk(documents=documents)
        vector_index = VectorStoreIndex(nodes)

        self._persist_vector_index(vector_index)

        now_iso = datetime.now(UTC).isoformat()
        manifest_files = {
            document.metadata.get("file_name", document.doc_id): {
                "sha256": current_hashes[document.metadata.get("file_name", document.doc_id)],
                "ref_doc_id": document.metadata.get("file_name", document.doc_id),
                "summary_text": document.text,
                "updated_at": now_iso,
            }
            for document in summary_documents
        }
        self._write_manifest({"version": MANIFEST_VERSION, "files": manifest_files})

        source_files = sorted(manifest_files)
        summary_index = SummaryIndex.from_documents(summary_documents)
        return IndexBundle(
            vector_index=vector_index,
            summary_index=summary_index,
            source_files=source_files,
            summary_documents=summary_documents,
        )

    def _incremental_build(
        self,
        vector_index: VectorStoreIndex,
        manifest_files: dict[str, dict],
        current_hashes: dict[str, str],
    ) -> IndexBundle:
        stored_names = set(manifest_files)
        current_names = set(current_hashes)
        deleted = sorted(stored_names - current_names)
        added = sorted(current_names - stored_names)
        changed = sorted(
            file_name
            for file_name in (stored_names & current_names)
            if manifest_files[file_name].get("sha256") != current_hashes[file_name]
        )

        for file_name in deleted + changed:
            vector_index.delete_ref_doc(file_name, delete_from_docstore=True)

        changed_summary_map: dict[str, Document] = {}
        files_to_reload = added + changed
        if files_to_reload:
            documents = self._load_files_parallel(files_to_reload)
            changed_summary_documents = self._summary_documents(documents)
            changed_summary_map = {
                document.metadata.get("file_name", document.doc_id): document
                for document in changed_summary_documents
            }
            nodes = self.chunker.chunk(documents=documents)
            if nodes:
                vector_index.insert_nodes(nodes)

        now_iso = datetime.now(UTC).isoformat()
        new_manifest_files: dict[str, dict] = {}
        source_files = sorted(current_hashes)
        for file_name in source_files:
            if file_name in changed_summary_map:
                summary_document = changed_summary_map[file_name]
                new_manifest_files[file_name] = {
                    "sha256": current_hashes[file_name],
                    "ref_doc_id": file_name,
                    "summary_text": summary_document.text,
                    "updated_at": now_iso,
                }
            else:
                previous_entry = dict(manifest_files[file_name])
                previous_entry["sha256"] = current_hashes[file_name]
                previous_entry["ref_doc_id"] = file_name
                new_manifest_files[file_name] = previous_entry

        self._persist_vector_index(vector_index)
        self._write_manifest({"version": MANIFEST_VERSION, "files": new_manifest_files})

        summary_documents = self._summary_documents_from_manifest(new_manifest_files, source_files)
        summary_index = SummaryIndex.from_documents(summary_documents)
        return IndexBundle(
            vector_index=vector_index,
            summary_index=summary_index,
            source_files=source_files,
            summary_documents=summary_documents,
        )

    def _load_files_parallel(self, file_names: list[str]) -> list[Document]:
        if not file_names:
            return []
        file_map = self.loader._pdf_file_map()
        paths = [file_map[name] for name in file_names if name in file_map]
        if not paths:
            return []
        if len(paths) == 1:
            return self.loader.load(file_paths=paths)

        workers = min(DEFAULT_LOAD_WORKERS, len(paths))
        documents: list[Document] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-load") as pool:
            for batch in pool.map(lambda p: self.loader.load(file_paths=[p]), paths):
                documents.extend(batch)
        return documents

    def _build_locked(self) -> IndexBundle:
        current_hashes = self._current_file_hashes()
        manifest = self._read_manifest()
        manifest_files = manifest.get("files", {}) if manifest.get("version") == MANIFEST_VERSION else {}

        if not current_hashes:
            raise FileNotFoundError(f"No PDF files found in data directory: {self.loader.data_dir}")

        can_incremental_load = (
            self.persist_dir.exists()
            and bool(manifest_files)
            and all("summary_text" in entry for entry in manifest_files.values())
        )

        if not can_incremental_load:
            return self._full_rebuild(current_hashes)

        try:
            vector_index = self._load_existing_vector_index()
            return self._incremental_build(vector_index, manifest_files, current_hashes)
        except Exception as exc:
            print(f"Failed to apply incremental index update: {exc}. Rebuilding index.")
            return self._full_rebuild(current_hashes)

    def build(self) -> IndexBundle:
        with _BUILD_LOCK:
            return self._build_locked()

    def build_or_fail(self) -> IndexBundle:
        if not _BUILD_LOCK.acquire(blocking=False):
            raise IndexBusy()
        try:
            return self._build_locked()
        finally:
            _BUILD_LOCK.release()
