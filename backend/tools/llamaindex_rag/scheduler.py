from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs" / "cli"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "rag_runtime.log"


logger = logging.getLogger("IndexRebuildScheduler")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)


ETA_SECONDS_PER_FILE = 15


def _default_rebuild() -> None:
    from backend.tools.llamaindex_rag.runtime import get_rag_engine

    engine = get_rag_engine()
    engine.builder.build()


class IndexRebuildScheduler:
    def __init__(self, rebuild_fn: Callable[[], None] | None = None) -> None:
        self._rebuild_fn = rebuild_fn or _default_rebuild
        self._state_lock = threading.Lock()
        self._pending_files: list[str] = []
        self._started_at: float | None = None
        self._worker: threading.Thread | None = None

    def schedule_rebuild(self, file_name: str | None = None) -> dict[str, object]:
        with self._state_lock:
            if file_name and file_name not in self._pending_files:
                self._pending_files.append(file_name)
            scheduled = False
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run,
                    name="IndexRebuildWorker",
                    daemon=True,
                )
                self._started_at = time.monotonic()
                scheduled = True
                self._worker.start()
            pending_snapshot = list(self._pending_files)
        logger.info(
            "schedule_rebuild file=%s scheduled=%s pending=%s",
            file_name,
            scheduled,
            pending_snapshot,
        )
        return {"scheduled": scheduled, "pending_files": pending_snapshot}

    def status(self) -> dict[str, object]:
        with self._state_lock:
            worker = self._worker
            building = bool(worker and worker.is_alive())
            pending = list(self._pending_files)
            started_at = self._started_at
        elapsed = (time.monotonic() - started_at) if started_at else 0.0
        eta = max(0, len(pending) * ETA_SECONDS_PER_FILE - int(elapsed)) if building else 0
        return {
            "building": building,
            "pending_files": pending,
            "elapsed": round(elapsed, 1),
            "eta_seconds": eta,
        }

    def wait_for_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._state_lock:
                worker = self._worker
                pending = list(self._pending_files)
            if pending == [] and (worker is None or not worker.is_alive()):
                return True
            time.sleep(0.02)
        return False

    def _run(self) -> None:
        while True:
            with self._state_lock:
                if not self._pending_files:
                    self._worker = None
                    self._started_at = None
                    return
                snapshot = list(self._pending_files)
            try:
                logger.info("rebuild_start pending=%s", snapshot)
                self._rebuild_fn()
                logger.info("rebuild_done processed=%s", snapshot)
            except Exception as exc:
                logger.exception("rebuild_failed error=%s", exc)
            with self._state_lock:
                self._pending_files = [f for f in self._pending_files if f not in snapshot]


_SCHEDULER: IndexRebuildScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def get_scheduler() -> IndexRebuildScheduler:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = IndexRebuildScheduler()
        return _SCHEDULER


def reset_scheduler_for_tests() -> None:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        _SCHEDULER = None
