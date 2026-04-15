from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


LAYER_DEFINITIONS = [
    ("entry", ("backend.app", "backend.entry")),
    ("flow", ("backend.agent", "backend.flow")),
    ("policy", ("backend.policy",)),
    ("state", ("backend.memory", "backend.state")),
    ("caps", ("backend.caps",)),
    ("runtime", ("backend.runtime",)),
    ("tools", ("backend.tools",)),
]

LAYER_ORDER = {
    "entry": 1,
    "flow": 2,
    "policy": 3,
    "state": 4,
    "caps": 5,
    "runtime": 6,
    "tools": 7,
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
    roots = [PROJECT_ROOT / "backend"]
    return sorted(path for root in roots if root.exists() for path in root.rglob("*.py"))


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
            "primary": {"layer": "policy", "directory": "backend/policy/"},
            "secondary": {"layer": "caps", "directory": "backend/caps/"},
        },
        "flow_imports_tools_directly": {
            "primary": {"layer": "runtime", "directory": "backend/runtime/"},
            "secondary": {"layer": "caps", "directory": "backend/caps/"},
        },
        "mcp_wrapper_missing_entrypoint": {
            "primary": {"layer": "tools", "directory": "backend/tools/"},
            "secondary": {"layer": "runtime", "directory": "backend/runtime/"},
        },
    }
    return mapping.get(
        rule_id,
        {
            "primary": {"layer": "policy", "directory": "backend/policy/"},
            "secondary": {"layer": "caps", "directory": "backend/caps/"},
        },
    )


def _iter_stdio_wrapper_files() -> list[Path]:
    wrapper_root = PROJECT_ROOT / "backend" / "tools"
    if not wrapper_root.exists():
        return []
    return sorted(path for path in wrapper_root.rglob("mcp_*.py"))


def _has_stdio_entrypoint(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                return True

    return False


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

            if source_layer == "flow" and target_layer == "tools":
                rule_id = "flow_imports_tools_directly"
                violated_rule = "flow 层不能直接依赖 tools 层。"
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

    for path in _iter_stdio_wrapper_files():
        if _has_stdio_entrypoint(path):
            continue
        violations.append(
            {
                "rule_id": "mcp_wrapper_missing_entrypoint",
                "violated_rule": "stdio MCP wrapper 必须在 __main__ 中显式启动 server.run(...)。",
                "source_file": str(path.relative_to(root)).replace("\\", "/"),
                "target_module": "",
                "source_layer": "tools",
                "target_layer": "tools",
                "suggested_refactor_target": _suggested_refactor_for_rule(
                    "mcp_wrapper_missing_entrypoint"
                ),
            }
        )

    return {"passed": not violations, "violations": violations}


def main() -> None:
    result = run_layer_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
