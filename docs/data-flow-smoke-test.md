# Data-flow smoke test

This test proves that a camera bundle can travel unchanged from the Pi into Google Drive and Colab. Tailscale provides remote access to start and inspect the Pi-side work; the data upload itself uses HTTPS to Drive. The test detects accidental missing or modified files; it does not authenticate the source or validate image meaning, camera quality, labels, or model performance. The frames are unlabeled plumbing data, not training or model-evaluation data. No actuator module is imported and `pigpiod` must remain stopped.

Prerequisites are the working SSH/Tailscale, Colab private-repository access, shared Drive setup in [GitHub, Colab, and Raspberry Pi connection](github-colab-pi.md), and the one-time [Pi direct Drive upload](pi-drive-upload.md) setup. The Pi uses the existing `/home/t1-faker/venv` course environment.

## 1. Copy and run the capture script

From the Mac repository root:

```bash
scp scripts/pi/capture-smoke.py t1-faker@100.94.55.34:/tmp/capture-smoke.py
ssh t1-faker@100.94.55.34
```

On the Pi, activate the existing course venv and capture three frames:

```bash
source /home/t1-faker/venv/bin/activate
python /tmp/capture-smoke.py --output-root /home/t1-faker/rbg-smoke
```

Point the camera only at a non-sensitive scene. The script refuses to run if a `pigpiod` process is active. Its final line prints the completed `smoke-<UTC timestamp>` directory; copy that capture ID exactly. If capture fails, leave the hidden `.partial` directory out of every transfer and retry because it is not a completed bundle.

## 2. Upload the bundle directly to Drive

Copy the uploader script from the Mac once:

```bash
scp scripts/pi/upload-drive-bundle.sh \
  t1-faker@100.94.55.34:/home/t1-faker/upload-drive-bundle.sh
```

On the Pi, replace the example with the capture ID printed by the capture script:

```bash
CAPTURE_ID='smoke-20260922T123456Z'
bash /home/t1-faker/upload-drive-bundle.sh \
  "/home/t1-faker/rbg-smoke/$CAPTURE_ID" \
  project-drive:smoke
```

The command must end with `Drive upload verified`. It keeps the local Pi bundle read-only and publishes `manifest.json` last. If it stops earlier, follow the interrupted-upload recovery procedure in [Pi direct Drive upload](pi-drive-upload.md).

## 3. Verify in Colab

Open the latest `notebooks/00_environment_check.ipynb` from GitHub and run all cells. When prompted, paste the exact `$CAPTURE_ID` printed by the Pi. The final cell fails if that directory is absent or invalid; otherwise it verifies every file against the Pi manifest and writes:

```text
MyDrive/rubber-band-gun-ai-data/runs/data-flow-smoke/<capture-id>.json
```

The source bundle appears at `MyDrive/rubber-band-gun-ai-data/pi-upload/smoke/<capture-id>`. The flow passes only when the Colab output and report both name the same `$CAPTURE_ID` printed by the Pi, `status` is `passed`, and both frame counts are `3`. A passed status means every listed file matched the Pi manifest by name, byte count, and SHA-256, with no extra files in the bundle. Delete smoke captures later from the Pi and Drive if desired; never move them into `raw/` or a training dataset.
