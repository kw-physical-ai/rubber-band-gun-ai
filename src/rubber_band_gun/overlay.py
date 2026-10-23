"""Display-only overlays for camera previews."""

from __future__ import annotations

import numpy as np


def draw_center_crosshair_bgr(frame: np.ndarray) -> np.ndarray:
    """Return a copy with a crosshair at pixel ``(width // 2, height // 2)``."""

    if not isinstance(frame, np.ndarray):
        raise TypeError("frame must be a numpy array")
    if frame.dtype != np.uint8:
        raise ValueError("frame must use uint8 pixels")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must have shape (height, width, 3)")
    height, width = frame.shape[:2]
    if height < 1 or width < 1:
        raise ValueError("frame dimensions must be positive")

    import cv2

    display = frame.copy()
    center = (width // 2, height // 2)
    arm_length = max(10, min(height, width) // 20)
    circle_radius = max(4, min(height, width) // 80)
    horizontal_start = (center[0] - arm_length, center[1])
    horizontal_end = (center[0] + arm_length, center[1])
    vertical_start = (center[0], center[1] - arm_length)
    vertical_end = (center[0], center[1] + arm_length)

    for thickness, color in ((5, (0, 0, 0)), (2, (0, 255, 0))):
        cv2.line(display, horizontal_start, horizontal_end, color, thickness)
        cv2.line(display, vertical_start, vertical_end, color, thickness)
        cv2.circle(display, center, circle_radius, color, thickness)
    cv2.circle(display, center, 1, (255, 255, 255), thickness=-1)
    return display
