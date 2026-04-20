from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.tools.llamaindex_rag import runtime
from backend.tools.llamaindex_rag.llamaindex.index import IndexBusy
from backend.tools.llamaindex_rag.scheduler import IndexRebuildScheduler


class FakeEngine:
    def __init__(self, search_effect) -> None:
        self._search_effect = search_effect

    def search(self, query: str) -> str:
        if isinstance(self._search_effect, Exception):
            raise self._search_effect
        return self._search_effect


class SearchLocalRagBusyPayloadTests(unittest.TestCase):
    def test_busy_payload_carries_scheduler_status(self) -> None:
        scheduler = IndexRebuildScheduler(rebuild_fn=lambda: None)
        scheduler._pending_files = ["a.pdf", "b.pdf"]

        with patch.object(runtime, "get_rag_engine", return_value=FakeEngine(IndexBusy())):
            with patch.object(runtime, "get_scheduler", return_value=scheduler):
                raw = runtime.search_local_rag("quantum computing")
        payload = json.loads(raw)
        self.assertEqual(payload["error_code"], "index_busy")
        self.assertEqual(sorted(payload["pending_files"]), ["a.pdf", "b.pdf"])
        self.assertGreaterEqual(payload["eta_seconds"], 0)

    def test_non_busy_search_returns_raw_text(self) -> None:
        with patch.object(runtime, "get_rag_engine", return_value=FakeEngine("hello world")):
            result = runtime.search_local_rag("anything")
        self.assertEqual(result, "hello world")

    def test_other_exceptions_propagate(self) -> None:
        with patch.object(runtime, "get_rag_engine", return_value=FakeEngine(RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                runtime.search_local_rag("anything")


if __name__ == "__main__":
    unittest.main()
