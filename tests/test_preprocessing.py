import numpy as np
import pytest

from rubber_band_gun.preprocessing import (
    PREPROCESSING_SCHEMA,
    PreprocessingSpec,
    orient_and_crop_rgb,
    picamera2_rgb888_to_rgb,
    prepare_model_rgb,
)


def test_orient_and_crop_matches_live_geometry() -> None:
    frame = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    spec = PreprocessingSpec(crop_bottom_ratio=0.25)

    actual = orient_and_crop_rgb(frame, spec)
    rotated = np.rot90(frame, k=3)

    assert np.array_equal(actual, rotated[:4])
    assert actual.flags.c_contiguous


def test_picamera2_rgb888_memory_order_is_converted_to_rgb() -> None:
    bgr = np.array([[[3, 2, 1], [30, 20, 10]]], dtype=np.uint8)

    rgb = picamera2_rgb888_to_rgb(bgr)

    assert np.array_equal(rgb, [[[1, 2, 3], [10, 20, 30]]])
    assert rgb.flags.c_contiguous


def test_prepare_model_rgb_has_declared_shape() -> None:
    frame = np.zeros((8, 12, 3), dtype=np.uint8)
    spec = PreprocessingSpec(model_width=7, model_height=5)

    prepared = prepare_model_rgb(frame, spec)

    assert prepared.shape == (5, 7, 3)
    assert prepared.dtype == np.uint8


def test_preprocessing_manifest_round_trip() -> None:
    spec = PreprocessingSpec(crop_bottom_ratio=0.125, model_width=112, model_height=96)

    restored = PreprocessingSpec.from_mapping(spec.to_manifest())

    assert restored == spec
    assert spec.to_manifest()["schema_version"] == PREPROCESSING_SCHEMA


@pytest.mark.parametrize("ratio", [-0.01, 1.0])
def test_preprocessing_rejects_invalid_crop(ratio: float) -> None:
    with pytest.raises(ValueError, match="crop_bottom_ratio"):
        PreprocessingSpec(crop_bottom_ratio=ratio)
