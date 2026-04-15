from __future__ import annotations

import unittest
from pathlib import Path

from backend.tools import kb_cli


class KnowledgeBaseCliNamingTests(unittest.TestCase):
    def test_upload_storage_name_uses_plain_filename(self) -> None:
        self.assertEqual(kb_cli.upload_storage_name("linux-part1.pdf"), "linux-part1.pdf")

    def test_display_name_returns_filename_as_is(self) -> None:
        self.assertEqual(kb_cli._display_name(Path("linux-part1.pdf")), "linux-part1.pdf")

    def test_records_have_no_source_type(self) -> None:
        record = kb_cli._record_from_path(kb_cli.PROJECT_ROOT / "knowledge_base" / "linux-part1.pdf")
        self.assertNotIn("source_type", record)
        self.assertEqual(record["file_name"], "linux-part1.pdf")


if __name__ == "__main__":
    unittest.main()
