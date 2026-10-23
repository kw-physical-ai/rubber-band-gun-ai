#!/usr/bin/env python3
"""Evaluate the reference detector and yaw model on immutable recorded data."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from rubber_band_gun import verify_yaw_dataset
from rubber_band_gun.evaluation import (
    BaselineThresholds,
    dataset_cases,
    evaluate_cases,
    load_target_annotations,
    no_target_cases,
    sha256_file,
    verify_baseline_run,
    write_baseline_run,
)
from rubber_band_gun.no_target import verify_no_target_bundle
from rubber_band_gun.preprocessing import PreprocessingSpec
from rubber_band_gun.runtime_models import TorchYawRegressor, UltralyticsTargetDetector


def _current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "locked-test"), default="validation")
    parser.add_argument("--allow-locked-test", action="store_true")
    parser.add_argument("--locked-test-approved-by")
    parser.add_argument("--locked-test-approval-reference")
    parser.add_argument("--no-target-bundle", type=Path)
    parser.add_argument("--target-annotations", type=Path, required=True)
    parser.add_argument("--target-iou-min", type=float, default=0.5)
    parser.add_argument("--yolo-model", type=Path, required=True)
    parser.add_argument("--yaw-model", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--device", default=None)
    parser.add_argument("--target-recall-min", type=float, required=True)
    parser.add_argument("--no-target-fpr-max", type=float, required=True)
    parser.add_argument("--yaw-mae-max", type=float, required=True)
    args = parser.parse_args()

    locked_test_approval = None
    if args.split == "locked-test":
        if not (
            args.allow_locked_test
            and args.locked_test_approved_by
            and args.locked_test_approval_reference
        ):
            raise RuntimeError(
                "locked-test refused: freeze the candidate and thresholds, then provide "
                "--allow-locked-test, --locked-test-approved-by, and "
                "--locked-test-approval-reference"
            )
        locked_test_approval = {
            "approved_by": args.locked_test_approved_by,
            "approval_reference": args.locked_test_approval_reference,
        }
    input_hashes = {
        "dataset_manifest": sha256_file(args.dataset / "dataset_manifest.json"),
        "target_annotations": sha256_file(args.target_annotations),
        "yolo_model": sha256_file(args.yolo_model),
        "yaw_model": sha256_file(args.yaw_model),
    }
    unannotated_cases, dataset_manifest = dataset_cases(args.dataset, args.split)
    preprocessing = PreprocessingSpec.from_mapping(dataset_manifest["preprocessing"])
    annotations = load_target_annotations(
        args.target_annotations,
        {case.case_id for case in unannotated_cases},
        width=preprocessing.model_width,
        height=preprocessing.model_height,
    )
    positive_cases, _ = dataset_cases(args.dataset, args.split, annotations)
    no_target_report = (
        verify_no_target_bundle(args.no_target_bundle) if args.no_target_bundle else None
    )
    if no_target_report and no_target_report["preprocessing"] != preprocessing.to_manifest():
        raise ValueError("no-target and dataset preprocessing definitions differ")
    cases = positive_cases + no_target_cases(
        no_target_report["image_paths"] if no_target_report else []
    )
    detector = UltralyticsTargetDetector(
        args.yolo_model,
        confidence=args.confidence,
        device=args.device,
    )
    yaw_regressor = TorchYawRegressor(
        args.yaw_model,
        image_size=preprocessing.model_width,
        device=args.device or "cpu",
    )
    predictions, metrics = evaluate_cases(
        cases,
        detector,
        yaw_regressor,
        preprocessing,
        target_iou_min=args.target_iou_min,
    )
    final_dataset_report = verify_yaw_dataset(args.dataset)
    if final_dataset_report["dataset_manifest_sha256"] != input_hashes["dataset_manifest"]:
        raise RuntimeError("dataset changed during baseline evaluation")
    if sha256_file(args.target_annotations) != input_hashes["target_annotations"]:
        raise RuntimeError("target annotations changed during baseline evaluation")
    if sha256_file(args.yolo_model) != input_hashes["yolo_model"]:
        raise RuntimeError("YOLO model changed during baseline evaluation")
    if sha256_file(args.yaw_model) != input_hashes["yaw_model"]:
        raise RuntimeError("yaw model changed during baseline evaluation")
    if args.no_target_bundle:
        final_no_target_report = verify_no_target_bundle(args.no_target_bundle)
        if (
            final_no_target_report["source_manifest_sha256"]
            != no_target_report["source_manifest_sha256"]
        ):
            raise RuntimeError("no-target bundle changed during baseline evaluation")
    completed = write_baseline_run(
        args.output_root,
        args.run_id,
        cases=cases,
        predictions=predictions,
        metrics=metrics,
        thresholds=BaselineThresholds(
            target_recall_min=args.target_recall_min,
            no_target_false_positive_rate_max=args.no_target_fpr_max,
            yaw_mae_max_degrees=args.yaw_mae_max,
        ),
        preprocessing=preprocessing,
        source_commit=args.source_commit or _current_commit(),
        dataset_manifest=args.dataset / "dataset_manifest.json",
        yolo_model=args.yolo_model,
        yaw_model=args.yaw_model,
        split=args.split,
        locked_test_approval=locked_test_approval,
        no_target_bundle=args.no_target_bundle,
        target_annotations=args.target_annotations,
    )
    print(json.dumps(verify_baseline_run(completed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
