from __future__ import annotations

import threading
import time
import unittest

from backend.tools.llamaindex_rag.scheduler import IndexRebuildScheduler


class IndexRebuildSchedulerTests(unittest.TestCase):
    def test_schedule_triggers_single_rebuild_when_idle(self) -> None:
        calls: list[float] = []
        gate = threading.Event()

        def fake_rebuild() -> None:
            calls.append(time.monotonic())
            gate.wait(timeout=1.0)

        scheduler = IndexRebuildScheduler(rebuild_fn=fake_rebuild)
        first = scheduler.schedule_rebuild("a.pdf")
        self.assertTrue(first["scheduled"])
        self.assertEqual(first["pending_files"], ["a.pdf"])

        gate.set()
        self.assertTrue(scheduler.wait_for_idle(timeout=2.0))
        self.assertEqual(len(calls), 1)

    def test_schedule_during_rebuild_queues_followup(self) -> None:
        calls: list[list[str]] = []
        gate = threading.Event()

        def fake_rebuild() -> None:
            gate.wait(timeout=2.0)
            calls.append(["tick"])

        scheduler = IndexRebuildScheduler(rebuild_fn=fake_rebuild)

        first = scheduler.schedule_rebuild("a.pdf")
        self.assertTrue(first["scheduled"])

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            status = scheduler.status()
            if status["building"]:
                break
            time.sleep(0.01)
        self.assertTrue(scheduler.status()["building"])

        second = scheduler.schedule_rebuild("b.pdf")
        self.assertFalse(second["scheduled"])
        self.assertEqual(sorted(second["pending_files"]), ["a.pdf", "b.pdf"])

        gate.set()
        self.assertTrue(scheduler.wait_for_idle(timeout=3.0))
        self.assertGreaterEqual(len(calls), 1)
        self.assertLessEqual(len(calls), 2)

    def test_status_reports_eta_for_pending_files(self) -> None:
        gate = threading.Event()

        def fake_rebuild() -> None:
            gate.wait(timeout=2.0)

        scheduler = IndexRebuildScheduler(rebuild_fn=fake_rebuild)
        scheduler.schedule_rebuild("a.pdf")
        scheduler.schedule_rebuild("b.pdf")

        status = scheduler.status()
        self.assertTrue(status["building"])
        self.assertEqual(sorted(status["pending_files"]), ["a.pdf", "b.pdf"])
        self.assertGreater(status["eta_seconds"], 0)

        gate.set()
        self.assertTrue(scheduler.wait_for_idle(timeout=3.0))
        idle_status = scheduler.status()
        self.assertFalse(idle_status["building"])
        self.assertEqual(idle_status["pending_files"], [])

    def test_rebuild_failure_clears_pending_and_allows_retry(self) -> None:
        fail_on_first = {"value": True}

        def fake_rebuild() -> None:
            if fail_on_first["value"]:
                fail_on_first["value"] = False
                raise RuntimeError("simulated")

        scheduler = IndexRebuildScheduler(rebuild_fn=fake_rebuild)
        scheduler.schedule_rebuild("a.pdf")
        self.assertTrue(scheduler.wait_for_idle(timeout=2.0))
        self.assertEqual(scheduler.status()["pending_files"], [])

        scheduler.schedule_rebuild("b.pdf")
        self.assertTrue(scheduler.wait_for_idle(timeout=2.0))
        self.assertEqual(scheduler.status()["pending_files"], [])


if __name__ == "__main__":
    unittest.main()
