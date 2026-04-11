from __future__ import annotations

import unittest
from pathlib import Path

from backend.tools import kb_cli


class KnowledgeBaseCliNamingTests(unittest.TestCase):
    def test_upload_storage_name_no_longer_uses_upload_prefix(self) -> None:
        self.assertEqual(kb_cli.upload_storage_name("linux-part1.pdf"), "linux-part1.pdf")

    def test_display_name_still_strips_legacy_upload_prefix(self) -> None:
        self.assertEqual(kb_cli._display_name(Path("upload__linux-part1.pdf")), "linux-part1.pdf")

    def test_records_are_exposed_as_knowledge_base_files(self) -> None:
        record = kb_cli._record_from_path(kb_cli.PROJECT_ROOT / "knowledge_base" / "linux-part1.pdf")
        self.assertEqual(record["source_type"], "knowledge_base")


if __name__ == "__main__":
    unittest.main()
