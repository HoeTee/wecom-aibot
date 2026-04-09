from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from backend.runtime import MCPHost


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "system" / "assistant_v1.md"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def load_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _find_tool_name(host: MCPHost, *suffixes: str) -> str:
    available = [tool["function"]["name"] for tool in host.tools]
    lower_available = {name.lower(): name for name in available}
    for suffix in suffixes:
        suffix_lower = suffix.lower()
        for lower_name, original_name in lower_available.items():
            if lower_name.endswith(suffix_lower):
                return original_name
    raise KeyError(f"Missing required MCP tool. Expected one of: {suffixes}")


def _parse_json_payload(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return {}
        return {}


async def get_doc_markdown(
    host: MCPHost,
    *,
    doc_id: str | None = None,
    doc_url: str | None = None,
    poll_interval_seconds: float = 1.0,
    max_polls: int = 8,
) -> str:
    tool_name = _find_tool_name(host, "get_doc_content")
    args: dict[str, Any] = {"type": 2}
    if doc_id:
        args["docid"] = doc_id
    elif doc_url:
        args["url"] = doc_url
    else:
        raise ValueError("doc_id or doc_url is required")

    task_id: str | None = None
    for _ in range(max_polls):
        if task_id:
            args["task_id"] = task_id
        payload = _parse_json_payload(await host.call_tool(tool_name, args))
        task_done = payload.get("task_done")
        if task_done is True:
            content = payload.get("content") or payload.get("markdown") or payload.get("doc_content")
            if isinstance(content, str):
                return content
            return str(content or "").strip()
        task_id = str(payload.get("task_id") or "").strip() or task_id
        if not task_id:
            break
        await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError("Failed to fetch document markdown content")


async def create_document(host: MCPHost, doc_name: str) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "create_doc")
    payload = _parse_json_payload(
        await host.call_tool(
            tool_name,
            {"doc_type": 3, "doc_name": doc_name},
        )
    )
    return payload


async def overwrite_document_markdown(
    host: MCPHost,
    *,
    doc_id: str,
    content: str,
) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "edit_doc_content")
    payload = _parse_json_payload(
        await host.call_tool(
            tool_name,
            {"docid": doc_id, "content": content, "content_type": 1},
        )
    )
    return payload


def parse_markdown_sections(markdown: str) -> list[dict[str, Any]]:
    text = str(markdown or "")
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return []

    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        start = match.start()
        body_start = match.end()
        end = len(text)
        for next_match in matches[index + 1 :]:
            next_level = len(next_match.group(1))
            if next_level <= level:
                end = next_match.start()
                break
        sections.append(
            {
                "index": index,
                "level": level,
                "title": title,
                "start": start,
                "body_start": body_start,
                "end": end,
                "markdown": text[start:end].strip(),
                "body": text[body_start:end].strip(),
            }
        )
    return sections


def choose_relevant_section(markdown: str, query: str) -> dict[str, Any] | None:
    def tokenize(value: str) -> set[str]:
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", str(value or "").lower()).strip()
        return {token for token in cleaned.split() if token}

    sections = parse_markdown_sections(markdown)
    if not sections:
        return None

    query_tokens = tokenize(query)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for section in sections:
        title_tokens = tokenize(section["title"])
        body_tokens = tokenize(section["body"][:400])
        score = 0
        score += 20 * len(query_tokens & title_tokens)
        score += 5 * len(query_tokens & body_tokens)
        if score <= 0:
            continue
        scored.append((score, section["index"], section))

    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]
    return sections[0]


def append_section(markdown: str, title: str, body: str, *, level: int = 2) -> str:
    text = str(markdown or "").rstrip()
    section_block = f"\n\n{'#' * level} {title}\n\n{body.strip()}\n"
    return text + section_block if text else f"{'#' * level} {title}\n\n{body.strip()}\n"


def insert_after_section(markdown: str, section: dict[str, Any], content_block: str) -> str:
    text = str(markdown or "")
    insertion = f"\n\n{content_block.strip()}\n"
    return text[: section["end"]].rstrip() + insertion + text[section["end"] :]


def replace_section(markdown: str, section: dict[str, Any], content_block: str) -> str:
    text = str(markdown or "")
    return text[: section["start"]].rstrip() + "\n\n" + content_block.strip() + "\n" + text[section["end"] :]


def build_section_block(title: str, body: str, *, level: int = 2) -> str:
    return f"{'#' * level} {title}\n\n{body.strip()}"


def section_preview(section: dict[str, Any], *, max_chars: int = 300) -> str:
    snippet = str(section.get("markdown") or "").strip()
    if len(snippet) <= max_chars:
        return snippet
    return snippet[: max_chars - 3] + "..."
