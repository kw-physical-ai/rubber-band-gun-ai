#!/usr/bin/env python3
"""Validate one data-flow smoke bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_smoke_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_smoke_bundle(args.bundle), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
