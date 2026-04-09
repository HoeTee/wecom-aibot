from __future__ import annotations

from typing import Any

from backend.runtime import async_dispatch_cli_action
from backend.tools.doc_cli import (
    append_section,
    build_section_block,
    choose_relevant_section,
    insert_after_section,
    load_system_prompt,
    parse_markdown_sections,
    replace_section,
    section_preview,
)


async def read_document_markdown(
    host: Any,
    *,
    doc_id: str | None = None,
    doc_url: str | None = None,
    poll_interval_seconds: float = 1.0,
    max_polls: int = 8,
) -> str:
    result = await async_dispatch_cli_action(
        "doc.read",
        host=host,
        doc_id=doc_id,
        doc_url=doc_url,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
    )
    return str(result.get("markdown") or "")


async def create_document(host: Any, doc_name: str) -> dict[str, Any]:
    return await async_dispatch_cli_action("doc.create", host=host, doc_name=doc_name)


async def write_document_markdown(
    host: Any,
    *,
    doc_id: str,
    content: str,
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "doc.write",
        host=host,
        doc_id=doc_id,
        content=content,
    )


async def append_document_section(
    host: Any,
    *,
    doc_id: str,
    doc_url: str | None = None,
    title: str,
    body: str,
    location_mode: str = "append_end",
    query: str | None = None,
    level: int = 2,
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "doc.append",
        host=host,
        doc_id=doc_id,
        doc_url=doc_url,
        title=title,
        body=body,
        location_mode=location_mode,
        query=query,
        level=level,
    )


async def preview_document_replace(
    host: Any,
    *,
    doc_id: str,
    doc_url: str | None = None,
    scope_hint: str,
    source_hint: str,
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "doc.preview_replace",
        host=host,
        doc_id=doc_id,
        doc_url=doc_url,
        scope_hint=scope_hint,
        source_hint=source_hint,
    )


async def replace_document_section(
    host: Any,
    *,
    doc_id: str,
    doc_url: str | None = None,
    title: str,
    body: str,
    section_payload: dict[str, Any] | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "doc.replace",
        host=host,
        doc_id=doc_id,
        doc_url=doc_url,
        title=title,
        body=body,
        section_payload=section_payload,
        query=query,
    )


async def expand_document_section(
    host: Any,
    *,
    doc_id: str,
    doc_url: str | None = None,
    title: str,
    body: str,
    query: str | None = None,
    new_section_title: str | None = None,
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "doc.expand",
        host=host,
        doc_id=doc_id,
        doc_url=doc_url,
        title=title,
        body=body,
        query=query,
        new_section_title=new_section_title,
    )


# compatibility exports
get_doc_markdown = read_document_markdown
overwrite_document_markdown = write_document_markdown
