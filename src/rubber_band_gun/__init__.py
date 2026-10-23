"""Shared project utilities for Colab and Raspberry Pi evaluation."""

from .capture import CaptureCalibration, YawCaptureSession, verify_yaw_capture_bundle
from .dataset import build_yaw_dataset, verify_yaw_dataset
from .environment import ProjectWorkspace, runtime_summary
from .evaluation import (
    BaselineCase,
    BaselineThresholds,
    Detection,
    evaluate_cases,
    verify_baseline_run,
)
from .model_manifest import verify_model_manifest
from .no_target import NoTargetCaptureSession, verify_no_target_bundle
from .preprocessing import PreprocessingSpec, orient_and_crop_rgb, prepare_model_rgb
from .safety import ControlOrigin, ManualAxisPolicy
from .shot_results import ShotResult, write_shot_results
from .shot_run import ArtifactReference, ShotRunSession, verify_shot_run
from .smoke import verify_smoke_bundle

__all__ = [
    "CaptureCalibration",
    "BaselineCase",
    "BaselineThresholds",
    "Detection",
    "NoTargetCaptureSession",
    "ControlOrigin",
    "PreprocessingSpec",
    "ProjectWorkspace",
    "ManualAxisPolicy",
    "ShotResult",
    "ArtifactReference",
    "ShotRunSession",
    "YawCaptureSession",
    "build_yaw_dataset",
    "evaluate_cases",
    "orient_and_crop_rgb",
    "prepare_model_rgb",
    "runtime_summary",
    "verify_smoke_bundle",
    "verify_shot_run",
    "verify_baseline_run",
    "verify_model_manifest",
    "verify_no_target_bundle",
    "verify_yaw_dataset",
    "verify_yaw_capture_bundle",
    "write_shot_results",
]
