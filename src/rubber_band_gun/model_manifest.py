"""Validation for promoted model manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evaluation import sha256_file
from .preprocessing import PreprocessingSpec

MODEL_MANIFEST_SCHEMA = "rbg-model-manifest/v1"
MODEL_ID_PATTERN = re.compile(r"model-[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


def verify_model_manifest(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != MODEL_MANIFEST_SCHEMA:
        raise ValueError(f"unsupported model manifest schema: {value.get('schema_version')}")
    model_id = value.get("model_id")
    if not isinstance(model_id, str) or not MODEL_ID_PATTERN.fullmatch(model_id):
        raise ValueError(f"invalid model ID: {model_id}")
    if value.get("model_kind") not in {"target-detector", "yaw-regressor"}:
        raise ValueError("model_kind must be target-detector or yaw-regressor")
    artifact_name = value.get("artifact")
    artifact = Path(artifact_name) if isinstance(artifact_name, str) else None
    if artifact is None or artifact.is_absolute() or len(artifact.parts) != 1:
        raise ValueError("artifact must be a file next to its manifest")
    artifact_path = path.parent / artifact
    if not artifact_path.is_file() or artifact_path.is_symlink():
        raise ValueError(f"model artifact is missing: {artifact_name}")
    expected_hash = value.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("model SHA-256 is invalid")
    if sha256_file(artifact_path) != expected_hash:
        raise ValueError("model artifact SHA-256 mismatch")
    source = value.get("source")
    if not isinstance(source, dict) or not str(source.get("run_id", "")).strip():
        raise ValueError("model source run_id is required")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("git_commit", ""))):
        raise ValueError("model source Git commit is invalid")
    PreprocessingSpec.from_mapping(value.get("preprocessing", {}))
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("model metrics are required")
    approval = value.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("model approval metadata is required")
    for key in ("approved_by", "approved_at_utc"):
        if not str(approval.get(key, "")).strip():
            raise ValueError(f"model approval {key} is required")
    return {
        "schema_version": "rbg-model-manifest-report/v1",
        "model_id": model_id,
        "model_kind": value["model_kind"],
        "artifact_sha256": expected_hash,
        "status": "passed",
    }
