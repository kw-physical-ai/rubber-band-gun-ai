#!/usr/bin/env python3
"""Check repository policy, secrets, model pairing, and evaluation-only boundaries."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from rubber_band_gun import verify_model_manifest

FORBIDDEN_PREFIXES = ("physical-ai/", "data/", "captures/", "runs/")
FORBIDDEN_EXACT = {"configs/pi.toml", ".env"}
TEXT_SUFFIXES = {
    ".json",
    ".ipynb",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "hard-coded API key": re.compile(
        r"(?i)(?:api[_-]?key|token)\s*=\s*['\"](?!replace|example|<)[A-Za-z0-9_-]{16,}['\"]"
    ),
}


def _tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return [Path(value.decode()) for value in output.split(b"\0") if value]


def _untracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
    ).stdout
    return [Path(value.decode()) for value in output.split(b"\0") if value]


def _index_bytes(path: Path) -> bytes:
    return subprocess.run(
        ["git", "show", f":{path.as_posix()}"],
        check=True,
        capture_output=True,
    ).stdout


def main() -> None:
    errors: list[str] = []
    tracked = _tracked_files()
    repository_files = sorted(set(tracked + _untracked_files()))
    for path in repository_files:
        name = path.as_posix()
        if name in FORBIDDEN_EXACT or name.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"forbidden tracked path: {name}")
        if path.suffix.lower() in TEXT_SUFFIXES and path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"text file is not UTF-8: {name}")
                continue
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"possible {label}: {name}")

    model_artifacts = [
        path
        for path in repository_files
        if path.parent == Path("models") and path.suffix in {".pt", ".pth"}
    ]
    for artifact in model_artifacts:
        if artifact in tracked:
            index = _index_bytes(artifact)
            if not index.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                errors.append(f"model is not stored as a Git LFS pointer: {artifact}")
        else:
            attribute = subprocess.run(
                ["git", "check-attr", "filter", "--", str(artifact)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not attribute.endswith(": lfs"):
                errors.append(f"untracked model is not covered by Git LFS: {artifact}")
        manifest = artifact.with_suffix(artifact.suffix + ".json")
        if manifest not in repository_files:
            errors.append(f"model manifest missing: {manifest}")
        elif artifact.is_file() and not artifact.read_bytes().startswith(
            b"version https://git-lfs.github.com/spec/v1\n"
        ):
            try:
                verify_model_manifest(manifest)
            except (OSError, ValueError) as error:
                errors.append(f"invalid model manifest {manifest}: {error}")

    actuator_free_sources = {
        "evaluation-only preview": Path("scripts/pi/preview-inference.py"),
        "shot-run evidence contract": Path("src/rubber_band_gun/shot_run.py"),
        "safety contract": Path("src/rubber_band_gun/safety.py"),
    }
    for label, source_path in actuator_free_sources.items():
        source = source_path.read_text(encoding="utf-8")
        for forbidden in ("pigpio", "gpiozero", "set_servo_pulsewidth", "FIRE_PIN"):
            if forbidden in source:
                errors.append(f"{label} contains actuator capability: {forbidden}")

    evaluator = Path("scripts/pi/log-shot-run.py").read_text(encoding="utf-8")
    required_evaluator_contract = (
        'set(servo) != {"yaw", "pitch"}',
        "set_servo_pulsewidth(config.pin, pulse)",
        "event independently, then press Enter",
    )
    for required in required_evaluator_contract:
        if required not in evaluator:
            errors.append(f"manual evaluator is missing its axis boundary: {required}")
    for forbidden in ("FIRE_PIN", "trigger_pin", "update_fire_button", "automatic_aim"):
        if forbidden in evaluator:
            errors.append(f"manual evaluator contains prohibited capability: {forbidden}")

    python_sources = [
        path
        for path in repository_files
        if path.suffix == ".py" and (path.parts[0] == "src" or path.parts[:2] == ("scripts", "pi"))
    ]
    for source_path in python_sources:
        source = source_path.read_text(encoding="utf-8")
        for forbidden in ("FIRE_PIN", "fire_servo", "update_fire_button", "trigger_pin"):
            if forbidden in source:
                errors.append(
                    f"repository source contains prohibited event capability: "
                    f"{source_path}: {forbidden}"
                )

    if errors:
        raise SystemExit("repository policy failed:\n- " + "\n- ".join(errors))
    print(
        "repository policy passed: "
        f"{len(tracked)} tracked and {len(repository_files) - len(tracked)} untracked files checked"
    )


if __name__ == "__main__":
    main()
