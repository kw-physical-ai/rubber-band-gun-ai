#!/usr/bin/env python3
"""Build one immutable yaw dataset from verified capture bundles."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from rubber_band_gun import build_yaw_dataset, verify_yaw_dataset


def _current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source-commit", default=None)
    for split in ("train", "validation", "locked-test"):
        parser.add_argument(f"--{split}", action="append", type=Path, default=[])
    args = parser.parse_args()

    completed = build_yaw_dataset(
        args.output_root,
        args.dataset_id,
        {
            "train": args.train,
            "validation": args.validation,
            "locked-test": args.locked_test,
        },
        source_commit=args.source_commit or _current_commit(),
    )
    print(json.dumps(verify_yaw_dataset(completed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
