from __future__ import annotations

import copy
import json
from typing import Any

from .cli import async_dispatch_cli_action
from backend.tools.llamaindex_rag.runtime import (
    LOCAL_RAG_SEARCH_TOOL,
    is_rag_tool_name,
    rag_action_for_tool_name,
)
from backend.tools.rag_cli import execute_rag_action


KB_LIST_FILES_TOOL_NAME = "kb__list_files"
KB_LIST_UPLOADS_TOOL_NAME = "kb__list_recent_uploads"
KB_MATCH_RELATED_TOOL_NAME = "kb__match_related_files"
KB_EXPORT_FILE_TOOL_NAME = "kb__export_file"
KB_RENAME_FILE_TOOL_NAME = "kb__rename_file"
KB_DELETE_FILE_TOOL_NAME = "kb__delete_file"
AGENT_NO_TOOL_NEEDED_TOOL_NAME = "agent__no_tool_needed"

DOC_READ_MARKDOWN_TOOL_NAME = "doc__read_markdown"
DOC_APPEND_SECTION_TOOL_NAME = "doc__append_section"
DOC_PREVIEW_REPLACE_TOOL_NAME = "doc__preview_replace"
DOC_REPLACE_SECTION_TOOL_NAME = "doc__replace_section"
DOC_EXPAND_SECTION_TOOL_NAME = "doc__expand_section"


AGENT_NO_TOOL_NEEDED_TOOL = {
    "type": "function",
    "function": {
        "name": AGENT_NO_TOOL_NEEDED_TOOL_NAME,
        "description": (
            "Use this only when no available tool is relevant and the user can be answered safely without external state or side effects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short explanation of why no tool is needed.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}

KB_LIST_FILES_TOOL = {
    "type": "function",
    "function": {
        "name": KB_LIST_FILES_TOOL_NAME,
        "description": (
            "List PDF files from the local knowledge base. "
            "Use this for requests like listing files, counting files, or understanding what PDFs exist "
            "before export, rename, delete, or related-file lookup."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Optional compatibility field. Ignored; all PDFs in the knowledge base are listed.",
                }
            },
            "additionalProperties": False,
        },
    },
}

KB_LIST_UPLOADS_TOOL = {
    "type": "function",
    "function": {
        "name": KB_LIST_UPLOADS_TOOL_NAME,
        "description": "Compatibility tool for listing recently added PDF files from the local knowledge base.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent uploads to return.",
                }
            },
            "additionalProperties": False,
        },
    },
}

KB_MATCH_RELATED_TOOL = {
    "type": "function",
    "function": {
        "name": KB_MATCH_RELATED_TOOL_NAME,
        "description": (
            "Find the most relevant PDF files in the local knowledge base by file name and metadata. "
            "Use this before export, rename, delete, or when the user asks which file is most related."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's file lookup request or keywords.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate files to return.",
                },
                "scope": {
                    "type": "string",
                    "description": "Optional compatibility field. Ignored; matching searches the whole knowledge base.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

KB_EXPORT_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": KB_EXPORT_FILE_TOOL_NAME,
        "description": (
            "Export the original PDF file from the local knowledge base and prepare it as a reply attachment. "
            "Use this when the user explicitly wants the original file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Exact display file name when known.",
                },
                "stored_path": {
                    "type": "string",
                    "description": "Stored project-relative path when available from a previous listing result.",
                },
            },
            "additionalProperties": False,
        },
    },
}

KB_RENAME_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": KB_RENAME_FILE_TOOL_NAME,
        "description": (
            "Rename a PDF file in the local knowledge base. "
            "Ask for explicit user confirmation first, then call this tool with confirmed=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Exact display file name when known.",
                },
                "stored_path": {
                    "type": "string",
                    "description": "Stored project-relative path when available from a previous listing result.",
                },
                "new_file_name": {
                    "type": "string",
                    "description": "The new PDF file name to apply.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true only after the user has explicitly confirmed the rename.",
                },
            },
            "required": ["new_file_name", "confirmed"],
            "additionalProperties": False,
        },
    },
}

KB_DELETE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": KB_DELETE_FILE_TOOL_NAME,
        "description": (
            "Delete a PDF file from the local knowledge base. "
            "Ask for explicit user confirmation first, then call this tool with confirmed=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Exact display file name when known.",
                },
                "stored_path": {
                    "type": "string",
                    "description": "Stored project-relative path when available from a previous listing result.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true only after the user has explicitly confirmed the deletion.",
                },
            },
            "required": ["confirmed"],
            "additionalProperties": False,
        },
    },
}

DOC_READ_MARKDOWN_TOOL = {
    "type": "function",
    "function": {
        "name": DOC_READ_MARKDOWN_TOOL_NAME,
        "description": (
            "Read a WeCom document or smart sheet document as Markdown. "
            "Use this when you need the current content before editing or summarizing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "The WeCom doc_id when available."},
                "doc_url": {"type": "string", "description": "The WeCom document URL when doc_id is not available."},
            },
            "additionalProperties": False,
        },
    },
}

DOC_APPEND_SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": DOC_APPEND_SECTION_TOOL_NAME,
        "description": (
            "Append a structured Markdown section into an existing WeCom document. "
            "Use this for adding a new section at the end, creating a new section, or inserting after the most relevant section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "doc_url": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "location_mode": {
                    "type": "string",
                    "enum": ["append_end", "new_section", "relevant_section"],
                },
                "query": {"type": "string"},
                "level": {"type": "integer"},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
    },
}

DOC_PREVIEW_REPLACE_TOOL = {
    "type": "function",
    "function": {
        "name": DOC_PREVIEW_REPLACE_TOOL_NAME,
        "description": (
            "Preview which Markdown section in the current WeCom document looks most relevant for replacement. "
            "Use this before replacing an existing section with new content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "doc_url": {"type": "string"},
                "scope_hint": {"type": "string"},
                "source_hint": {"type": "string"},
            },
            "required": ["scope_hint", "source_hint"],
            "additionalProperties": False,
        },
    },
}

DOC_REPLACE_SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": DOC_REPLACE_SECTION_TOOL_NAME,
        "description": "Replace the most relevant Markdown section in an existing WeCom document with new content.",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "doc_url": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "query": {"type": "string"},
                "section_payload": {"type": "object"},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
    },
}

DOC_EXPAND_SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": DOC_EXPAND_SECTION_TOOL_NAME,
        "description": "Expand an existing WeCom document by inserting a new Markdown subsection or a new top-level section.",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "doc_url": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "query": {"type": "string"},
                "new_section_title": {"type": "string"},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
    },
}


_LOCAL_TOOL_NAMES = {
    AGENT_NO_TOOL_NEEDED_TOOL_NAME,
    KB_LIST_FILES_TOOL_NAME,
    KB_MATCH_RELATED_TOOL_NAME,
    KB_EXPORT_FILE_TOOL_NAME,
    KB_RENAME_FILE_TOOL_NAME,
    KB_DELETE_FILE_TOOL_NAME,
    DOC_READ_MARKDOWN_TOOL_NAME,
    DOC_APPEND_SECTION_TOOL_NAME,
    DOC_PREVIEW_REPLACE_TOOL_NAME,
    DOC_REPLACE_SECTION_TOOL_NAME,
    DOC_EXPAND_SECTION_TOOL_NAME,
    LOCAL_RAG_SEARCH_TOOL["function"]["name"],
}


def get_local_agent_tools() -> list[dict[str, object]]:
    return [
        copy.deepcopy(AGENT_NO_TOOL_NEEDED_TOOL),
        copy.deepcopy(KB_LIST_FILES_TOOL),
        copy.deepcopy(KB_MATCH_RELATED_TOOL),
        copy.deepcopy(KB_EXPORT_FILE_TOOL),
        copy.deepcopy(KB_RENAME_FILE_TOOL),
        copy.deepcopy(KB_DELETE_FILE_TOOL),
        copy.deepcopy(DOC_READ_MARKDOWN_TOOL),
        copy.deepcopy(DOC_APPEND_SECTION_TOOL),
        copy.deepcopy(DOC_PREVIEW_REPLACE_TOOL),
        copy.deepcopy(DOC_REPLACE_SECTION_TOOL),
        copy.deepcopy(DOC_EXPAND_SECTION_TOOL),
        copy.deepcopy(LOCAL_RAG_SEARCH_TOOL),
    ]


def is_local_agent_tool_name(function_name: str) -> bool:
    return str(function_name or "").strip() in _LOCAL_TOOL_NAMES


def _require_doc_target(args_dict: dict[str, Any]) -> None:
    if str(args_dict.get("doc_id") or "").strip():
        return
    if str(args_dict.get("doc_url") or "").strip():
        return
    raise ValueError("doc tool requires doc_id or doc_url")


def _require_kb_target(args_dict: dict[str, Any]) -> None:
    if str(args_dict.get("file_name") or "").strip():
        return
    if str(args_dict.get("stored_path") or "").strip():
        return
    raise ValueError("knowledge-base tool requires file_name or stored_path")


async def execute_local_agent_tool(
    function_name: str,
    args_dict: dict[str, Any],
    *,
    host: Any | None,
) -> dict[str, Any]:
    name = str(function_name or "").strip()

    if is_rag_tool_name(name):
        rag_action = rag_action_for_tool_name(name)
        if not rag_action:
            raise KeyError(f"Unknown local rag tool: {name}")
        payload = await execute_rag_action(rag_action, query=args_dict.get("query"))
        return {
            "content": payload.get("text") or "",
            "attachment": None,
        }

    if name == AGENT_NO_TOOL_NEEDED_TOOL_NAME:
        reason = str(args_dict.get("reason") or "").strip()
        if not reason:
            raise ValueError("agent no-tool decision requires reason")
        return {"content": f"No tool needed: {reason}", "attachment": None}

    if name == KB_LIST_FILES_TOOL_NAME:
        payload = await async_dispatch_cli_action("kb.list", scope="all")
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == KB_LIST_UPLOADS_TOOL_NAME:
        payload = await async_dispatch_cli_action("kb.list_uploads", limit=int(args_dict.get("limit") or 5))
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == KB_MATCH_RELATED_TOOL_NAME:
        query = str(args_dict.get("query") or "").strip()
        if not query:
            raise ValueError("kb related lookup requires query")
        payload = await async_dispatch_cli_action(
            "kb.match_related",
            query=query,
            limit=int(args_dict.get("limit") or 10),
            scope="all",
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == KB_EXPORT_FILE_TOOL_NAME:
        _require_kb_target(args_dict)
        payload = await async_dispatch_cli_action(
            "kb.export",
            file_name=args_dict.get("file_name"),
            stored_path=args_dict.get("stored_path"),
        )
        return {
            "content": json.dumps(payload, ensure_ascii=False),
            "attachment": {
                "type": "file",
                "path": str(payload["path"]),
                "name": str(payload["file_name"]),
            },
        }

    if name == KB_RENAME_FILE_TOOL_NAME:
        _require_kb_target(args_dict)
        if args_dict.get("confirmed") is not True:
            raise ValueError("kb rename requires confirmed=true after explicit user confirmation")
        payload = await async_dispatch_cli_action(
            "kb.rename",
            file_name=args_dict.get("file_name"),
            stored_path=args_dict.get("stored_path"),
            new_file_name=str(args_dict.get("new_file_name") or "").strip(),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == KB_DELETE_FILE_TOOL_NAME:
        _require_kb_target(args_dict)
        if args_dict.get("confirmed") is not True:
            raise ValueError("kb delete requires confirmed=true after explicit user confirmation")
        payload = await async_dispatch_cli_action(
            "kb.delete",
            file_name=args_dict.get("file_name"),
            stored_path=args_dict.get("stored_path"),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if host is None:
        raise ValueError(f"local doc tool '{name}' requires MCP host")

    if name == DOC_READ_MARKDOWN_TOOL_NAME:
        _require_doc_target(args_dict)
        payload = await async_dispatch_cli_action(
            "doc.read",
            host=host,
            doc_id=args_dict.get("doc_id"),
            doc_url=args_dict.get("doc_url"),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == DOC_APPEND_SECTION_TOOL_NAME:
        _require_doc_target(args_dict)
        payload = await async_dispatch_cli_action(
            "doc.append",
            host=host,
            doc_id=str(args_dict.get("doc_id") or ""),
            doc_url=args_dict.get("doc_url"),
            title=str(args_dict.get("title") or ""),
            body=str(args_dict.get("body") or ""),
            location_mode=str(args_dict.get("location_mode") or "append_end"),
            query=args_dict.get("query"),
            level=int(args_dict.get("level") or 2),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == DOC_PREVIEW_REPLACE_TOOL_NAME:
        _require_doc_target(args_dict)
        payload = await async_dispatch_cli_action(
            "doc.preview_replace",
            host=host,
            doc_id=str(args_dict.get("doc_id") or ""),
            doc_url=args_dict.get("doc_url"),
            scope_hint=str(args_dict.get("scope_hint") or ""),
            source_hint=str(args_dict.get("source_hint") or ""),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == DOC_REPLACE_SECTION_TOOL_NAME:
        _require_doc_target(args_dict)
        payload = await async_dispatch_cli_action(
            "doc.replace",
            host=host,
            doc_id=str(args_dict.get("doc_id") or ""),
            doc_url=args_dict.get("doc_url"),
            title=str(args_dict.get("title") or ""),
            body=str(args_dict.get("body") or ""),
            query=args_dict.get("query"),
            section_payload=args_dict.get("section_payload"),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    if name == DOC_EXPAND_SECTION_TOOL_NAME:
        _require_doc_target(args_dict)
        payload = await async_dispatch_cli_action(
            "doc.expand",
            host=host,
            doc_id=str(args_dict.get("doc_id") or ""),
            doc_url=args_dict.get("doc_url"),
            title=str(args_dict.get("title") or ""),
            body=str(args_dict.get("body") or ""),
            query=args_dict.get("query"),
            new_section_title=args_dict.get("new_section_title"),
        )
        return {"content": json.dumps(payload, ensure_ascii=False), "attachment": None}

    raise KeyError(f"Unknown local agent tool: {name}")
