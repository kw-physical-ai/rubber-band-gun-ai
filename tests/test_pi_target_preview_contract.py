from pathlib import Path

PREVIEW = Path(__file__).resolve().parents[1] / "scripts" / "pi" / "preview-target.py"


def test_target_preview_has_no_actuator_interface() -> None:
    source = PREVIEW.read_text(encoding="utf-8")

    for forbidden in (
        "pigpio",
        "gpiozero",
        "set_servo_pulsewidth",
        "FIRE_PIN",
        "FIRE_SHOOT",
    ):
        assert forbidden not in source
    assert "TARGET PREVIEW ONLY" in source
    assert 'f"CANDIDATE {detection.confidence:.2f}' in source
    assert "picamera2_rgb888_to_rgb(camera.capture_array())" in source
    assert "orient_like_legacy_collector(raw_rgb)" in source


def test_headless_preview_requires_a_finite_frame_count() -> None:
    source = PREVIEW.read_text(encoding="utf-8")

    assert 'if args.headless and args.frames == 0:' in source
    assert 'parser.error("--headless requires a positive --frames value")' in source
