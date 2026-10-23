#!/usr/bin/env python3
"""Verify one immutable recorded-frame baseline run."""

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_baseline_run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run", type=Path)
args = parser.parse_args()
print(json.dumps(verify_baseline_run(args.run), ensure_ascii=False, indent=2))
