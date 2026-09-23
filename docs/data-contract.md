# Data contracts

The project keeps model-label collection separate from later shot-outcome evaluation. A yaw capture never fires the mechanism, and a shot result never silently becomes training data.

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

Schema: `rbg-yaw-capture/v1`

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
| `yaw_degrees` | Calibrated yaw servo position |
| `yaw_offset` | `yaw_degrees - yaw_center_degrees` |
| `pitch_degrees` | Calibrated pitch servo position |
| `label_status` | `human-aligned` or `diagnostic` |

The angle fields are commanded servo setpoints in degrees, not sensor measurements of the physical shaft angle. `human-aligned` means the operator deliberately aligned the target to the team's fixed aiming reference before capture. `diagnostic` is reserved for troubleshooting and is excluded from supervised training unless it is separately reviewed and promoted in a versioned dataset.

The manifest binds the capture ID, calibration ID, fixed aiming reference, yaw center, stored image geometry, preprocessing schema, frame count, file byte counts, and SHA-256 hashes. A completed bundle is immutable. Upload the entire directory to `project-drive:raw`; never append a later session to it. The operational procedure is in [Yaw data collection](yaw-data-collection.md).

## Shot-result table

`shot_results.csv` is reserved for supervised, physically controlled end-to-end evaluation after the hardware and safety gates pass. It records a unique shot ID, the exact pre-shot frame, distance, commanded angles, predicted offset, outcome, and optional impact coordinates.

| Column | Meaning |
| --- | --- |
| `shot_id` | Unique `shot-...` identifier |
| `captured_frame` | Relative path to the exact pre-shot image |
| `fired_at_utc` | Timezone-aware ISO 8601 timestamp |
| `target_distance_m` | Measured target distance in metres |
| `commanded_yaw_degrees` | Yaw servo command in degrees |
| `commanded_pitch_degrees` | Pitch servo command in degrees |
| `predicted_yaw_offset_degrees` | Model output before the shot |
| `outcome` | `hit`, `miss`, or `invalid` |
| `impact_x_mm`, `impact_y_mm` | Optional paired impact coordinates in millimetres under the run's declared target coordinate system |
| `notes` | Manual context, including the invalid-shot reason |

The current code defines and validates this table but cannot actuate the firing servo. A later firing application must require a local arm action and a separate local single-shot action, and it must link each result to an immutable capture/model/calibration version.

The current row schema does not yet carry that complete lineage. Before physical shot testing, add a versioned shot-run manifest that binds the table to the model hash, calibration ID, preprocessing schema, target coordinate system, and hashes of retained target evidence.

The `hit`, `miss`, or `invalid` result must come from post-shot target evidence that does not use the model prediction as its source. Define the hit region before the run, preserve a target image or measured impact position for each shot where practical, and record the outcome before inspecting aggregate model performance. A locked shot-evaluation set is not used for tuning; tuning creates a new model version and requires a new locked run.

## Dataset splits

Split yaw data by capture ID, not by random individual frames. Frames within one burst are correlated and must remain in the same train, validation, or locked-test partition. If every split uses the same aligner and session conditions, the score may still share that bias; the final physical shot test supplies the independent outcome. Shot results remain evaluation evidence unless the team explicitly versions a later training dataset that includes them.
