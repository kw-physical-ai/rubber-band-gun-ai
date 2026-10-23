# Pre-device readiness

The repository completes every hardware-independent gate automatically while keeping calibration, axis movement, and the evaluated event behind explicit human decisions. CI and model output cannot move hardware or perform the event.

## Prerequisites and stop condition

Run repository commands from the checkout root with Python 3.10 or newer after the virtual-environment setup in the root [README](../README.md). Pi access, Drive sharing, and the `project-drive` rclone alias must already follow [GitHub, Colab, and Pi connection](github-colab-pi.md) and [Pi direct Drive upload](pi-drive-upload.md). The local `configs/pi.toml` is copied from `configs/pi.example.toml` and is never committed.

Yaw is the learned correction in the current model. Pitch is recorded and mechanically bounded but is not predicted. A manual-axis shot-run evidence manifest and verifier now exist, but they do not constitute a physical-safety procedure or authorize an external event. The evaluator permits only local keyboard control of calibrated yaw and pitch; event actuation remains outside the repository.

## One-command gate

From an installed development environment, run:

```bash
python scripts/verify-pre-device.py
```

The same command runs in pull requests, `main` pushes, and before an evaluation deployment. It performs Ruff, the hardware-free pytest suite, Python compilation, notebook cleanliness checks, repository policy and secret-pattern checks, Git LFS/model-manifest pairing, and source checks for the Pi evaluator boundary. Policy tests prove that only calibrated, settled, local-keyboard yaw/pitch movement is accepted and that model, remote, or extra-axis input is rejected. Success ends with `pre-device gate passed`. These static and fake-input checks support the boundary but cannot prove external services, credentials, untracked code, wiring, or the physical adapter.

Passing this gate proves software structure and contracts only. It does not prove camera geometry, human labels, model accuracy, servo direction, latency, or physical safety.

The gate checks that the shot-run evaluator exposes only its manual yaw/pitch boundary and that preview and evidence modules remain actuator-free. Its CPU tests construct, verify, and tamper with synthetic run bundles; they do not move hardware or perform a physical event. After an independently approved physical procedure exists, evaluator usage and the evidence contract are documented in [Data contracts](data-contract.md#shot-run-bundle).

If the untracked course models are present locally, inspect their archive metadata and record their hashes before uploading them to the shared Drive `reference-models/` directory:

```bash
python scripts/check-reference-models.py \
  --yolo physical-ai/yolo_target.pt \
  --yaw physical-ai/best_yaw_cnn.pth
```

This inspection disassembles metadata without executing pickle bytecode and prints `structure-passed-runtime-load-not-executed` plus both hashes. Runtime checks and the Colab baseline must load only the team-approved course files whose hashes were recorded by this inspection; isolation does not make an unknown checkpoint trustworthy.

To execute a local runtime smoke test as well, first install `requirements/base.txt`, then run:

```bash
python scripts/check-reference-runtime.py \
  --yolo physical-ai/yolo_target.pt \
  --yaw physical-ai/best_yaw_cnn.pth
```

This loads both models on CPU, sends a synthetic box through the yaw CNN, and sends a blank frame through YOLO. Success prints `status: passed`. It proves framework compatibility, not model accuracy.

## Hardware-ready sequence

1. With axis power unavailable, run the collector without `--enable-motion` and verify camera rotation and crop.
2. Follow [Yaw data collection](yaw-data-collection.md) to measure mechanical yaw/pitch limits in degrees, record a stable calibration ID and fixed visual aiming reference in ignored `configs/pi.toml`, then enable motion only for human-established yaw-correction capture.
3. Capture validation sessions across yaw positions, distances, lighting and backgrounds. Keep later independent sessions aside for locked test.
4. Stop `pigpiod`, remove the target from the scene, and capture independent negative examples:

   ```bash
   python scripts/pi/capture-no-target.py \
     --config configs/pi.toml \
     --output-root "$HOME/evaluation-captures"

   python scripts/check-no-target-capture.py \
     "$HOME/evaluation-captures/no-target-<UTC>"

   bash "$HOME/upload-drive-bundle.sh" \
     "$HOME/evaluation-captures/no-target-<UTC>" \
     project-drive:evaluation
   ```

5. Build the immutable yaw dataset with `notebooks/10_build_yaw_dataset.ipynb`. Here immutable means the builder refuses an existing ID and manifests bind every payload by SHA-256; Drive write permissions remain a team trust boundary.
6. Create the complete positive-frame annotation template, then have a reviewer who has not seen model predictions fill every box in resized model-input coordinates:

   ```bash
   python scripts/create-target-annotation-template.py \
     --dataset /path/to/processed/dataset-id \
     --split validation \
     --output /path/to/target_annotations.csv \
     --image-output /path/to/model-sized-annotation-images
   ```

7. Before viewing predictions, record the metric definitions and thresholds from [Data contracts](data-contract.md) in a GitHub Issue. Run `notebooks/20_evaluate_baseline.ipynb` to create and verify an immutable baseline run. A complete run ends with the run verifier report and a `passed`, `failed`, or `incomplete` gate status; `incomplete` is never acceptance.
8. On the Pi, inspect live overlays without motion:

   ```bash
   python -m pip install ultralytics==8.4.19

   python scripts/pi/preview-target.py \
     --model /path/to/yolo_target.pt \
     --confidence 0.15 \
     --tile-grid 2 \
     --tile-overlap 0.2

   python scripts/pi/preview-inference.py \
     --config configs/pi.toml \
     --yolo-model /path/to/yolo_target.pt \
     --yaw-model /path/to/best_yaw_cnn.pth
   ```

   Install the Pi-compatible PyTorch and torchvision builds before installing Ultralytics.
   The target-only preview uses one full-frame inference plus a 2×2
   overlapping tile pass. This costs more latency than one inference but preserves small target
   detail. Measure frame time on the actual Pi before choosing between `--tile-grid 2` and the
   faster `--tile-grid 1`. Press Q or Escape to stop. For a display-free check, pass `--headless`
   with a positive `--frames` value; annotated frames are then written under `--output-dir`.

   A recorded folder can be diagnosed on a development machine before Pi deployment:

   ```bash
   python scripts/analyze-target-images.py \
     --images /path/to/recorded-images \
     --model physical-ai/yolo_target.pt \
     --output /path/to/target-analysis \
     --confidence 0.15 \
     --tile-grid 2
   ```

   The analyzer scans supported images directly inside the folder in filename order. It writes
   detected-frame overlays, `predictions.csv`, `contact-sheet.jpg`, and `summary.json`. The report
   status is `diagnostic-unlabeled`: detection counts without independently reviewed boxes are not
   recall, precision, or model acceptance evidence. A non-empty output directory is rejected unless
   `--overwrite` is supplied, and overwrite is allowed only for a folder containing this analyzer's
   valid prior `summary.json`.

9. Keep the existing models if all gates pass. Correct calibration for a stable bias. Add yaw training only for position/session-dependent yaw error, and YOLO training only for target recall or false-positive failure.

Locked test remains closed until the candidate model hashes and thresholds are frozen. The evaluation command requires a second-person approver and Issue/PR reference. Live movement and supervised hit/miss evaluation remain separate work after the hardware and safety procedure exist.
