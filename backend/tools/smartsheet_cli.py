from __future__ import annotations

import json
from typing import Any, Protocol


class SmartsheetHost(Protocol):
    tools: list[dict[str, Any]]

    async def call_tool(self, exposed_name: str, args: dict[str, Any]) -> str:
        ...


def _find_tool_name(host: SmartsheetHost, *suffixes: str) -> str:
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


def _build_result(action: str, tool_name: str, tool_args: dict[str, Any], raw_text: str) -> dict[str, Any]:
    payload = _parse_json_payload(raw_text)
    result = {
        "action": action,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result_raw": raw_text,
    }
    result.update(payload)
    return result


def _extract_doc_id(payload: dict[str, Any]) -> str | None:
    for key in ("docid", "doc_id", "docId"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("docid", "doc_id", "docId"):
            value = data.get(key)
            if value:
                return str(value).strip()
    return None


def _extract_doc_url(payload: dict[str, Any]) -> str | None:
    for key in ("url", "doc_url", "docUrl"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("url", "doc_url", "docUrl"):
            value = data.get(key)
            if value:
                return str(value).strip()
    return None


def _extract_sheet_id(payload: dict[str, Any]) -> str | None:
    for key in ("sheet_id", "sheetId"):
        value = payload.get(key)
        if value:
            return str(value).strip()

    sheets = payload.get("sheets")
    if isinstance(sheets, list) and sheets:
        first = sheets[0]
        if isinstance(first, dict):
            for key in ("sheet_id", "sheetId"):
                value = first.get(key)
                if value:
                    return str(value).strip()
            properties = first.get("properties")
            if isinstance(properties, dict):
                for key in ("sheet_id", "sheetId"):
                    value = properties.get(key)
                    if value:
                        return str(value).strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("sheet_id", "sheetId"):
            value = data.get(key)
            if value:
                return str(value).strip()
        nested_sheets = data.get("sheets")
        if isinstance(nested_sheets, list) and nested_sheets:
            first = nested_sheets[0]
            if isinstance(first, dict):
                for key in ("sheet_id", "sheetId"):
                    value = first.get(key)
                    if value:
                        return str(value).strip()
    return None


async def create_smartsheet(host: SmartsheetHost, doc_name: str) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "create_doc")
    tool_args = {"doc_type": 10, "doc_name": doc_name}
    result = _build_result(action="smartsheet.create", tool_name=tool_name, tool_args=tool_args, raw_text=await host.call_tool(tool_name, tool_args))
    result["doc_id"] = _extract_doc_id(result)
    result["doc_url"] = _extract_doc_url(result)
    result["doc_name"] = doc_name
    return result


async def get_smartsheet_sheets(host: SmartsheetHost, *, doc_id: str) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "smartsheet_get_sheet")
    tool_args = {"docid": doc_id}
    result = _build_result(action="smartsheet.get_sheets", tool_name=tool_name, tool_args=tool_args, raw_text=await host.call_tool(tool_name, tool_args))
    result["sheet_id"] = _extract_sheet_id(result)
    return result


async def add_smartsheet_sheet(host: SmartsheetHost, *, doc_id: str, title: str) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "smartsheet_add_sheet")
    tool_args = {"docid": doc_id, "properties": {"title": title}}
    result = _build_result(action="smartsheet.add_sheet", tool_name=tool_name, tool_args=tool_args, raw_text=await host.call_tool(tool_name, tool_args))
    result["sheet_id"] = _extract_sheet_id(result)
    return result


async def add_smartsheet_fields(
    host: SmartsheetHost,
    *,
    doc_id: str,
    sheet_id: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "smartsheet_add_fields")
    tool_args = {"docid": doc_id, "sheet_id": sheet_id, "fields": fields}
    return _build_result(action="smartsheet.add_fields", tool_name=tool_name, tool_args=tool_args, raw_text=await host.call_tool(tool_name, tool_args))


async def add_smartsheet_records(
    host: SmartsheetHost,
    *,
    doc_id: str,
    sheet_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_name = _find_tool_name(host, "smartsheet_add_records")
    tool_args = {"docid": doc_id, "sheet_id": sheet_id, "records": records}
    return _build_result(action="smartsheet.add_records", tool_name=tool_name, tool_args=tool_args, raw_text=await host.call_tool(tool_name, tool_args))


async def execute_smartsheet_action(action: str, **kwargs: Any) -> dict[str, Any]:
    host = kwargs.get("host")
    if host is None:
        raise ValueError("smartsheet actions require host")

    if action == "smartsheet.create":
        return await create_smartsheet(host, str(kwargs["doc_name"]))

    if action == "smartsheet.get_sheets":
        return await get_smartsheet_sheets(host, doc_id=str(kwargs["doc_id"]))

    if action == "smartsheet.add_sheet":
        return await add_smartsheet_sheet(host, doc_id=str(kwargs["doc_id"]), title=str(kwargs["title"]))

    if action == "smartsheet.add_fields":
        return await add_smartsheet_fields(
            host,
            doc_id=str(kwargs["doc_id"]),
            sheet_id=str(kwargs["sheet_id"]),
            fields=list(kwargs["fields"]),
        )

    if action == "smartsheet.add_records":
        return await add_smartsheet_records(
            host,
            doc_id=str(kwargs["doc_id"]),
            sheet_id=str(kwargs["sheet_id"]),
            records=list(kwargs["records"]),
        )

    raise KeyError(f"Unknown smartsheet action: {action}")
