#!/usr/bin/env python3
"""Validate one immutable yaw-capture bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_yaw_capture_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_yaw_capture_bundle(args.bundle), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
