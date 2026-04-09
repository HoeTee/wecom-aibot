from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.tools.doc_cli import execute_doc_action
from backend.tools.kb_cli import execute_kb_action
from backend.tools.rag_cli import execute_rag_action
from backend.tools.smartsheet_cli import execute_smartsheet_action


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "data" / "logs" / "cli"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "cli_runtime.log"


logger = logging.getLogger("CLIRuntime")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)


def _safe_summary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {key: _safe_summary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_summary(item) for item in value[:5]]
    return value


def dispatch_cli_action(action: str, **kwargs: Any) -> dict[str, Any]:
    params_summary = _safe_summary(kwargs)
    logger.info(
        "dispatch action=%s params=%s",
        action,
        json.dumps(params_summary, ensure_ascii=False, sort_keys=True),
    )

    try:
        if action.startswith("kb."):
            result = execute_kb_action(action, **kwargs)
        else:
            raise KeyError(f"Unknown CLI action: {action}")
    except Exception as exc:
        logger.exception("action failed action=%s error=%s", action, exc)
        raise

    result_summary = _safe_summary(result)
    logger.info(
        "dispatch_result action=%s result=%s",
        action,
        json.dumps(result_summary, ensure_ascii=False, sort_keys=True),
    )
    return result


async def async_dispatch_cli_action(action: str, **kwargs: Any) -> dict[str, Any]:
    params_summary = _safe_summary(kwargs)
    logger.info(
        "async_dispatch action=%s params=%s",
        action,
        json.dumps(params_summary, ensure_ascii=False, sort_keys=True),
    )

    try:
        if action.startswith("kb."):
            result = execute_kb_action(action, **kwargs)
        elif action.startswith("doc."):
            result = await execute_doc_action(action, **kwargs)
        elif action.startswith("smartsheet."):
            result = await execute_smartsheet_action(action, **kwargs)
        elif action.startswith("rag."):
            result = await execute_rag_action(action, **kwargs)
        else:
            raise KeyError(f"Unknown CLI action: {action}")
    except Exception as exc:
        logger.exception("async action failed action=%s error=%s", action, exc)
        raise

    result_summary = _safe_summary(result)
    logger.info(
        "async_dispatch_result action=%s result=%s",
        action,
        json.dumps(result_summary, ensure_ascii=False, sort_keys=True),
    )
    return result
