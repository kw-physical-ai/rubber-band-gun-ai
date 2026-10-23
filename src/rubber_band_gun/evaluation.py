"""Actuator-free evaluation of recorded frames."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .dataset import DATASET_CSV_COLUMNS, SPLIT_NAMES, verify_yaw_dataset
from .environment import runtime_summary
from .preprocessing import PreprocessingSpec, prepare_model_rgb, resize_model_rgb

BASELINE_RUN_SCHEMA = "rbg-baseline-run/v1"
RUN_ID_PATTERN = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PREDICTION_COLUMNS = (
    "case_id",
    "source",
    "expected_target",
    "detected",
    "confidence",
    "box_x1",
    "box_y1",
    "box_x2",
    "box_y2",
    "expected_yaw_offset",
    "predicted_yaw_offset",
    "absolute_error",
    "matched_target",
)
TARGET_ANNOTATION_COLUMNS = (
    "case_id",
    "box_x1",
    "box_y1",
    "box_x2",
    "box_y2",
    "annotated_by",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]
    confidence: float

    def __post_init__(self) -> None:
        x1, y1, x2, y2 = self.box
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("detection box must have positive area and non-negative coordinates")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection confidence must be within 0..1")


class TargetDetector(Protocol):
    def detect(self, model_rgb: np.ndarray) -> Detection | None: ...


class YawRegressor(Protocol):
    def predict(self, mask: np.ndarray) -> float: ...


@dataclass(frozen=True)
class BaselineThresholds:
    target_recall_min: float
    no_target_false_positive_rate_max: float
    yaw_mae_max_degrees: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.target_recall_min <= 1.0:
            raise ValueError("target_recall_min must be within 0..1")
        if not 0.0 <= self.no_target_false_positive_rate_max <= 1.0:
            raise ValueError("no_target_false_positive_rate_max must be within 0..1")
        if self.yaw_mae_max_degrees < 0 or not math.isfinite(self.yaw_mae_max_degrees):
            raise ValueError("yaw_mae_max_degrees must be finite and non-negative")


@dataclass(frozen=True)
class BaselineCase:
    case_id: str
    image_path: Path
    expected_target: bool
    expected_yaw_offset: float | None
    source: str
    canonical_geometry: bool
    expected_box: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if not self.case_id or any(character in self.case_id for character in "\r\n"):
            raise ValueError("case_id is required and must fit on one line")
        if self.expected_target != (self.expected_yaw_offset is not None):
            raise ValueError("target cases require yaw labels and no-target cases must omit them")
        if self.expected_yaw_offset is not None and not math.isfinite(
            self.expected_yaw_offset
        ):
            raise ValueError("expected yaw must be finite")
        if self.expected_box is not None:
            x1, y1, x2, y2 = self.expected_box
            if not self.expected_target or x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("expected target box is invalid")


def rectangle_mask(
    detection: Detection,
    *,
    width: int,
    height: int,
) -> np.ndarray:
    """Create the single-channel mask consumed by the reference yaw CNN."""

    x1, y1, x2, y2 = detection.box
    x1 = min(max(x1, 0), width - 1)
    y1 = min(max(y1, 0), height - 1)
    x2 = min(max(x2, 0), width - 1)
    y2 = min(max(y2, 0), height - 1)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("clipped detection box has no area")
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[y1 : y2 + 1, x1 : x2 + 1] = 255
    return mask


def load_target_annotations(
    path: Path,
    expected_case_ids: set[str],
    *,
    width: int,
    height: int,
) -> dict[str, tuple[int, int, int, int]]:
    """Load independently authored boxes and require complete split coverage."""

    annotations: dict[str, tuple[int, int, int, int]] = {}
    with path.expanduser().resolve().open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TARGET_ANNOTATION_COLUMNS:
            raise ValueError("invalid target annotation CSV header")
        for row in reader:
            case_id = row["case_id"]
            if case_id in annotations:
                raise ValueError(f"duplicate target annotation: {case_id}")
            if not row["annotated_by"].strip():
                raise ValueError(f"target annotation has no author: {case_id}")
            try:
                box = tuple(int(row[key]) for key in TARGET_ANNOTATION_COLUMNS[1:5])
            except ValueError as error:
                raise ValueError(f"invalid target annotation coordinates: {case_id}") from error
            x1, y1, x2, y2 = box
            if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1 or x2 >= width or y2 >= height:
                raise ValueError(f"target annotation is outside model geometry: {case_id}")
            annotations[case_id] = box
    if set(annotations) != expected_case_ids:
        missing = sorted(expected_case_ids - set(annotations))
        extra = sorted(set(annotations) - expected_case_ids)
        raise ValueError(
            f"target annotations must cover the exact split; missing={missing}, extra={extra}"
        )
    return annotations


def dataset_cases(
    dataset: Path,
    split: str,
    target_annotations: Mapping[str, tuple[int, int, int, int]] | None = None,
) -> tuple[list[BaselineCase], dict[str, Any]]:
    if split not in SPLIT_NAMES:
        raise ValueError(f"unsupported split: {split}")
    report = verify_yaw_dataset(dataset)
    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    rows: list[BaselineCase] = []
    with (dataset / "labels.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != DATASET_CSV_COLUMNS:
            raise ValueError("dataset labels header changed after verification")
        for row in reader:
            if row["split"] != split:
                continue
            rows.append(
                BaselineCase(
                    case_id=row["filename"],
                    image_path=dataset / row["filename"],
                    expected_target=True,
                    expected_yaw_offset=float(row["yaw_offset"]),
                    source=f"dataset:{report['dataset_id']}:{split}",
                    canonical_geometry=True,
                    expected_box=(target_annotations or {}).get(row["filename"]),
                )
            )
    return rows, manifest


def no_target_cases(paths: Iterable[Path]) -> list[BaselineCase]:
    cases: list[BaselineCase] = []
    for index, source in enumerate(sorted(Path(path).expanduser().resolve() for path in paths)):
        if not source.is_file():
            raise FileNotFoundError(f"no-target image not found: {source}")
        cases.append(
            BaselineCase(
                case_id=f"no-target-{index:06d}-{source.name}",
                image_path=source,
                expected_target=False,
                expected_yaw_offset=None,
                source="independent-no-target",
                canonical_geometry=False,
            )
        )
    return cases


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _gate(value: float | None, threshold: float, comparison: str) -> str:
    if value is None:
        return "incomplete"
    passed = value >= threshold if comparison == "minimum" else value <= threshold
    return "passed" if passed else "failed"


def _read_rgb(path: Path) -> np.ndarray:
    import cv2

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot decode image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _intersection_over_union(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def evaluate_cases(
    cases: Sequence[BaselineCase],
    detector: TargetDetector,
    yaw_regressor: YawRegressor,
    preprocessing: PreprocessingSpec,
    *,
    target_iou_min: float = 0.5,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Evaluate recorded cases without importing or controlling hardware."""

    if not cases:
        raise ValueError("at least one evaluation case is required")
    if not 0.0 < target_iou_min <= 1.0:
        raise ValueError("target_iou_min must be greater than 0 and at most 1")
    prediction_rows: list[dict[str, str]] = []
    positive_count = positive_detected = positive_annotated = positive_matched = 0
    negative_count = negative_detected = 0
    errors: list[float] = []
    signed_errors: list[float] = []
    for case in cases:
        rgb = _read_rgb(case.image_path)
        model_rgb = (
            resize_model_rgb(rgb, preprocessing)
            if case.canonical_geometry
            else prepare_model_rgb(rgb, preprocessing)
        )
        detection = detector.detect(model_rgb)
        predicted_yaw: float | None = None
        absolute_error: float | None = None
        matched_target: bool | None = None
        if case.expected_target:
            positive_count += 1
            if detection is not None:
                positive_detected += 1
            if case.expected_box is not None:
                positive_annotated += 1
                matched_target = detection is not None and _intersection_over_union(
                    detection.box, case.expected_box
                ) >= target_iou_min
                if matched_target:
                    positive_matched += 1
        else:
            negative_count += 1
            if detection is not None:
                negative_detected += 1
        if detection is not None and case.expected_yaw_offset is not None:
            mask = rectangle_mask(
                detection,
                width=preprocessing.model_width,
                height=preprocessing.model_height,
            )
            predicted_yaw = float(yaw_regressor.predict(mask))
            if not math.isfinite(predicted_yaw):
                raise ValueError(f"non-finite yaw prediction: {case.case_id}")
            signed_error = predicted_yaw - case.expected_yaw_offset
            signed_errors.append(signed_error)
            absolute_error = abs(signed_error)
            errors.append(absolute_error)
        box = detection.box if detection is not None else (None, None, None, None)
        prediction_rows.append(
            {
                "case_id": case.case_id,
                "source": case.source,
                "expected_target": str(case.expected_target).lower(),
                "detected": str(detection is not None).lower(),
                "confidence": "" if detection is None else f"{detection.confidence:.8f}",
                "box_x1": "" if box[0] is None else str(box[0]),
                "box_y1": "" if box[1] is None else str(box[1]),
                "box_x2": "" if box[2] is None else str(box[2]),
                "box_y2": "" if box[3] is None else str(box[3]),
                "expected_yaw_offset": (
                    "" if case.expected_yaw_offset is None else f"{case.expected_yaw_offset:.8f}"
                ),
                "predicted_yaw_offset": "" if predicted_yaw is None else f"{predicted_yaw:.8f}",
                "absolute_error": "" if absolute_error is None else f"{absolute_error:.8f}",
                "matched_target": "" if matched_target is None else str(matched_target).lower(),
            }
        )
    annotations_complete = positive_count > 0 and positive_annotated == positive_count
    return prediction_rows, {
        "case_counts": {
            "target": positive_count,
            "target_annotated": positive_annotated,
            "no_target": negative_count,
            "yaw_predictions": len(errors),
        },
        "target_iou_min": target_iou_min,
        "target_detection_rate": _rate(positive_detected, positive_count),
        "target_recall": _rate(positive_matched, positive_count) if annotations_complete else None,
        "no_target_false_positive_rate": _rate(negative_detected, negative_count),
        "yaw_mae_degrees": sum(errors) / len(errors) if errors else None,
        "yaw_rmse_degrees": (
            math.sqrt(sum(error * error for error in signed_errors) / len(signed_errors))
            if signed_errors
            else None
        ),
        "yaw_bias_degrees": sum(signed_errors) / len(signed_errors) if signed_errors else None,
    }


def write_baseline_run(
    output_root: Path,
    run_id: str,
    *,
    cases: Sequence[BaselineCase],
    predictions: Sequence[Mapping[str, str]],
    metrics: Mapping[str, Any],
    thresholds: BaselineThresholds,
    preprocessing: PreprocessingSpec,
    source_commit: str,
    dataset_manifest: Path,
    yolo_model: Path,
    yaw_model: Path,
    split: str = "validation",
    locked_test_approval: Mapping[str, str] | None = None,
    no_target_bundle: Path | None = None,
    target_annotations: Path | None = None,
) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run ID: {run_id}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full lowercase Git SHA")
    if split not in {"validation", "locked-test"}:
        raise ValueError("baseline split must be validation or locked-test")
    if split == "locked-test":
        if not locked_test_approval or not all(
            str(locked_test_approval.get(key, "")).strip()
            for key in ("approved_by", "approval_reference")
        ):
            raise ValueError("locked-test requires approver and approval reference")
    elif locked_test_approval is not None:
        raise ValueError("locked-test approval is only valid for the locked-test split")
    output_root = output_root.expanduser().resolve()
    partial = output_root / f".{run_id}.partial"
    completed = output_root / run_id
    if partial.exists() or completed.exists():
        raise FileExistsError(f"run already exists: {run_id}")
    partial.mkdir(parents=True)
    try:
        predictions_path = partial / "predictions.csv"
        with predictions_path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=PREDICTION_COLUMNS)
            writer.writeheader()
            writer.writerows(predictions)
        gates = {
            "target_recall": _gate(
                metrics.get("target_recall"), thresholds.target_recall_min, "minimum"
            ),
            "no_target_false_positive_rate": _gate(
                metrics.get("no_target_false_positive_rate"),
                thresholds.no_target_false_positive_rate_max,
                "maximum",
            ),
            "yaw_mae_degrees": _gate(
                metrics.get("yaw_mae_degrees"), thresholds.yaw_mae_max_degrees, "maximum"
            ),
        }
        overall = (
            "failed"
            if "failed" in gates.values()
            else "passed"
            if set(gates.values()) == {"passed"}
            else "incomplete"
        )
        metrics_document = {
            "schema_version": "rbg-baseline-metrics/v1",
            **metrics,
            "thresholds": asdict(thresholds),
            "gates": gates,
            "status": overall,
        }
        metrics_path = partial / "metrics.json"
        metrics_path.write_text(
            json.dumps(metrics_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        inputs = {
            "dataset_manifest": {
                "path": str(dataset_manifest.resolve()),
                "sha256": sha256_file(dataset_manifest),
            },
            "yolo_model": {"path": str(yolo_model.resolve()), "sha256": sha256_file(yolo_model)},
            "yaw_model": {"path": str(yaw_model.resolve()), "sha256": sha256_file(yaw_model)},
            "no_target_images": [
                {"path": str(case.image_path.resolve()), "sha256": sha256_file(case.image_path)}
                for case in cases
                if not case.expected_target
            ],
        }
        if no_target_bundle is not None:
            bundle = no_target_bundle.expanduser().resolve()
            inputs["no_target_bundle"] = {
                "path": str(bundle),
                "manifest_sha256": sha256_file(bundle / "manifest.json"),
                "cases_sha256": sha256_file(bundle / "cases.csv"),
            }
        if target_annotations is not None:
            annotations = target_annotations.expanduser().resolve()
            inputs["target_annotations"] = {
                "path": str(annotations),
                "sha256": sha256_file(annotations),
            }
        manifest = {
            "schema_version": BASELINE_RUN_SCHEMA,
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_commit": source_commit,
            "preprocessing": preprocessing.to_manifest(),
            "runtime": runtime_summary(),
            "evaluation": {
                "split": split,
                "locked_test_approval": locked_test_approval,
            },
            "inputs": inputs,
            "outputs": {
                "predictions.csv": sha256_file(predictions_path),
                "metrics.json": sha256_file(metrics_path),
            },
            "status": overall,
        }
        (partial / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        partial.rename(completed)
        return completed
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def verify_baseline_run(run: Path) -> dict[str, Any]:
    run = run.expanduser().resolve()
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != BASELINE_RUN_SCHEMA:
        raise ValueError("unsupported baseline run schema")
    if manifest.get("run_id") != run.name or not RUN_ID_PATTERN.fullmatch(run.name):
        raise ValueError("run directory and run ID differ")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", ""))):
        raise ValueError("invalid source commit")
    PreprocessingSpec.from_mapping(manifest.get("preprocessing", {}))
    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("split") not in {
        "validation",
        "locked-test",
    }:
        raise ValueError("invalid baseline evaluation split")
    if evaluation["split"] == "locked-test":
        approval = evaluation.get("locked_test_approval")
        if not isinstance(approval, dict) or not all(
            str(approval.get(key, "")).strip()
            for key in ("approved_by", "approval_reference")
        ):
            raise ValueError("locked-test approval metadata is incomplete")
    expected_outputs = manifest.get("outputs")
    if not isinstance(expected_outputs, dict) or set(expected_outputs) != {
        "predictions.csv",
        "metrics.json",
    }:
        raise ValueError("baseline output manifest is incomplete")
    for filename, expected_hash in expected_outputs.items():
        if not SHA256_PATTERN.fullmatch(str(expected_hash)):
            raise ValueError(f"invalid output hash: {filename}")
        if sha256_file(run / filename) != expected_hash:
            raise ValueError(f"output hash mismatch: {filename}")
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    if metrics.get("status") != manifest.get("status"):
        raise ValueError("run and metrics status differ")
    with (run / "predictions.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != PREDICTION_COLUMNS:
            raise ValueError("invalid predictions CSV header")
        rows = list(reader)
    # yaw_predictions is a subset, so only the two mutually exclusive case classes sum.
    expected_rows = int(metrics["case_counts"]["target"]) + int(
        metrics["case_counts"]["no_target"]
    )
    if len(rows) != expected_rows:
        raise ValueError("prediction count does not match metrics")
    return {
        "schema_version": "rbg-baseline-run-report/v1",
        "run_id": run.name,
        "prediction_count": len(rows),
        "status": manifest["status"],
        "run_manifest_sha256": sha256_file(manifest_path),
    }
