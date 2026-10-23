from pathlib import Path

COLLECTOR = Path(__file__).resolve().parents[1] / "scripts" / "pi" / "collect-yaw-data.py"
PREVIEW = Path(__file__).resolve().parents[1] / "scripts" / "pi" / "preview-inference.py"
NO_TARGET = Path(__file__).resolve().parents[1] / "scripts" / "pi" / "capture-no-target.py"


def test_collector_has_no_firing_interface() -> None:
    source = COLLECTOR.read_text(encoding="utf-8")

    assert "FIRE_PIN" not in source
    assert "FIRE_SHOOT" not in source
    assert "--enable-motion" in source
    assert "calibrated=true" in source
    assert "SETTLING - CAPTURE DISABLED" in source
    assert "picamera2_rgb888_to_rgb(camera.capture_array())" in source
    assert "draw_center_crosshair_bgr(display)" in source
    assert "session.add_frame(\n                    raw_rgb," in source
    assert "session.add_frame(\n                    display," not in source


def test_inference_preview_has_no_actuator_interface() -> None:
    source = PREVIEW.read_text(encoding="utf-8")

    for forbidden in ("pigpio", "gpiozero", "set_servo_pulsewidth", "FIRE_PIN"):
        assert forbidden not in source
    assert "EVALUATION ONLY" in source
    assert "picamera2_rgb888_to_rgb(camera.capture_array())" in source


def test_no_target_capture_has_no_actuator_interface() -> None:
    source = NO_TARGET.read_text(encoding="utf-8")

    for forbidden in ("import pigpio", "gpiozero", "set_servo_pulsewidth", "FIRE_PIN"):
        assert forbidden not in source
    assert "picamera2_rgb888_to_rgb(camera.capture_array())" in source
