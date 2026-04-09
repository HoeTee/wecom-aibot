from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "system" / "assistant_v1.md"


def load_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
