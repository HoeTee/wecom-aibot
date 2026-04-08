from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


LAYER_DEFINITIONS = [
    ("orchestration", ("backend.app", "backend.agent")),
    ("policy_state", ("backend.memory",)),
    ("tool_runtime", ("backend.mcp_client",)),
    ("tool_implementation", ("backend.mcp_server_local",)),
    ("eval", ("evals",)),
]

LAYER_ORDER = {
    "orchestration": 1,
    "policy_state": 2,
    "tool_runtime": 3,
    "tool_implementation": 4,
    "eval": 5,
}


def _module_name_for_path(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(relative.parts)


def _layer_for_module(module_name: str) -> str | None:
    for layer_name, prefixes in LAYER_DEFINITIONS:
        if any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in prefixes):
            return layer_name
    return None


def _iter_python_files() -> list[Path]:
    return sorted(
        path
        for root in (PROJECT_ROOT / "backend", PROJECT_ROOT / "evals")
        if root.exists()
        for path in root.rglob("*.py")
    )


def _extract_imports(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module_name = _module_name_for_path(path)
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is not None:
                base_parts = module_name.split(".")[:-node.level]
                imported = ".".join(base_parts + node.module.split("."))
                imports.append(imported)
            elif node.level and node.module is None:
                base_parts = module_name.split(".")[:-node.level]
                if base_parts:
                    imports.append(".".join(base_parts))
            elif node.module:
                imports.append(node.module)

    return imports


def _suggested_refactor_for_rule(rule_id: str) -> dict[str, Any]:
    mapping = {
        "lower_layer_imports_higher_layer": {
            "primary": {"layer": "policy_state", "directory": "backend/policies/"},
            "secondary": {"layer": "capability_api", "directory": "backend/capabilities/"},
        },
        "production_imports_eval": {
            "primary": {"layer": "eval", "directory": "evals/"},
            "secondary": {"layer": "architecture_docs", "directory": "docs/"},
        },
        "orchestration_imports_tool_implementation": {
            "primary": {"layer": "tool_runtime", "directory": "backend/mcp_client/"},
            "secondary": {"layer": "capability_api", "directory": "backend/capabilities/"},
        },
    }
    return mapping.get(
        rule_id,
        {
            "primary": {"layer": "policy_state", "directory": "backend/policies/"},
            "secondary": {"layer": "capability_api", "directory": "backend/capabilities/"},
        },
    )


def run_layer_checks(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or PROJECT_ROOT
    violations: list[dict[str, Any]] = []

    for path in _iter_python_files():
        source_module = _module_name_for_path(path)
        source_layer = _layer_for_module(source_module)
        if source_layer is None:
            continue

        for imported_module in _extract_imports(path):
            target_layer = _layer_for_module(imported_module)
            if target_layer is None:
                continue

            rule_id: str | None = None
            violated_rule: str | None = None

            if source_layer != "eval" and target_layer == "eval":
                rule_id = "production_imports_eval"
                violated_rule = "生产代码不能依赖 eval 层。"
            elif source_layer == "orchestration" and target_layer == "tool_implementation":
                rule_id = "orchestration_imports_tool_implementation"
                violated_rule = "Orchestration 层不能直接依赖 Tool Implementation 层。"
            elif LAYER_ORDER[source_layer] > LAYER_ORDER[target_layer]:
                rule_id = "lower_layer_imports_higher_layer"
                violated_rule = "下层不能反向依赖上层。"

            if not rule_id:
                continue

            violations.append(
                {
                    "rule_id": rule_id,
                    "violated_rule": violated_rule,
                    "source_file": str(path.relative_to(root)).replace("\\", "/"),
                    "target_module": imported_module,
                    "source_layer": source_layer,
                    "target_layer": target_layer,
                    "suggested_refactor_target": _suggested_refactor_for_rule(rule_id),
                }
            )

    return {
        "passed": not violations,
        "violations": violations,
    }


def main() -> None:
    result = run_layer_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
