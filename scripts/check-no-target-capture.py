#!/usr/bin/env python3
"""Verify an immutable no-target evaluation capture."""

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_no_target_bundle

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("bundle", type=Path)
args = parser.parse_args()
report = verify_no_target_bundle(args.bundle)
report["image_paths"] = [str(path) for path in report["image_paths"]]
print(json.dumps(report, ensure_ascii=False, indent=2))
