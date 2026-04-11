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
    LOCAL_RAG_SUMMARIZE_TOOL_NAME,
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
        self.assertIn(LOCAL_RAG_SUMMARIZE_TOOL_NAME, tool_names)

    def test_local_rag_tools_include_search_and_summarize(self) -> None:
        tool_names = {tool["function"]["name"] for tool in get_local_rag_tools()}
        self.assertEqual(
            tool_names,
            {LOCAL_RAG_SEARCH_TOOL_NAME, LOCAL_RAG_SUMMARIZE_TOOL_NAME},
        )

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
