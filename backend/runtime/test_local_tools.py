from __future__ import annotations

import asyncio
import unittest

from backend.runtime.local_tools import (
    DOC_APPEND_SECTION_TOOL_NAME,
    DOC_READ_MARKDOWN_TOOL_NAME,
    KB_DELETE_FILE_TOOL_NAME,
    KB_EXPORT_FILE_TOOL_NAME,
    KB_LIST_FILES_TOOL_NAME,
    KB_MATCH_RELATED_TOOL_NAME,
    KB_RENAME_FILE_TOOL_NAME,
    execute_local_agent_tool,
    get_local_agent_tools,
)
from backend.tools.llamaindex_rag.runtime import (
    LOCAL_RAG_SEARCH_TOOL_NAME,
    get_local_rag_tools,
)


class LocalAgentToolsTests(unittest.TestCase):
    def test_local_agent_tools_expose_kb_doc_and_rag_families(self) -> None:
        tool_names = {tool["function"]["name"] for tool in get_local_agent_tools()}
        self.assertIn(KB_LIST_FILES_TOOL_NAME, tool_names)
        self.assertIn(KB_MATCH_RELATED_TOOL_NAME, tool_names)
        self.assertIn(KB_EXPORT_FILE_TOOL_NAME, tool_names)
        self.assertIn(DOC_READ_MARKDOWN_TOOL_NAME, tool_names)
        self.assertIn(DOC_APPEND_SECTION_TOOL_NAME, tool_names)
        self.assertIn(LOCAL_RAG_SEARCH_TOOL_NAME, tool_names)
        self.assertNotIn("kb__list_recent_uploads", tool_names)
        self.assertNotIn("llamaindex_rag__llamaindex_rag_summarize", tool_names)

    def test_local_rag_tools_only_expose_search(self) -> None:
        tool_names = {tool["function"]["name"] for tool in get_local_rag_tools()}
        self.assertEqual(tool_names, {LOCAL_RAG_SEARCH_TOOL_NAME})

    def test_kb_file_tools_do_not_expose_source_type_filters(self) -> None:
        tools = {tool["function"]["name"]: tool for tool in get_local_agent_tools()}
        export_props = tools[KB_EXPORT_FILE_TOOL_NAME]["function"]["parameters"]["properties"]
        rename_props = tools[KB_RENAME_FILE_TOOL_NAME]["function"]["parameters"]["properties"]
        delete_props = tools[KB_DELETE_FILE_TOOL_NAME]["function"]["parameters"]["properties"]
        self.assertNotIn("source_type", export_props)
        self.assertNotIn("source_type", rename_props)
        self.assertNotIn("source_type", delete_props)

    def test_rename_requires_confirmed_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmed=true"):
            asyncio.run(
                execute_local_agent_tool(
                    KB_RENAME_FILE_TOOL_NAME,
                    {
                        "file_name": "sample.pdf",
                        "new_file_name": "renamed.pdf",
                        "confirmed": False,
                    },
                    host=None,
                )
            )

    def test_delete_requires_confirmed_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmed=true"):
            asyncio.run(
                execute_local_agent_tool(
                    KB_DELETE_FILE_TOOL_NAME,
                    {
                        "file_name": "sample.pdf",
                        "confirmed": False,
                    },
                    host=None,
                )
            )


if __name__ == "__main__":
    unittest.main()
