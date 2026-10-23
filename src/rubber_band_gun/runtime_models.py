"""Lazy adapters for the course YOLO and yaw-CNN artifacts."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .evaluation import Detection


def build_yaw_cnn() -> Any:
    """Build the reference architecture without importing torch at package import time."""

    import torch.nn as nn

    class YawCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 16, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Conv2d(16, 32, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Conv2d(64, 128, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.AdaptiveAvgPool2d((4, 4)),
            )
            self.regressor = nn.Sequential(
                nn.Flatten(),
                nn.Linear(128 * 4 * 4, 64),
                nn.ReLU(),
                nn.Dropout(0.25),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

        def forward(self, value: Any) -> Any:
            return self.regressor(self.features(value))

    return YawCNN()


class UltralyticsTargetDetector:
    def __init__(
        self,
        model_path: Path,
        *,
        confidence: float = 0.5,
        device: str | None = None,
        image_size: int = 640,
        tile_grid: int = 1,
        tile_overlap: float = 0.2,
        include_full_frame: bool = True,
    ):
        if not 0.0 < confidence <= 1.0:
            raise ValueError("confidence must be greater than 0 and at most 1")
        if image_size < 32:
            raise ValueError("image_size must be at least 32")
        if tile_grid < 1:
            raise ValueError("tile_grid must be positive")
        if not 0.0 <= tile_overlap < 1.0:
            raise ValueError("tile_overlap must be within 0..1")
        from ultralytics import YOLO

        self.model = YOLO(str(model_path))
        self.confidence = confidence
        self.device = device
        self.image_size = image_size
        self.tile_grid = tile_grid
        self.tile_overlap = tile_overlap
        self.include_full_frame = include_full_frame

    def detect(self, model_rgb: np.ndarray) -> Detection | None:
        import cv2

        height, width = model_rgb.shape[:2]
        windows = target_tile_windows(
            width,
            height,
            grid=self.tile_grid,
            overlap=self.tile_overlap,
            include_full_frame=self.include_full_frame,
        )
        sources = [
            cv2.cvtColor(model_rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
            for x1, y1, x2, y2 in windows
        ]
        options: dict[str, Any] = {
            "source": sources,
            "conf": self.confidence,
            "imgsz": self.image_size,
            "verbose": False,
        }
        if self.device is not None:
            options["device"] = self.device
        best: Detection | None = None
        for window, result in zip(windows, self.model.predict(**options), strict=True):
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            confidences = boxes.conf.detach().cpu().numpy()
            best_index = int(np.argmax(confidences))
            coords = np.rint(boxes.xyxy[best_index].detach().cpu().numpy()).astype(int)
            offset_x, offset_y = window[:2]
            x1 = int(np.clip(coords[0] + offset_x, 0, width - 1))
            y1 = int(np.clip(coords[1] + offset_y, 0, height - 1))
            x2 = int(np.clip(coords[2] + offset_x, 0, width - 1))
            y2 = int(np.clip(coords[3] + offset_y, 0, height - 1))
            if x2 <= x1 or y2 <= y1:
                continue
            candidate = Detection((x1, y1, x2, y2), float(confidences[best_index]))
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        return best


def target_tile_windows(
    width: int,
    height: int,
    *,
    grid: int,
    overlap: float,
    include_full_frame: bool,
) -> list[tuple[int, int, int, int]]:
    """Return deterministic overlapping ``(x1, y1, x2, y2)`` inference windows."""

    if width < 1 or height < 1:
        raise ValueError("frame dimensions must be positive")
    if grid < 1:
        raise ValueError("grid must be positive")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("overlap must be within 0..1")
    if grid == 1:
        return [(0, 0, width, height)]

    tile_width = min(width, math.ceil(width / (grid - (grid - 1) * overlap)))
    tile_height = min(height, math.ceil(height / (grid - (grid - 1) * overlap)))
    x_starts = np.rint(np.linspace(0, width - tile_width, grid)).astype(int)
    y_starts = np.rint(np.linspace(0, height - tile_height, grid)).astype(int)
    windows = [
        (int(x), int(y), int(x + tile_width), int(y + tile_height))
        for y in y_starts
        for x in x_starts
    ]
    if include_full_frame:
        return [(0, 0, width, height), *windows]
    return windows


class TorchYawRegressor:
    def __init__(self, checkpoint_path: Path, *, image_size: int, device: str = "cpu") -> None:
        import torch

        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
        if not isinstance(checkpoint, dict):
            raise ValueError("yaw checkpoint must contain metadata and model_state_dict")
        required = {"model_state_dict", "yaw_min", "yaw_max"}
        if not required <= checkpoint.keys():
            raise ValueError(f"yaw checkpoint is missing: {sorted(required - checkpoint.keys())}")
        checkpoint_size = int(checkpoint.get("image_size", image_size))
        if checkpoint_size != image_size:
            raise ValueError(
                f"yaw checkpoint image_size {checkpoint_size} does not match {image_size}"
            )
        self.yaw_min = float(checkpoint["yaw_min"])
        self.yaw_max = float(checkpoint["yaw_max"])
        if not all(math.isfinite(value) for value in (self.yaw_min, self.yaw_max)):
            raise ValueError("yaw checkpoint range must be finite")
        if self.yaw_max <= self.yaw_min:
            raise ValueError("yaw checkpoint range must increase")
        self.torch = torch
        self.device = torch.device(device)
        self.model = build_yaw_cnn().to(self.device)
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.eval()

    def predict(self, mask: np.ndarray) -> float:
        if mask.dtype != np.uint8 or mask.ndim != 2:
            raise ValueError("yaw mask must be a single-channel uint8 array")
        tensor = (
            self.torch.from_numpy(mask)
            .float()
            .div(255.0)
            .unsqueeze(0)
            .unsqueeze(0)
            .to(self.device)
        )
        with self.torch.inference_mode():
            normalized = float(self.model(tensor).item())
        return normalized * (self.yaw_max - self.yaw_min) + self.yaw_min
