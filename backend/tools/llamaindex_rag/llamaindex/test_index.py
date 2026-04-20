from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from backend.tools.llamaindex_rag.llamaindex.index import (
    IndexBusy,
    LlamaIndexBuilder,
    _BUILD_LOCK,
)


class BuildLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = LlamaIndexBuilder.__new__(LlamaIndexBuilder)

    def test_build_or_fail_raises_when_lock_held(self) -> None:
        _BUILD_LOCK.acquire()
        try:
            with self.assertRaises(IndexBusy):
                self.builder.build_or_fail()
        finally:
            _BUILD_LOCK.release()

    def test_build_or_fail_succeeds_when_lock_free(self) -> None:
        sentinel = object()
        with patch.object(self.builder, "_build_locked", return_value=sentinel):
            result = self.builder.build_or_fail()
        self.assertIs(result, sentinel)
        self.assertFalse(_BUILD_LOCK.locked())

    def test_concurrent_builds_serialize(self) -> None:
        active = {"count": 0, "max": 0}
        active_lock = threading.Lock()

        def fake_build() -> str:
            with active_lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.05)
            with active_lock:
                active["count"] -= 1
            return "done"

        with patch.object(self.builder, "_build_locked", side_effect=fake_build):
            threads = [threading.Thread(target=self.builder.build) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        self.assertEqual(active["max"], 1)
        self.assertFalse(_BUILD_LOCK.locked())

    def test_build_releases_lock_on_exception(self) -> None:
        with patch.object(self.builder, "_build_locked", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.builder.build()
        self.assertFalse(_BUILD_LOCK.locked())

        with patch.object(self.builder, "_build_locked", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.builder.build_or_fail()
        self.assertFalse(_BUILD_LOCK.locked())


if __name__ == "__main__":
    unittest.main()
