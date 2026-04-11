from __future__ import annotations

import unittest

from backend.flow.chat import _append_bound_doc_link, _tool_modifies_wecom_target


class ChatReplyLinkTests(unittest.TestCase):
    def test_append_bound_doc_link_adds_link_once(self) -> None:
        reply = "已成功更新智能表格。"
        doc_url = "https://doc.weixin.qq.com/smartsheet/s3_demo?scode=demo"
        updated = _append_bound_doc_link(reply, doc_url)
        self.assertIn(doc_url, updated)
        self.assertEqual(updated.count(doc_url), 1)

    def test_append_bound_doc_link_does_not_duplicate_existing_link(self) -> None:
        doc_url = "https://doc.weixin.qq.com/doc/w3_demo?scode=demo"
        reply = f"已成功更新文档。\n\n链接：{doc_url}"
        updated = _append_bound_doc_link(reply, doc_url)
        self.assertEqual(updated, reply)

    def test_tool_modifies_wecom_target_matches_write_tools_only(self) -> None:
        self.assertTrue(_tool_modifies_wecom_target("wecom_docs__create_doc"))
        self.assertTrue(_tool_modifies_wecom_target("wecom_docs__smartsheet_add_records"))
        self.assertTrue(_tool_modifies_wecom_target("doc__append_section"))
        self.assertFalse(_tool_modifies_wecom_target("wecom_docs__smartsheet_get_fields"))
        self.assertFalse(_tool_modifies_wecom_target("doc__read_markdown"))


if __name__ == "__main__":
    unittest.main()
