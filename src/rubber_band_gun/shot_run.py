"""Immutable evidence bundles for manually positioned evaluation trials."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import secrets
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .preprocessing import PreprocessingSpec, orient_and_crop_rgb

SHOT_RUN_SCHEMA = "rbg-shot-run/v1"
SHOT_RUN_REPORT_SCHEMA = "rbg-shot-run-report/v1"
SHOT_RUN_ID_PATTERN = re.compile(r"shot-run-\d{8}T\d{6}Z(?:-[a-z0-9]{1,16})?")
REFERENCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHOT_RUN_COLUMNS = (
    "shot_id",
    "pre_event_frame",
    "pre_event_captured_at_utc",
    "external_event_acknowledged_at_utc",
    "outcome_recorded_at_utc",
    "target_distance_m",
    "commanded_yaw_degrees",
    "commanded_pitch_degrees",
    "predicted_yaw_offset_degrees",
    "outcome",
    "impact_x_mm",
    "impact_y_mm",
    "post_event_evidence",
    "post_event_captured_at_utc",
    "notes",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return instant.astimezone(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return _utc(value).isoformat()


def _parse_timestamp(name: str, value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _finite(name: str, value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _angle(name: str, value: object) -> float:
    angle = _finite(name, value)
    if not 0.0 <= angle <= 180.0:
        raise ValueError(f"{name} must be within 0..180 degrees")
    return angle


def _relative_file(name: str) -> Path:
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError(f"unsafe bundle path: {name}")
    return relative


@dataclass(frozen=True)
class ArtifactReference:
    """A content-addressed reference without copying a potentially large artifact."""

    reference_id: str
    filename: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if not REFERENCE_ID_PATTERN.fullmatch(self.reference_id):
            raise ValueError(f"invalid reference ID: {self.reference_id}")
        if Path(self.filename).name != self.filename or not self.filename:
            raise ValueError("reference filename must be a plain file name")
        if self.bytes < 0:
            raise ValueError("reference byte count cannot be negative")
        if not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("reference SHA-256 is invalid")

    @classmethod
    def from_path(cls, reference_id: str, path: Path) -> ArtifactReference:
        expanded = path.expanduser().absolute()
        if expanded.is_symlink() or not expanded.is_file():
            raise ValueError(f"reference must be an ordinary file: {path}")
        resolved = expanded.resolve()
        before = resolved.stat()
        digest = _sha256(resolved)
        after = resolved.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"reference changed while it was being hashed: {path}")
        return cls(reference_id, resolved.name, after.st_size, digest)

    def to_manifest(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "filename": self.filename,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class _PendingShot:
    shot_id: str
    pre_event_frame: str
    pre_event_captured_at_utc: str
    target_distance_m: float
    commanded_yaw_degrees: float
    commanded_pitch_degrees: float
    predicted_yaw_offset_degrees: float | None


class ShotRunSession:
    """Stage a run and publish it once; this class has no hardware-control capability."""

    def __init__(
        self,
        output_root: Path,
        preprocessing: PreprocessingSpec,
        *,
        target_coordinate_system: str,
        run_id: str | None = None,
        calibration_id: str | None = None,
        calibration_reference: ArtifactReference | None = None,
        model_references: tuple[ArtifactReference, ...] = (),
        created_at: datetime | None = None,
    ) -> None:
        self.output_root = output_root.expanduser().resolve()
        self.preprocessing = preprocessing
        self.run_id = run_id or (
            datetime.now(UTC).strftime("shot-run-%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
        )
        if not SHOT_RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError(f"invalid shot run ID: {self.run_id}")
        if not target_coordinate_system.strip():
            raise ValueError("target coordinate system is required")
        if calibration_id is not None and not calibration_id.strip():
            raise ValueError("calibration ID cannot be blank")
        reference_ids = [reference.reference_id for reference in model_references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("model reference IDs must be unique")

        self.target_coordinate_system = target_coordinate_system.strip()
        self.calibration_id = calibration_id
        self.calibration_reference = calibration_reference
        self.model_references = model_references
        self.partial_path = self.output_root / f".{self.run_id}.partial"
        self.completed_path = self.output_root / self.run_id
        if self.partial_path.exists() or self.completed_path.exists():
            raise FileExistsError(f"shot run already exists: {self.run_id}")
        (self.partial_path / "evidence").mkdir(parents=True)
        self._created_at_utc = _timestamp(created_at)
        self._rows: list[dict[str, str]] = []
        self._pending: _PendingShot | None = None
        self._canonical_shape: tuple[int, int, int] | None = None
        self._finalized = False

    def _write_rgb_png(self, relative: Path, raw_rgb: np.ndarray) -> None:
        import cv2

        canonical = orient_and_crop_rgb(raw_rgb, self.preprocessing)
        if self._canonical_shape is None:
            self._canonical_shape = canonical.shape
        elif canonical.shape != self._canonical_shape:
            raise ValueError(
                f"canonical frame shape changed from {self._canonical_shape} to {canonical.shape}"
            )
        success, encoded = cv2.imencode(
            ".png", cv2.cvtColor(canonical, cv2.COLOR_RGB2BGR)
        )
        if not success:
            raise RuntimeError("PNG encoding failed")
        (self.partial_path / relative).write_bytes(encoded.tobytes())

    def begin_shot(
        self,
        raw_rgb: np.ndarray,
        *,
        target_distance_m: float,
        commanded_yaw_degrees: float,
        commanded_pitch_degrees: float,
        predicted_yaw_offset_degrees: float | None = None,
        captured_at: datetime | None = None,
    ) -> str:
        """Persist the exact pre-event frame before any outcome can be supplied."""

        if self._finalized:
            raise RuntimeError("shot run is already finalized")
        if self._pending is not None:
            raise RuntimeError("the preceding shot still needs an outcome")
        distance = _finite("target_distance_m", target_distance_m)
        if distance <= 0:
            raise ValueError("target_distance_m must be positive")
        yaw = _angle("commanded_yaw_degrees", commanded_yaw_degrees)
        pitch = _angle("commanded_pitch_degrees", commanded_pitch_degrees)
        prediction = (
            None
            if predicted_yaw_offset_degrees is None
            else _finite("predicted_yaw_offset_degrees", predicted_yaw_offset_degrees)
        )
        shot_id = f"shot-{len(self._rows) + 1:06d}"
        staging = Path(f".{shot_id}.staging")
        staged_frame = staging / "pre.png"
        relative = Path("evidence") / shot_id / "pre.png"
        (self.partial_path / staging).mkdir()
        self._write_rgb_png(staged_frame, raw_rgb)
        attempt = {
            "shot_id": shot_id,
            "pre_event_frame": relative.as_posix(),
            "pre_event_captured_at_utc": _timestamp(captured_at),
            "target_distance_m": distance,
            "commanded_yaw_degrees": yaw,
            "commanded_pitch_degrees": pitch,
            "predicted_yaw_offset_degrees": prediction,
            "status": "pre-event-stored",
        }
        (self.partial_path / staging / "attempt.json").write_text(
            json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.partial_path / staging).rename(self.partial_path / "evidence" / shot_id)
        self._pending = _PendingShot(
            shot_id=shot_id,
            pre_event_frame=relative.as_posix(),
            pre_event_captured_at_utc=str(attempt["pre_event_captured_at_utc"]),
            target_distance_m=distance,
            commanded_yaw_degrees=yaw,
            commanded_pitch_degrees=pitch,
            predicted_yaw_offset_degrees=prediction,
        )
        return shot_id

    def complete_shot(
        self,
        *,
        outcome: str,
        external_event_acknowledged_at: datetime,
        impact_x_mm: float | None = None,
        impact_y_mm: float | None = None,
        post_event_rgb: np.ndarray | None = None,
        post_event_captured_at: datetime | None = None,
        notes: str = "",
        outcome_recorded_at: datetime | None = None,
    ) -> None:
        """Record operator-supplied evidence after an independently performed event."""

        if self._pending is None:
            raise RuntimeError("no pre-event shot is pending")
        if outcome not in {"hit", "miss", "invalid"}:
            raise ValueError(f"invalid shot outcome: {outcome}")
        if (impact_x_mm is None) != (impact_y_mm is None):
            raise ValueError("impact coordinates must both be present or both be absent")
        if (post_event_rgb is None) != (post_event_captured_at is None):
            raise ValueError("post-event frame and capture time must both be present or absent")
        impact_x = None if impact_x_mm is None else _finite("impact_x_mm", impact_x_mm)
        impact_y = None if impact_y_mm is None else _finite("impact_y_mm", impact_y_mm)
        acknowledged = _utc(external_event_acknowledged_at)
        recorded = _utc(outcome_recorded_at)
        captured = _parse_timestamp(
            "pre_event_captured_at_utc", self._pending.pre_event_captured_at_utc
        )
        if acknowledged < captured:
            raise ValueError("external event acknowledgment cannot precede pre-event capture")
        if recorded < acknowledged:
            raise ValueError("outcome recording cannot precede external event acknowledgment")

        post_path = ""
        post_captured_at = ""
        if post_event_rgb is not None:
            post_captured = _utc(post_event_captured_at)
            if post_captured < acknowledged or post_captured > recorded:
                raise ValueError(
                    "post-event capture must follow acknowledgment and precede outcome recording"
                )
            relative = Path("evidence") / self._pending.shot_id / "post.png"
            self._write_rgb_png(relative, post_event_rgb)
            post_path = relative.as_posix()
            post_captured_at = post_captured.isoformat()
        pending = self._pending
        row = {
            "shot_id": pending.shot_id,
            "pre_event_frame": pending.pre_event_frame,
            "pre_event_captured_at_utc": pending.pre_event_captured_at_utc,
            "external_event_acknowledged_at_utc": acknowledged.isoformat(),
            "outcome_recorded_at_utc": recorded.isoformat(),
            "target_distance_m": str(pending.target_distance_m),
            "commanded_yaw_degrees": str(pending.commanded_yaw_degrees),
            "commanded_pitch_degrees": str(pending.commanded_pitch_degrees),
            "predicted_yaw_offset_degrees": (
                ""
                if pending.predicted_yaw_offset_degrees is None
                else str(pending.predicted_yaw_offset_degrees)
            ),
            "outcome": outcome,
            "impact_x_mm": "" if impact_x is None else str(impact_x),
            "impact_y_mm": "" if impact_y is None else str(impact_y),
            "post_event_evidence": post_path,
            "post_event_captured_at_utc": post_captured_at,
            "notes": notes,
        }
        attempt_path = self.partial_path / "evidence" / pending.shot_id / "attempt.json"
        temporary_attempt_path = attempt_path.with_suffix(".json.tmp")
        temporary_attempt_path.write_text(
            json.dumps({"status": "completed", "row": row}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary_attempt_path.replace(attempt_path)
        self._rows.append(row)
        self._pending = None

    def finalize(self) -> Path:
        if self._finalized:
            raise RuntimeError("shot run is already finalized")
        if self._pending is not None:
            raise RuntimeError("cannot finalize while a shot needs an outcome")
        if not self._rows:
            raise ValueError("cannot finalize an empty shot run")

        csv_path = self.partial_path / "shot_results.csv"
        with csv_path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=SHOT_RUN_COLUMNS)
            writer.writeheader()
            writer.writerows(self._rows)
        files = [
            {
                "path": path.relative_to(self.partial_path).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(self.partial_path.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "schema_version": SHOT_RUN_SCHEMA,
            "run_id": self.run_id,
            "created_at_utc": self._created_at_utc,
            "finalized_at_utc": _timestamp(),
            "source_host": socket.gethostname(),
            "manual_axis_control": {
                "enabled": True,
                "axes": ["yaw", "pitch"],
                "origin": "local_keyboard",
                "automatic_aiming": False,
            },
            "external_event_only": True,
            "operator_event_contract": (
                "the evaluated event occurs outside this program; timestamps record camera "
                "capture and operator acknowledgment, not sensed event activity"
            ),
            "shot_count": len(self._rows),
            "canonical_frame_height": self._canonical_shape[0],
            "canonical_frame_width": self._canonical_shape[1],
            "image_encoding": "lossless PNG containing canonical RGB pixels",
            "target_coordinate_system": self.target_coordinate_system,
            "preprocessing": self.preprocessing.to_manifest(),
            "calibration": {
                "calibration_id": self.calibration_id,
                "reference": (
                    None
                    if self.calibration_reference is None
                    else self.calibration_reference.to_manifest()
                ),
            },
            "model_references": [item.to_manifest() for item in self.model_references],
            "files": files,
        }
        (self.partial_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.partial_path.rename(self.completed_path)
        self._finalized = True
        return self.completed_path


def _verify_reference(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    try:
        ArtifactReference(
            reference_id=str(value["reference_id"]),
            filename=str(value["filename"]),
            bytes=int(value["bytes"]),
            sha256=str(value["sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {error}") from error


def verify_shot_run(bundle: Path) -> dict[str, Any]:
    """Verify structure, hashes, chronology, rows, and evidence of one run."""

    bundle = bundle.expanduser().resolve()
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest.json must be an ordinary file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SHOT_RUN_SCHEMA:
        raise ValueError(f"unsupported shot run schema: {manifest.get('schema_version')}")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not SHOT_RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid shot run ID: {run_id}")
    if bundle.name != run_id:
        raise ValueError("bundle directory and shot run ID differ")
    manual_axis_control = manifest.get("manual_axis_control")
    if manual_axis_control != {
        "enabled": True,
        "axes": ["yaw", "pitch"],
        "origin": "local_keyboard",
        "automatic_aiming": False,
    }:
        raise ValueError("shot run does not declare the manual axis-control contract")
    if manifest.get("external_event_only") is not True:
        raise ValueError("shot run does not declare the external-event contract")
    created = _parse_timestamp("created_at_utc", manifest.get("created_at_utc"))
    finalized = _parse_timestamp("finalized_at_utc", manifest.get("finalized_at_utc"))
    if finalized < created:
        raise ValueError("shot run finalization precedes creation")
    preprocessing = PreprocessingSpec.from_mapping(manifest.get("preprocessing", {}))
    if not str(manifest.get("target_coordinate_system", "")).strip():
        raise ValueError("target coordinate system is missing")
    try:
        height = int(manifest["canonical_frame_height"])
        width = int(manifest["canonical_frame_width"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid canonical frame geometry") from error
    if height < 1 or width < 1:
        raise ValueError("invalid canonical frame geometry")

    calibration = manifest.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("calibration binding must be an object")
    calibration_id = calibration.get("calibration_id")
    if calibration_id is not None and not str(calibration_id).strip():
        raise ValueError("calibration ID cannot be blank")
    if calibration.get("reference") is not None:
        _verify_reference(calibration["reference"], "calibration reference")
    models = manifest.get("model_references")
    if not isinstance(models, list):
        raise ValueError("model references must be a list")
    for index, reference in enumerate(models):
        _verify_reference(reference, f"model reference {index}")
    model_ids = [reference["reference_id"] for reference in models]
    if len(model_ids) != len(set(model_ids)):
        raise ValueError("model reference IDs must be unique")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("shot run manifest contains no files")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid shot run file entry")
        name = entry.get("path")
        relative = _relative_file(name) if isinstance(name, str) else None
        if relative is None:
            raise ValueError(f"invalid shot run file path: {name}")
        if name in expected:
            raise ValueError(f"duplicate shot run file path: {name}")
        expected.add(name)
        path = bundle / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsupported shot run file: {name}")
        if path.stat().st_size != entry.get("bytes") or _sha256(path) != entry.get("sha256"):
            raise ValueError(f"shot run file integrity failed: {name}")
    all_paths = list(bundle.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise ValueError("shot run bundle contains a symbolic link")
    if any(not path.is_file() and not path.is_dir() for path in all_paths):
        raise ValueError("shot run bundle contains a non-regular filesystem object")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in all_paths
        if path.is_file() and path.relative_to(bundle).as_posix() != "manifest.json"
    }
    if actual != expected:
        raise ValueError("shot run files do not exactly match the manifest")

    csv_path = bundle / "shot_results.csv"
    with csv_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != SHOT_RUN_COLUMNS:
            raise ValueError("invalid shot results CSV header")
        rows = list(reader)
    if not rows or len(rows) != manifest.get("shot_count"):
        raise ValueError("shot result count does not match the manifest")
    ids = [row["shot_id"] for row in rows]
    if ids != [f"shot-{index:06d}" for index in range(1, len(rows) + 1)]:
        raise ValueError("shot IDs must be unique and sequential")

    evidence_paths: set[str] = set()
    previous_recorded = created
    import cv2

    for row in rows:
        captured = _parse_timestamp("pre_event_captured_at_utc", row["pre_event_captured_at_utc"])
        acknowledged = _parse_timestamp(
            "external_event_acknowledged_at_utc",
            row["external_event_acknowledged_at_utc"],
        )
        recorded = _parse_timestamp("outcome_recorded_at_utc", row["outcome_recorded_at_utc"])
        if not captured <= acknowledged <= recorded:
            raise ValueError(f"invalid shot chronology: {row['shot_id']}")
        if captured < previous_recorded or recorded > finalized:
            raise ValueError(f"shot falls outside run chronology: {row['shot_id']}")
        previous_recorded = recorded
        distance = _finite("target_distance_m", row["target_distance_m"])
        if distance <= 0:
            raise ValueError("target distance must be positive")
        _angle("commanded_yaw_degrees", row["commanded_yaw_degrees"])
        _angle("commanded_pitch_degrees", row["commanded_pitch_degrees"])
        if row["predicted_yaw_offset_degrees"]:
            _finite("predicted_yaw_offset_degrees", row["predicted_yaw_offset_degrees"])
        if row["outcome"] not in {"hit", "miss", "invalid"}:
            raise ValueError(f"invalid shot outcome: {row['outcome']}")
        impacts = (row["impact_x_mm"], row["impact_y_mm"])
        if bool(impacts[0]) != bool(impacts[1]):
            raise ValueError("impact coordinates must both be present or both be absent")
        if impacts[0]:
            _finite("impact_x_mm", impacts[0])
            _finite("impact_y_mm", impacts[1])
        attempt_path = bundle / "evidence" / row["shot_id"] / "attempt.json"
        if not attempt_path.is_file():
            raise ValueError(f"attempt record is missing: {row['shot_id']}")
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        expected_attempt = {"status": "completed", "row": row}
        if attempt != expected_attempt:
            raise ValueError(f"attempt record and shot row differ: {row['shot_id']}")
        paths = [row["pre_event_frame"]]
        if row["post_event_evidence"]:
            paths.append(row["post_event_evidence"])
            post_captured = _parse_timestamp(
                "post_event_captured_at_utc", row["post_event_captured_at_utc"]
            )
            if not acknowledged <= post_captured <= recorded:
                raise ValueError(f"invalid post-event chronology: {row['shot_id']}")
        elif row["post_event_captured_at_utc"]:
            raise ValueError("post-event capture time requires a post-event evidence image")
        for name in paths:
            relative = _relative_file(name)
            if name in evidence_paths:
                raise ValueError(f"evidence file is reused: {name}")
            evidence_paths.add(name)
            image = cv2.imread(str(bundle / relative), cv2.IMREAD_COLOR)
            if image is None or image.shape != (height, width, 3):
                raise ValueError(f"invalid evidence image geometry: {name}")
    manifested_evidence = {
        name
        for name in expected
        if name.startswith("evidence/") and name.endswith(".png")
    }
    if evidence_paths != manifested_evidence:
        raise ValueError("shot rows and manifested evidence differ")

    return {
        "schema_version": SHOT_RUN_REPORT_SCHEMA,
        "run_id": run_id,
        "shot_count": len(rows),
        "outcomes": {
            outcome: sum(row["outcome"] == outcome for row in rows)
            for outcome in ("hit", "miss", "invalid")
        },
        "preprocessing": preprocessing.to_manifest(),
        "source_manifest_sha256": _sha256(manifest_path),
        "status": "passed",
    }
