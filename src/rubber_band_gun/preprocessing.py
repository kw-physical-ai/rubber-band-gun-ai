"""Shared camera geometry for collection, training, and inference."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

PREPROCESSING_SCHEMA = "rbg-camera-preprocessing/v1"


@dataclass(frozen=True)
class PreprocessingSpec:
    """One versioned definition of the model's camera field of view."""

    rotation: str = "clockwise_90"
    crop_bottom_ratio: float = 0.2
    model_width: int = 224
    model_height: int = 224

    def __post_init__(self) -> None:
        if self.rotation != "clockwise_90":
            raise ValueError("rotation must be clockwise_90")
        if not 0.0 <= self.crop_bottom_ratio < 1.0:
            raise ValueError("crop_bottom_ratio must be at least 0 and less than 1")
        if self.model_width < 1 or self.model_height < 1:
            raise ValueError("model dimensions must be positive")

    def to_manifest(self) -> dict[str, Any]:
        return {"schema_version": PREPROCESSING_SCHEMA, **asdict(self)}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PreprocessingSpec:
        if value.get("schema_version") != PREPROCESSING_SCHEMA:
            raise ValueError(f"unsupported preprocessing schema: {value.get('schema_version')}")
        return cls(
            rotation=str(value["rotation"]),
            crop_bottom_ratio=float(value["crop_bottom_ratio"]),
            model_width=int(value["model_width"]),
            model_height=int(value["model_height"]),
        )


def _validate_rgb_frame(frame: np.ndarray) -> None:
    if not isinstance(frame, np.ndarray):
        raise TypeError("frame must be a numpy array")
    if frame.dtype != np.uint8:
        raise ValueError("frame must use uint8 pixels")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must have shape (height, width, 3)")
    if frame.shape[0] < 1 or frame.shape[1] < 1:
        raise ValueError("frame dimensions must be positive")


def picamera2_rgb888_to_rgb(frame: np.ndarray) -> np.ndarray:
    """Convert a Picamera2 RGB888 array, whose memory order is BGR, to RGB."""

    _validate_rgb_frame(frame)
    return np.ascontiguousarray(frame[..., ::-1])


def orient_and_crop_rgb(frame: np.ndarray, spec: PreprocessingSpec) -> np.ndarray:
    """Apply the canonical live-camera geometry and return contiguous RGB pixels."""

    _validate_rgb_frame(frame)
    rotated = np.rot90(frame, k=3)
    crop_end = max(1, int(rotated.shape[0] * (1.0 - spec.crop_bottom_ratio)))
    return np.ascontiguousarray(rotated[:crop_end])


def resize_model_rgb(frame: np.ndarray, spec: PreprocessingSpec) -> np.ndarray:
    """Resize an already oriented/cropped RGB frame for model input."""

    _validate_rgb_frame(frame)
    import cv2

    return cv2.resize(
        frame,
        (spec.model_width, spec.model_height),
        interpolation=cv2.INTER_AREA,
    )


def prepare_model_rgb(frame: np.ndarray, spec: PreprocessingSpec) -> np.ndarray:
    """Apply the exact live geometry and model resize in one call."""

    return resize_model_rgb(orient_and_crop_rgb(frame, spec), spec)
