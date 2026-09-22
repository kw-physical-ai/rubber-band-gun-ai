# Yaw data collection

This procedure collects camera frames and human-aligned yaw labels without firing. Preview-only mode does not import the motor driver or command an actuator. Motion-capable collection starts only after the yaw and pitch limits have been physically measured and recorded.

## 1. Put the collector on the Pi

Run the collector from a repository checkout because it imports the shared data-contract code. On the Pi:

```bash
git clone git@github.com:kw-physical-ai/rubber-band-gun-ai.git
cd rubber-band-gun-ai
source /home/t1-faker/venv/bin/activate
python -m pip install --no-deps -e .
cp configs/pi.example.toml configs/pi.toml
```

`--no-deps` preserves the working course environment, including its Raspberry Pi GUI-capable OpenCV build. Confirm `picamera2`, `pigpio`, `cv2`, and `numpy` still import before continuing.

The `project-drive` rclone remote and least-privilege upload folder must already be configured as described in [Pi direct Drive upload](pi-drive-upload.md). The uploader uses immutable remote writes and stops on a capture-ID collision rather than replacing an existing bundle.

## 2. Check the camera geometry without motion

Leave `calibrated = false`, then run:

```bash
python scripts/pi/collect-yaw-data.py --config configs/pi.toml
```

The window shows the exact rotated and cropped field of view that will be stored. Servo motion and labeled capture are disabled. Press `Esc` to exit. This preview does not create a dataset.

The shared `rbg-camera-preprocessing/v1` contract deliberately uses the inference-side geometry: rotate clockwise and remove the bottom 20% by default. The course collector preview, saved image, training notebook, and inference path do not use one consistent field of view, so an old checkpoint is not automatically compatible with newly collected frames. Evaluate it under this declared geometry before trusting it.

## 3. Calibrate before enabling motion

With the firing linkage physically disconnected, follow the assembly's approved mechanical calibration procedure to determine the yaw and pitch center, minimum, and maximum command angles without driving either axis into a hard stop. This software does not infer safe mechanical limits. Record the approved values in the ignored local file `configs/pi.toml`, give the calibration a stable ID, and describe the fixed visual reference that means “aligned.” The reference can be a reticle or another repeatable mark, but it must remain unchanged within a dataset version. Only then set `calibrated = true`.

Do not copy the example limits unchanged: their minimum and maximum both equal the center, so they intentionally allow no motion. This repository does not provide a firing command in the collector.

Motion mode also requires the Pi's `pigpiod` service. Start or inspect that service only after the firing linkage is disconnected; preview mode does not need it.

## 4. Collect one immutable session

```bash
python scripts/pi/collect-yaw-data.py \
  --config configs/pi.toml \
  --output-root /home/t1-faker/captures \
  --enable-motion
```

Controls are `A` to increase yaw, `D` to decrease yaw, `W` to increase pitch, `S` to decrease pitch, and `R` for the calibrated center. Each key press moves by the configured step. The screen blocks capture for the configured settling interval after every motion command. Once the target is aligned with the team's fixed aiming reference and the settling warning disappears, press `Space` once to save the current frame and commanded angles. The collector prints `Saved ...` for each accepted frame and writes `human-aligned`; it has no UI for creating `diagnostic` labels. These angles are servo setpoints, not measurements from a position sensor.

Press `Esc` to finalize the saved frames into one completed directory containing canonical images, `data_angles.csv`, and `manifest.json`. Successful finalization prints `Capture bundle ready: ...`; if no frames were accepted, it prints `No labeled frames captured` and creates no completed bundle. A crash leaves a hidden `.partial` directory; do not rename or upload it, and start a new session instead. Completed IDs use `capture-YYYYMMDDTHHMMSSZ`, so wait until the next second before restarting an ID that already exists.

Validate and upload the completed directory:

```bash
python scripts/check-yaw-capture.py /home/t1-faker/captures/capture-<UTC>
bash /home/t1-faker/upload-drive-bundle.sh \
  /home/t1-faker/captures/capture-<UTC> \
  project-drive:raw
```

The verifier checks file hashes, image geometry, timestamps, calibrated angle ranges, and the yaw-offset equation. A passing bundle proves internal data integrity, not label correctness or model accuracy.

After Drive is mounted in Colab, run the same semantic verifier against the uploaded copy:

```bash
!python scripts/check-yaw-capture.py \
  "/content/drive/MyDrive/rubber-band-gun-ai-data/pi-upload/raw/capture-<UTC>"
```

Only a bundle that passes on both the Pi and the Drive-mounted Colab path is eligible for analysis.

## 5. Keep firing evaluation separate

Yaw collection answers “what yaw offset did a human align for this frame?” It does not answer whether a rubber band hits. After the hardware and safety procedure are complete, a separate controlled test must record the exact pre-shot frame, model prediction, commanded angles, distance, and a `hit`, `miss`, or `invalid` result derived from post-shot target evidence rather than the prediction itself. Define the hit region before the run and use the `shot_results.csv` contract in [Data contracts](data-contract.md).
