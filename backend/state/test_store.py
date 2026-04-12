from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.state import store


class ExtractDocBindingTests(unittest.TestCase):
    def test_create_doc_keeps_wecom_smartsheet_url(self) -> None:
        raw_result = json.dumps(
            {
                "errcode": 0,
                "errmsg": "ok",
                "url": "https://doc.weixin.qq.com/smartsheet/s3_demo?scode=demo",
                "docid": "doc-1",
            }
        )

        binding = store.extract_doc_binding(
            "wecom_docs__create_doc",
            {"doc_type": 10, "doc_name": "KB smartsheet"},
            raw_result,
        )

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding["doc_id"], "doc-1")
        self.assertEqual(binding["doc_url"], "https://doc.weixin.qq.com/smartsheet/s3_demo?scode=demo")

    def test_smartsheet_error_ignores_devtool_query_url(self) -> None:
        raw_result = json.dumps(
            {
                "errcode": 2022030,
                "errmsg": (
                    "Smartsheet invalid title, hint: [1], more info at "
                    "https://open.work.weixin.qq.com/devtool/query?e=2022030"
                ),
            }
        )

        binding = store.extract_doc_binding(
            "wecom_docs__smartsheet_add_fields",
            {"docid": "doc-1", "sheet_id": "sheet-1"},
            raw_result,
        )

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding["doc_id"], "doc-1")
        self.assertIsNone(binding["doc_url"])


class PersistDocBindingTests(unittest.TestCase):
    def test_error_result_does_not_overwrite_existing_doc_url(self) -> None:
        original_db_path = store.DB_PATH
        original_connect = store._connect
        with tempfile.TemporaryDirectory() as tmp_dir:
            store.DB_PATH = Path(tmp_dir) / "memory.sqlite3"
            connections: list[sqlite3.Connection] = []

            def connect_override() -> sqlite3.Connection:
                conn = sqlite3.connect(store.DB_PATH)
                conn.row_factory = sqlite3.Row
                connections.append(conn)
                return conn

            store._connect = connect_override
            try:
                store.init_db()
                store.upsert_session_doc(
                    session_id="dm:test",
                    doc_id="doc-1",
                    doc_url="https://doc.weixin.qq.com/smartsheet/s3_demo?scode=demo",
                    doc_name="KB smartsheet",
                    last_tool_name="wecom_docs__create_doc",
                    last_user_text="create a smartsheet",
                    request_id="req-1",
                )

                raw_error = json.dumps(
                    {
                        "errcode": 2022030,
                        "errmsg": (
                            "Smartsheet invalid title, hint: [1], more info at "
                            "https://open.work.weixin.qq.com/devtool/query?e=2022030"
                        ),
                    }
                )
                store.persist_doc_binding_from_tool_result(
                    session_id="dm:test",
                    request_id="req-2",
                    tool_name="wecom_docs__smartsheet_add_fields",
                    args_dict={"docid": "doc-1", "sheet_id": "sheet-1"},
                    result_text=raw_error,
                    last_user_text="add a new column",
                )

                current = store.current_bound_doc("dm:test")
                self.assertIsNotNone(current)
                assert current is not None
                self.assertEqual(current["doc_url"], "https://doc.weixin.qq.com/smartsheet/s3_demo?scode=demo")
                self.assertEqual(current["doc_name"], "KB smartsheet")
            finally:
                for conn in connections:
                    conn.close()
                store._connect = original_connect
                store.DB_PATH = original_db_path


class LoadMemoryContextTests(unittest.TestCase):
    def test_load_memory_context_includes_latest_ten_user_turns(self) -> None:
        original_db_path = store.DB_PATH
        original_connect = store._connect
        with tempfile.TemporaryDirectory() as tmp_dir:
            store.DB_PATH = Path(tmp_dir) / "memory.sqlite3"
            connections: list[sqlite3.Connection] = []

            def connect_override() -> sqlite3.Connection:
                conn = sqlite3.connect(store.DB_PATH)
                conn.row_factory = sqlite3.Row
                connections.append(conn)
                return conn

            store._connect = connect_override
            try:
                store.init_db()
                for index in range(12):
                    request_id = f"req-{index:02d}"
                    store.save_turn("dm:test", "user", f"user-turn-{index:02d}", request_id=request_id)

                memory_context = store.load_memory_context("dm:test", include_bound_doc=False)

                self.assertIn("user-turn-11", memory_context)
                self.assertIn("user-turn-02", memory_context)
                self.assertNotIn("user-turn-01", memory_context)
                self.assertNotIn("user-turn-00", memory_context)
            finally:
                for conn in connections:
                    conn.close()
                store._connect = original_connect
                store.DB_PATH = original_db_path

    def test_load_memory_context_includes_turn_state_with_tools_and_assistant(self) -> None:
        original_db_path = store.DB_PATH
        original_connect = store._connect
        with tempfile.TemporaryDirectory() as tmp_dir:
            store.DB_PATH = Path(tmp_dir) / "memory.sqlite3"
            connections: list[sqlite3.Connection] = []

            def connect_override() -> sqlite3.Connection:
                conn = sqlite3.connect(store.DB_PATH)
                conn.row_factory = sqlite3.Row
                connections.append(conn)
                return conn

            store._connect = connect_override
            try:
                store.init_db()
                store.save_turn("dm:test", "user", "帮我总结知识库内容", request_id="req-1")
                store.save_tool_call(
                    "dm:test",
                    "kb__list_files",
                    {"scope": "all"},
                    '{"ok": true, "records": []}',
                    request_id="req-1",
                )
                store.save_turn("dm:test", "assistant", "已列出知识库文件。", request_id="req-1")

                memory_context = store.load_memory_context("dm:test", include_bound_doc=False)

                self.assertIn("Recent turn states", memory_context)
                self.assertIn("turn request_id=req-1", memory_context)
                self.assertIn("tool=kb__list_files", memory_context)
                self.assertIn("assistant=已列出知识库文件。", memory_context)
            finally:
                for conn in connections:
                    conn.close()
                store._connect = original_connect
                store.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
