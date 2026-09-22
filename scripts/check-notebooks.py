#!/usr/bin/env python3
"""Validate committed notebooks without starting a Jupyter runtime."""

from __future__ import annotations

import json
from pathlib import Path


def validate_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4:
        raise ValueError(f"unsupported nbformat: {path}")

    for index, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            raise ValueError(f"saved output: {path}, cell {index}")
        if cell.get("execution_count") is not None:
            raise ValueError(f"saved execution count: {path}, cell {index}")


def main() -> None:
    paths = sorted(Path("notebooks").glob("*.ipynb"))
    if not paths:
        raise ValueError("no notebooks found")
    for path in paths:
        validate_notebook(path)
        print(f"validated: {path}")


if __name__ == "__main__":
    main()
