#!/usr/bin/env python3
"""Verify a promoted model artifact and its manifest."""

import argparse
import json
from pathlib import Path

from rubber_band_gun import verify_model_manifest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("manifest", type=Path)
args = parser.parse_args()
print(json.dumps(verify_model_manifest(args.manifest), ensure_ascii=False, indent=2))
