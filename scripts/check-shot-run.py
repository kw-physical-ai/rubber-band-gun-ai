#!/usr/bin/env python3
"""Verify an immutable manually positioned evaluation run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rubber_band_gun import verify_shot_run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_shot_run(args.bundle), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
