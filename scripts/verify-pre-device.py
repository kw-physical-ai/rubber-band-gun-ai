#!/usr/bin/env python3
"""Run the complete hardware-independent gate used locally and in CI."""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    commands = (
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"],
        [sys.executable, "scripts/check-notebooks.py"],
        [sys.executable, "scripts/check-repository.py"],
    )
    for command in commands:
        print(f"+ {' '.join(command)}", flush=True)
        subprocess.run(command, check=True)
    print("pre-device gate passed")


if __name__ == "__main__":
    main()
