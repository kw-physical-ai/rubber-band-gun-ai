#!/usr/bin/env python3
"""Safely inspect course model archives without executing their pickle payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import pickletools
import zipfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pickle_payload(path: Path) -> bytes:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"not a PyTorch zip archive: {path}")
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.endswith("/data.pkl")]
        if len(candidates) != 1:
            raise ValueError(f"expected one data.pkl in {path}, found {len(candidates)}")
        return archive.read(candidates[0])


def _strings_and_scalars(payload: bytes) -> tuple[set[str], dict[str, Any]]:
    operations = list(pickletools.genops(payload))
    strings = {
        argument
        for opcode, argument, _ in operations
        if opcode.name in {"SHORT_BINUNICODE", "BINUNICODE", "UNICODE"}
        and isinstance(argument, str)
    }
    scalars: dict[str, Any] = {}
    for index, (opcode, argument, _) in enumerate(operations):
        if opcode.name not in {"SHORT_BINUNICODE", "BINUNICODE", "UNICODE"}:
            continue
        if not isinstance(argument, str):
            continue
        for next_opcode, next_argument, _ in operations[index + 1 : index + 5]:
            if next_opcode.name in {"BININT", "BININT1", "BININT2", "BINFLOAT", "INT", "FLOAT"}:
                scalars[argument] = next_argument
                break
            if next_opcode.name in {"SHORT_BINUNICODE", "BINUNICODE", "UNICODE"}:
                break
    return strings, scalars


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yolo", type=Path, required=True)
    parser.add_argument("--yaw", type=Path, required=True)
    args = parser.parse_args()
    yaw_strings, yaw_scalars = _strings_and_scalars(_pickle_payload(args.yaw))
    required_yaw = {"model_state_dict", "image_size", "yaw_min", "yaw_max"}
    if not required_yaw <= yaw_strings:
        raise ValueError(f"yaw checkpoint metadata missing: {sorted(required_yaw - yaw_strings)}")
    yolo_strings, _ = _strings_and_scalars(_pickle_payload(args.yolo))
    if "model" not in yolo_strings or "names" not in yolo_strings:
        raise ValueError("YOLO archive does not expose model and names metadata")
    if not any(value.startswith("ultralytics.") for value in yolo_strings):
        raise ValueError("YOLO archive does not identify an Ultralytics model")
    report = {
        "schema_version": "rbg-reference-model-inspection/v1",
        "yaw": {
            "path": str(args.yaw.resolve()),
            "sha256": _sha256(args.yaw),
            "image_size": yaw_scalars.get("image_size"),
            "yaw_min": yaw_scalars.get("yaw_min"),
            "yaw_max": yaw_scalars.get("yaw_max"),
        },
        "yolo": {
            "path": str(args.yolo.resolve()),
            "sha256": _sha256(args.yolo),
            "format": "ultralytics-pytorch-archive",
        },
        "status": "structure-passed-runtime-load-not-executed",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
