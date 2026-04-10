from __future__ import annotations

from typing import Any

from backend.runtime import async_dispatch_cli_action


async def create_smartsheet(host: Any, doc_name: str) -> dict[str, Any]:
    return await async_dispatch_cli_action("smartsheet.create", host=host, doc_name=doc_name)


async def get_smartsheet_sheets(host: Any, *, doc_id: str) -> dict[str, Any]:
    return await async_dispatch_cli_action("smartsheet.get_sheets", host=host, doc_id=doc_id)


async def add_smartsheet_sheet(host: Any, *, doc_id: str, title: str) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "smartsheet.add_sheet",
        host=host,
        doc_id=doc_id,
        title=title,
    )


async def add_smartsheet_fields(
    host: Any,
    *,
    doc_id: str,
    sheet_id: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "smartsheet.add_fields",
        host=host,
        doc_id=doc_id,
        sheet_id=sheet_id,
        fields=fields,
    )


async def add_smartsheet_records(
    host: Any,
    *,
    doc_id: str,
    sheet_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return await async_dispatch_cli_action(
        "smartsheet.add_records",
        host=host,
        doc_id=doc_id,
        sheet_id=sheet_id,
        records=records,
    )
