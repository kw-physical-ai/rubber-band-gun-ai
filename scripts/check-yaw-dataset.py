#!/usr/bin/env python3
"""Validate one immutable yaw dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_yaw_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_yaw_dataset(args.dataset), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
