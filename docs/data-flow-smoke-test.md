# Data-flow smoke test

This test proves that a camera bundle can travel unchanged from the Pi through Tailscale and Google Drive into Colab. It detects accidental missing or modified files; it does not authenticate the source or validate image meaning, camera quality, labels, or model performance. The frames are unlabeled plumbing data, not training or model-evaluation data. No actuator module is imported and `pigpiod` must remain stopped.

Prerequisites are the working SSH/Tailscale, Colab private-repository access, and shared Drive setup in [GitHub, Colab, and Raspberry Pi connection](github-colab-pi.md). The Pi uses the existing `/home/t1-faker/venv` course environment. The Mac uses this repository's `.venv`.

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

## 2. Pull the bundle over Tailscale

Back on the Mac:

```bash
mkdir -p tmp/smoke
CAPTURE_ID='smoke-20260922T123456Z' # replace with the ID printed by the Pi
rsync -av \
  "t1-faker@100.94.55.34:/home/t1-faker/rbg-smoke/$CAPTURE_ID/" \
  "tmp/smoke/$CAPTURE_ID/"
```

Validate the new completed bundle before uploading it:

```bash
source .venv/bin/activate
python scripts/check-smoke-bundle.py "tmp/smoke/$CAPTURE_ID"
```

## 3. Move through Drive and Colab

Upload only `tmp/smoke/$CAPTURE_ID` as one intact directory under:

```text
MyDrive/rubber-band-gun-ai-data/smoke/
```

Open the latest `notebooks/00_environment_check.ipynb` from GitHub and run all cells. Its final cell verifies every file against the Pi manifest and writes:

```text
MyDrive/rubber-band-gun-ai-data/runs/data-flow-smoke/<capture-id>.json
```

The flow passes only when the Colab output and report both name the same `$CAPTURE_ID` printed by the Pi, `status` is `passed`, and both frame counts are `3`. A passed status means every listed file matched the Pi manifest by name, byte count, and SHA-256, with no extra files in the bundle. Delete smoke captures later from the Pi, Mac, and Drive if desired; never move them into `raw/` or a training dataset.
