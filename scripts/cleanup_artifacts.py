from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = [
    PROJECT_ROOT / "he" / "runs",
    PROJECT_ROOT / "he" / "reports",
    PROJECT_ROOT / "data" / "logs",
]


def _clean_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def main() -> None:
    for target in TARGET_DIRS:
        _clean_directory(target)
    print("Cleaned HE runs/reports and runtime logs.")


if __name__ == "__main__":
    main()
