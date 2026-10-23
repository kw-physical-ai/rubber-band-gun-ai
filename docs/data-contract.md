# Data contracts

The project keeps model-label collection separate from later shot-outcome evaluation. Yaw capture does not perform the evaluated event, and a shot result never silently becomes training data.

## Shared preprocessing

`rbg-camera-preprocessing/v1` defines the camera geometry used by collection, training, and inference:

1. input pixels are RGB `uint8`;
2. rotate 90 degrees clockwise;
3. remove the configured fraction from the bottom of the rotated frame;
4. store that canonical field of view in the capture bundle;
5. resize it to the configured model dimensions only when a model consumes it.

The default crop ratio is `0.2` and the default model size is `224 x 224`. Every capture manifest embeds the complete preprocessing definition. Training or inference must refuse a capture/model whose preprocessing schema does not match its configured schema.

This geometry follows the course inference example. The course collector preview removes the top 20% of the rotated frame but saves the full rotated frame, the course training notebook resizes that full frame, and inference removes the bottom 20%. Therefore an old checkpoint is not assumed compatible. A full uncropped source frame can be reprocessed under this schema, but an already cropped frame cannot recover discarded pixels.

## Yaw-label capture bundle

Schema: `rbg-yaw-capture/v2`

```text
capture-<UTC>/
├── images/
│   ├── frame_000000.jpg
│   └── ...
├── data_angles.csv
└── manifest.json
```

`data_angles.csv` columns:

| Column | Meaning |
| --- | --- |
| `filename` | File name below `images/` |
| `captured_at_utc` | Timezone-aware capture time |
| `yaw_degrees` | Yaw servo position when the frame was captured |
| `aligned_yaw_degrees` | Human-established yaw position that aligns the target for the same scene |
| `yaw_offset` | Required correction: `aligned_yaw_degrees - yaw_degrees` |
| `pitch_degrees` | Calibrated pitch servo position |
| `label_status` | `human-aligned` or `diagnostic` |

The angle fields are commanded servo setpoints in degrees, not sensor measurements of the physical shaft angle. Because the camera rotates with the barrel, the operator first aligns the target to the fixed aiming reference and marks that servo position. The operator then moves yaw away from that position and captures frames whose label is the correction required to return to the marked alignment. `human-aligned` means the correction label came from this human-established alignment; it does not mean the captured frame itself is already aligned. `diagnostic` is reserved for troubleshooting and is excluded from supervised training unless it is separately reviewed and promoted in a versioned dataset.

The manifest binds the capture ID, calibration ID, fixed aiming reference, yaw center, stored image geometry, preprocessing schema, frame count, file byte counts, and SHA-256 hashes. A completed bundle is immutable. Upload the entire directory to `project-drive:raw`; never append a later session to it. The operational procedure is in [Yaw data collection](yaw-data-collection.md).

## Shot-run bundle

Schema: `rbg-shot-run/v1`

```text
shot-run-<UTC>-<suffix>/
├── evidence/
│   └── shot-000001/
│       ├── attempt.json
│       ├── pre.png
│       └── post.png   # optional
├── shot_results.csv
└── manifest.json
```

`shot_results.csv` is reserved for supervised, physically controlled end-to-end evaluation after the hardware and safety gates pass. `scripts/pi/log-shot-run.py` permits only local keyboard movement of the calibrated yaw and pitch axes. It rejects uncalibrated or extra servo configuration, has no model-driven movement, and provides no external-event actuation. The operator performs the event independently while the program is paused and acknowledges completion before entering the outcome.

The live preview uses the versioned canonical rotation/crop. After the configured settling interval, Space atomically stores one attempt directory containing the lossless canonical pre-event image and `attempt.json` with the current commanded yaw/pitch. The evaluator then pauses for the independent event; Enter acknowledges completion, optional post-event capture occurs, and terminal prompts collect outcome, paired coordinates, and notes before live preview resumes. A/D move yaw, W/S move pitch, R returns both axes to their configured centers, and Esc publishes early only when at least one trial is complete. Every completed `hit`, `miss`, or `invalid` trial counts toward `--shots`, and reaching that limit publishes automatically.

| Column | Meaning |
| --- | --- |
| `shot_id` | Unique `shot-...` identifier |
| `pre_event_frame` | Relative path to the exact canonical pre-event PNG |
| `pre_event_captured_at_utc` | Timezone-aware camera capture time |
| `external_event_acknowledged_at_utc` | Time the operator confirmed the independent event was complete; not a sensed actuation time |
| `outcome_recorded_at_utc` | Time the outcome entry was recorded |
| `target_distance_m` | Measured target distance in metres |
| `commanded_yaw_degrees` | Yaw servo command in degrees |
| `commanded_pitch_degrees` | Pitch servo command in degrees |
| `predicted_yaw_offset_degrees` | Reserved model-output field; the manual evaluator leaves it blank and never uses it for movement |
| `outcome` | `hit`, `miss`, or `invalid` |
| `impact_x_mm`, `impact_y_mm` | Optional paired impact coordinates in millimetres under the run's declared target coordinate system |
| `post_event_evidence` | Optional relative path to a later canonical evidence PNG |
| `post_event_captured_at_utc` | Optional timezone-aware capture time paired with post-event evidence |
| `notes` | Manual context, including the invalid-shot reason |

The completed directory is published by atomic rename and cannot overwrite an existing run ID. Its manifest binds the preprocessing contract, declared coordinate system, calibration ID and content-addressed calibration/model references when supplied, canonical geometry, timestamps, row count, and byte count plus SHA-256 for the CSV and every evidence image. External references are bound by filename, size, and SHA-256 without copying large models into every run. `scripts/check-shot-run.py` rejects changed, missing, extra, reused, malformed, or chronologically inconsistent evidence.

“Immutable” here is a workflow property, not filesystem write protection or cryptographic authorship: completed IDs are never reused and later byte changes are detected against the manifest. A party able to rewrite both payload and manifest can create a new internally consistent bundle, so retain the verifier's `source_manifest_sha256` in the approved external evaluation record. Reference hashes identify the exact external bytes but the offline bundle verifier cannot prove those bytes are still available; retain referenced artifacts in the team's versioned model/calibration store.

The older `rubber_band_gun.shot_results` row helper remains for compatibility with standalone draft tables. It does not produce a `rbg-shot-run/v1` bundle and must not be used as new evaluation evidence.

Example evaluator and verifier commands:

```bash
python scripts/pi/log-shot-run.py \
  --config configs/pi.toml \
  --target-distance-m 2.0 \
  --shots 10 \
  --model-reference yaw-v3=/path/to/yaw.pth \
  --capture-post-evidence

python scripts/check-shot-run.py "$HOME/shot-runs/shot-run-<UTC>-<suffix>"

bash "$HOME/upload-drive-bundle.sh" \
  "$HOME/shot-runs/shot-run-<UTC>-<suffix>" \
  project-drive:evaluation
```

Esc before any completed trial exits without a completed bundle. An interruption after Space leaves `.<run-id>.partial` with the atomically stored attempt directory, including its pre-event frame and commanded axes; it is never reported as a completed run. Inspect that exact staging directory for recovery evidence, then archive or remove only that directory before choosing whether to repeat the run. The evaluator does not resume a partially observed physical sequence.

The verifier proves bundle integrity and contract consistency, not that the entered outcome is true. The `hit`, `miss`, or `invalid` result must come from post-event target evidence that does not use the model prediction as its source. Define the hit region before the run, preserve a target image or measured impact position for each shot where practical, and record the outcome before inspecting aggregate model performance. For a trusted evaluation, have a reviewer score retained evidence without seeing the model prediction. A locked shot-evaluation set is not used for tuning; tuning creates a new model version and requires a new locked run.

## Dataset splits

Split yaw data by capture ID, not by random individual frames. Frames within one burst are correlated and must remain in the same train, validation, or locked-test partition. If every split uses the same aligner and session conditions, the score may still share that bias; the final physical shot test supplies the independent outcome. Shot results remain evaluation evidence unless the team explicitly versions a later training dataset that includes them.

## Yaw dataset bundle

Schema: `rbg-yaw-dataset/v1`

```text
dataset-<version>/
├── images/
│   ├── train/
│   ├── validation/
│   └── locked-test/
├── labels.csv
└── dataset_manifest.json
```

Run `notebooks/10_build_yaw_dataset.ipynb` in Colab or `scripts/build-yaw-dataset.py` locally. The builder verifies every source capture before and after copying, checks copied image bytes against the source manifest, rejects preprocessing mismatches and capture IDs assigned to more than one split, and copies only `human-aligned` frames. It stages the complete directory before renaming it and never overwrites an existing dataset ID. Completed datasets are immutable by team convention; Drive itself does not enforce read-only files or filesystem-level atomicity.

`labels.csv` binds each copied image to its source capture, source filename, timestamp, split, angles, label status, and calibration ID. `dataset_manifest.json` records the builder Git commit and package version, preprocessing contract, source capture manifest hashes, capture IDs per split, included and excluded counts, per-split yaw-offset summary, and SHA-256 for every copied file. `scripts/check-yaw-dataset.py` verifies the completed dataset without requiring the raw folders.

The manifest proves provenance and internal consistency, not that a human alignment is correct or that a split has enough data. Validation-only datasets are allowed for baseline diagnosis. A training run must separately require the splits and condition coverage it needs. Keep `locked-test` empty during ordinary dataset iteration; add those capture IDs only after the candidate model and acceptance thresholds are fixed. If an interrupted runtime leaves `.<dataset-id>.partial`, inspect why it stopped and remove only that exact staging directory before retrying with the same ID.

## No-target evaluation capture

Schema: `rbg-no-target-capture/v1`

The Pi creates `no-target-<UTC>/` bundles containing raw RGB camera frames, `cases.csv`, and `manifest.json`. Every row is explicitly labeled `expected_target=false`. The operator must visually confirm that the declared course target is absent from the entire scene; hashes cannot prove label meaning. The bundle records the preprocessing contract and is rejected if it differs from the positive dataset used in the same baseline run.

Use `scripts/pi/capture-no-target.py` with `pigpiod` stopped, verify it with `scripts/check-no-target-capture.py`, and upload it to `project-drive:evaluation`. These frames are evaluation evidence and never enter a training dataset.

## Baseline evaluation run

Schema: `rbg-baseline-run/v1`

`scripts/evaluate-baseline.py` combines target-positive rows from one immutable yaw dataset split with one optional verified no-target bundle. A separate `target_annotations.csv` must cover every positive case exactly once with `case_id,box_x1,box_y1,box_x2,box_y2,annotated_by`; coordinates use the resized model-input geometry. Incomplete or extra target annotations are rejected before model loading. Target recall counts a prediction only when its bounding box reaches the frozen IoU threshold against this independent human annotation. It also records raw detection rate, no-target false-positive rate, yaw MAE, RMSE and signed bias. Missing target or no-target cases make the corresponding gate `incomplete`; they never silently pass.

Each `runs/<run-id>/` contains `predictions.csv`, `metrics.json`, and `run_manifest.json`. The manifest binds the Git commit, preprocessing contract, dataset manifest, target annotation file, both model files, every no-target image, runtime versions, thresholds and output hashes. A run directory is staged before publication and cannot overwrite an existing ID. `scripts/check-baseline-run.py` verifies the completed outputs.

Validation thresholds must be fixed before inspecting predictions. A `locked-test` invocation additionally requires an explicit opt-in, a second-person approver, and an Issue or PR reference; these are stored in the run manifest.

## Promoted model manifest

Schema: `rbg-model-manifest/v1`

A promoted `.pt` or `.pth` file in `models/` must have an adjacent `<artifact-name>.json` manifest. It binds the model ID and kind, artifact SHA-256, source run and Git commit, preprocessing contract, metrics, and approval record. `scripts/check-model-manifest.py` verifies the artifact, and the repository policy gate requires Git LFS plus the paired manifest for every tracked model.
