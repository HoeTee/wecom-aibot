import hashlib
from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAPER_DIR = PROJECT_ROOT / "knowledge_base" / "papers"
LEGACY_DATA_DIR = PROJECT_ROOT / "docs"


class LlamaIndexLoader:

    def __init__(
            self, 
            data_dir: Path | None = None
        ) -> None: 
        resolved_dir = data_dir
        if resolved_dir is None:
            if DEFAULT_PAPER_DIR.exists():
                resolved_dir = DEFAULT_PAPER_DIR
            else:
                resolved_dir = LEGACY_DATA_DIR
        self.data_dir = Path(resolved_dir).resolve()
    

    def _pdf_files(self, file_dir: Path | None = None) -> list[Path]: 
        target_dir = self.data_dir if file_dir is None else Path(file_dir).resolve()
        return sorted(
            [pdf for pdf in target_dir.rglob("*.pdf") if pdf.is_file()]
        )

    def _pdf_file_map(self, file_dir: Path | None = None) -> dict[str, Path]:
        return {file_path.name: file_path for file_path in self._pdf_files(file_dir)}
    
    
    def _file_sha256(self, file_dir: Path | None = None) -> list[str]: 
        if file_dir is None:
            file_dir = self.data_dir # 如果没有提供文件目录，就使用默认的数据目录（回退值）
        
        hashes = []

        for file_path in self._pdf_files(file_dir): # 遍历所有pdf文件
            h = hashlib.sha256() # 创建一个sha256哈希对象
            with open(file_path, "rb") as f: # read binary (for hash)，并且二进制不支持encoding，所以不需要指定编码格式
                for chunk in iter(lambda: f.read(8192), b""): # 每次读8192字节/8kb，分块读适合大文件；iter不断去读下一块，直到读到空块（b""）为止
                    h.update(chunk) # b把hash值变成sha-256格式
            h_complete = h.hexdigest() # 输出当前最终完整的sha-256值
            hashes.append(h_complete)

        hashes.sort()
        return hashes # 输出sha-256值列

    def _file_sha256_map(self, file_dir: Path | None = None) -> dict[str, str]:
        target_dir = self.data_dir if file_dir is None else Path(file_dir).resolve()
        hash_map: dict[str, str] = {}

        for file_path in self._pdf_files(target_dir):
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            hash_map[file_path.name] = h.hexdigest()

        return dict(sorted(hash_map.items()))


    def _validate_data_dir(self, data_dir: Path):
        if not data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")
        
        if not data_dir.is_dir():
            raise NotADirectoryError(f"Given path is not a directory: {data_dir}")
        
        pdf_files = self._pdf_files(data_dir)
        if not pdf_files:
            raise FileNotFoundError(f"No PDF files found in data directory: {data_dir}")

    def load(self, file_paths: list[Path] | None = None):
        if file_paths is None:
            self._validate_data_dir(self.data_dir)
            input_dir = str(self.data_dir)
            input_files = None
        else:
            input_files = [str(Path(path).resolve()) for path in file_paths]
            if not input_files:
                return []
            input_dir = None

        file_extractor = {}
        file_extractor[".pdf"] = PDFReader()

        reader = SimpleDirectoryReader(
            input_dir=input_dir,
            input_files=input_files,
            required_exts=['.pdf'], 
            file_extractor=file_extractor, 
            raise_on_error=True, 
            filename_as_id=True
            )
        
        return reader.load_data()
