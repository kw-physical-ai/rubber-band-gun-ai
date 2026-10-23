# Rubber Band Gun AI - development setup plan

이 문서는 장기 설계와 안전 경계를 설명합니다. 팀의 현재 실행 순서와 구현 상태는 [프로젝트 워크플로](project-workflow.md)를 기준으로 합니다.

## 1. Goal and operating boundary

Build one reproducible workflow for:

1. collecting camera and yaw-label data on the Raspberry Pi,
2. training YOLO and the yaw-regression CNN in Google Colab,
3. promoting versioned model artifacts,
4. deploying inference code and selected artifacts back to the Pi over Tailscale,
5. recording supervised outcomes while the evaluated event remains external to the software.

The permitted target is an inanimate course target in a controlled test area. People, animals, and uncontrolled environments are out of scope. Software may move only the calibrated yaw and pitch axes after deliberate local keyboard input. Model output, remote input, process startup, and reconnect cannot command movement.

The evaluated event is outside the repository and is performed independently while the evaluator is paused. The repository contains no event-actuation interface or sequence. A software stop and a physical axis-power cutoff must both be available during live axis tests.

## 2. What the course material implements

The reference pipeline is:

```text
Pi camera + manual WASD control
  -> image files + data_angles.csv(yaw_offset)
  -> YOLO target detection in Colab
  -> rectangle mask at 224 x 224
  -> four-layer CNN yaw regression
  -> best_yaw_cnn.pth + yaw min/max
  -> Pi evaluator: human moves calibrated yaw/pitch, Space stores pre-event evidence
```

The example configuration includes yaw and pitch pins and centers, but its zero-width bounds intentionally prevent motion. The actual assembly's two axes must be calibrated and stored in the ignored device configuration.

The supplied YOLO notebook contains a plaintext example Roboflow API key and explicitly expects students to replace it. Do not use or copy that example value. Create this project's own Roboflow project/key and access it only through Colab Secrets or an environment variable.

### Baseline completeness decision

The reference material is a complete course prototype, not a verified deployment for the current assembly. Both Python entry points pass syntax compilation, and the supplied yaw checkpoint contains the expected model state plus `image_size=224` and a `yaw_min/yaw_max` range of -18 to +18 degrees. However:

- collection saves the full rotated frame, while live inference removes 20% of the rotated frame before resize;
- the training notebook resizes saved frames without reproducing the inference crop;
- collection clamps servos only to 0-180 degrees, while inference applies a narrower 32-68 degree yaw limit;
- the checkpoint has no independently held-out result for this camera mounting, target distance, lighting, or mechanical calibration;
- the notebook randomly splits individual frames, so adjacent burst frames can enter both training and validation.

Do not begin with a full new training-data collection. First reconcile preprocessing and collect a small, non-firing diagnostic set on the actual assembly across the supported yaw range, distances, lighting conditions, and no-target scenes. Evaluate YOLO target recall/false positives and CNN yaw error against known servo/target positions. Then choose the smallest response:

1. both models pass: keep the supplied models and calibrate only configuration/alignment;
2. YOLO passes but yaw has a consistent bias: adjust calibration, not training data;
3. YOLO passes but yaw error varies by position/session: collect yaw data and retrain the CNN only;
4. YOLO fails on the actual target/environment: collect detection annotations and retrain YOLO, then reassess the CNN.

## 3. Repository boundaries

The current directory roles are documented in the root [README](../README.md). Shared Python code belongs in `src/`, hardware-facing entry points in `scripts/pi/`, reproducible Colab sources in `notebooks/`, and hardware-free verification in `tests/`.

Do not commit raw camera images, generated datasets, notebook outputs, credentials, local configuration, arbitrary training runs, course reference files under `physical-ai/`, or machine-specific access details.

## 4. Phased implementation

### Phase 0 - protect inputs and defer optional training services

- Do not reuse the course notebook's example Roboflow value.
- Name owners for the GitHub repository, Pi administration, model acceptance, and release approval.
- Use the existing shared Drive folder for smoke data and diagnostic captures. Create a project-owned Roboflow resource only if the baseline decision requires detection retraining; at that point, name its owner and store `ROBOFLOW_API_KEY` in Colab Secrets. Store any required fine-grained read-only GitHub token there as well.
- Keep `.env`, local TOML configuration, datasets, training outputs, and caches ignored.
- Preserve only sanitized example configuration in Git.

Exit gate: secret scanning finds no live credentials in files to be committed.

### Phase 1 - team collaboration model

- Add all four students as organization members with the same repository `Write` permission. This is sufficient to create branches, open pull requests, review, and merge.
- Keep at least two organization owners for account continuity; owner status is an administrative responsibility, not a different development workflow.
- Use short-lived branches and pull requests into `main`. Any member may open or merge a pull request.
- Require pull requests and a successful `python` CI job by team convention wherever repository rules cannot enforce them. Do not make the course repository public merely to obtain enforcement.
- Record hardware experiments and model evaluations as Issues that reference the code commit, hardware revision, model hash, dataset/run ID, result, and next decision.
- Use one organization Project with `Backlog`, `Ready`, `In Progress`, `Hardware Blocked`, `Review`, and `Done` states.
- Treat `main` as the integration branch and the source for evaluation releases. Deployment is manually dispatched at first; automatic deployment after merge is enabled only after version switching and rollback have been tested. Neither mode may move an axis or perform the evaluated event.

### Phase 2 - convert scripts into a testable package

- Move shared model, image-processing, servo, and configuration logic into `src/rubber_band_gun/`.
- Keep the two command-line entry points small: one for collection and one for inference.
- Import `pigpio` and `picamera2` only in Raspberry-Pi adapters so CPU-only tests and Colab imports work.
- Represent camera and servo access behind small interfaces; use fakes in tests.
- Put all pins, angle bounds, direction, camera crop, confidence, cooldown, and alignment offset in validated TOML configuration.
- Define the yaw-label contract in `docs/data-contract.md`: degrees, sign/reference frame, valid range, required CSV columns, capture ID, timestamp/file matching, and rejected-capture handling.
- Define no-detection, multi-detection, confidence, stale-frame, mechanical-limit, and oscillation behavior before connecting servos.
- Use one shared preprocessing implementation where possible. Cover crop/rotation, resize/interpolation, color order, mask construction, normalization, and numeric precision with golden fixtures and an explicit equality/tolerance rule.
- Add structured run metadata: Git commit, data-manifest hash, package versions, model metrics, and calibration version.

Exit gate: preprocessing and controller tests run on macOS/Linux without Pi hardware, and invalid/out-of-range commands cannot reach the servo adapter.

### Phase 3 - inventory and prepare the Raspberry Pi runtime

For class exercises, connect through Tailscale and use the existing shared password. Team members who only work in GitHub or Colab do not need separate Pi SSH setup. The GitHub Actions pipeline uses one separate deploy-only service key; team members do not copy or share that private key.

Keep the runtime username, Tailscale hostname or IP, and release path in local shell variables or GitHub repository variables rather than this repository. Use an explicit `user@host` SSH target and do not expose port 22 publicly or share a private SSH key among team members.

After access works, inventory before installing anything:

```bash
uname -a
cat /etc/os-release
python3 --version
getconf LONG_BIT
df -h /
tailscale status
systemctl status pigpiod --no-pager
```

Then:

- Install OS-provided camera/GPIO packages appropriate to the detected Raspberry Pi OS release.
- Create one project virtual environment; if `picamera2` is OS-provided, create it with system site packages rather than installing an incompatible wheel.
- Clone the repository using a deploy key or a fine-grained read-only credential, not a personal broad-scope token.
- Add the runtime user to only the required hardware groups.
- Run camera, individual-servo, limit, and emergency-stop checks before loading a model.
- Keep axis power unavailable for camera/model-only tests. Enable yaw/pitch motion only for an attended, calibrated manual-axis test.
- Reconcile collection/training/inference preprocessing before judging either supplied model.
- Capture a diagnostic evaluation set rather than a training set first. Keep it out of later training so it remains an independent baseline check.
- Run inference in log/overlay-only mode: record detections, confidence, predicted yaw, expected yaw, and latency without sending movement commands.
- If a systemd service is added, keep it preview-only; manual axis movement remains an attended command-line operation.

Exit gate: camera preview and dry-run aiming work; no unattended startup or reconnection path can move either axis.

### Phase 4 - make Colab reproducible

Keep notebooks in GitHub and add an "Open in Colab" badge to the README. A notebook opened from GitHub does not make the repository package or data automatically available in the runtime, so its setup section must explicitly:

1. authenticate to the private repository using a Colab Secret,
2. clone or update the repository at a chosen commit/tag,
3. install pinned packages from `requirements/colab.txt`,
4. mount the selected Drive data folder,
5. read dataset paths from configuration instead of fixed `/content` assumptions,
6. save checkpoints, metrics, and a run manifest outside the ephemeral VM.

Secret-reading cells must fail closed when a secret is unavailable and must never print tokens or embed them in clone URLs that appear in notebook output.

Recommended Drive layout:

```text
rubber-band-gun-ai-data/
├── pi-upload/
│   ├── raw/<capture-id>/images/
│   ├── raw/<capture-id>/data_angles.csv
│   └── smoke/<capture-id>/
├── processed/<dataset-version>/
└── runs/<run-id>/
```

The Pi uploader owns `pi-upload/`; Colab reads that ingress and writes only `processed/` and `runs/`. Each raw capture is immutable. Generate a manifest containing filename, size/hash, yaw label, capture ID, and train/validation/test split. Split by capture session, not only by random image, to reduce leakage between near-identical consecutive frames. Lock a test set captured in later, independent sessions with different target positions, distances, and lighting; do not use it for model or threshold selection.

Pin direct dependencies in the repository because Colab runtimes and preinstalled packages change. Do not depend on notebook execution order that is invisible to a clean runtime.

Exit gate: a fresh Colab runtime can run top-to-bottom from a documented data version and produce the same artifact schema without manual drag-and-drop.

### Colab-to-GitHub promotion flow

Colab never connects directly to the Pi. Each team member authenticates Colab with their own fine-grained, repository-scoped GitHub credential stored in that member's Colab Secrets; credentials are never shared between members or saved in notebook output.

```text
GitHub notebook/code at commit X
  -> Colab clones commit X
  -> Drive supplies versioned data
  -> Colab writes model + metrics + manifest
  -> contributor pushes a model-candidate branch
  -> pull request compares metrics and artifact metadata
  -> merge to main marks the artifact deployable
```

Candidate pull requests contain the notebook/code changes, a Git LFS pointer for the selected model, and a JSON manifest. Raw data, intermediate checkpoints, and full notebook output remain in Drive and are referenced by run ID/hash.

### Phase 5 - model promotion and Pi deployment

- Keep raw/processed datasets and run checkpoints outside Git.
- Track only intentionally promoted `.pt`/`.pth` artifacts with Git LFS. The canonical release record is a versioned JSON manifest in Git containing the Git tag/commit, LFS object hash, SHA-256, data-manifest hash, calibration version, input/preprocessing schema, yaw scale, dependency lock identifier, and metrics.
- Before training, define promotion thresholds from the calibrated servo resolution, target angular size at the farthest supported distance, and allowed alignment error. Never deploy based only on training loss.
- Promotion requires validation yaw MAE, locked-test yaw MAE, target recall, no-target false-positive rate, recorded-frame end-to-end alignment error, and all safety fault tests. Model selection uses validation data; only the final candidate is evaluated on the locked test set.
- Deploy a tagged commit and matching model manifest through `scripts/deploy-eval.sh` using SSH/rsync.
- Verify SHA-256 hashes on the Pi before activation.
- Install releases under a configured release root in `releases/<tag>`, switch a `current` symlink only after verification, and retain the previous known-good release. Rollback stops the service, repoints `current`, verifies the manifest/hash, and restarts preview-only.

Use a push-based GitHub Actions deployment with GitHub as the control point:

```text
merge to main
  -> hosted GitHub runner checks out code and Git LFS artifacts
  -> CPU tests and manifest/hash checks
  -> official Tailscale GitHub Action joins as ephemeral tag:ci
  -> deploy-only SSH key connects to the configured Pi account
  -> rsync uploads releases/<commit-sha>
  -> Pi-side fixed deployment command verifies and activates the release
  -> health check; otherwise rollback
```

Automation credentials are service credentials, separate from the shared class password and every student's personal SSH key:

- Prefer Tailscale workload identity federation when the installed Tailscale version supports it; otherwise use a tag-restricted OAuth client stored as a GitHub secret.
- Tailnet policy allows `tag:ci` to reach only the Pi's SSH port.
- Store one deploy-only SSH private key in GitHub Actions secrets and its public key on the Pi. Do not use a student's personal key or the shared password.
- The deploy user can write only versioned release directories and invoke one root-owned activation script through a narrow sudo rule.
- Do not install a persistent GitHub self-hosted runner on the Pi.

While hardware is incomplete, the automatic target is an evaluation release only: dependencies, code, configuration, and accepted reference/candidate models are synchronized, but the launched command is log/overlay-only and has no actuator access. After hardware and safety gates pass, an attended local process may enable bounded yaw/pitch movement. No workflow performs the evaluated event.

Exit gate: the deployed code commit, model hash, configuration, and training run can be traced to one release/tag.

### Phase 6 - continuous integration

On pull requests, run CPU-only checks:

- formatting/linting,
- type checking,
- unit tests,
- notebook syntax/clean-output checks,
- secret scanning,
- checks that forbidden data/config paths are absent and promoted weights are Git LFS pointers with matching manifests.

Hardware-in-the-loop checks stay on the Pi and are manually initiated with actuator power disconnected unless the test explicitly requires it. Hosted CI receives no Pi/Tailscale credentials, does not run on a hardware-attached runner, and cannot invoke the actuator entry point.

## 5. Recommended implementation order

1. Keep unaccepted reference model binaries and course material outside Git; use the organization repository as the source of shared code.
2. Sign in to the configured Pi runtime account and record OS, architecture, camera, GPIO, servo, power, and physical-cutoff details.
3. Use the shared preprocessing contract and GPIO-free overlay preview to inspect the actual camera field of view.
4. Copy the reference models directly to the Pi without treating them as promoted repository artifacts, then capture positive and no-target diagnostic sets.
5. Use the versioned dataset and immutable baseline-run tooling to evaluate the supplied YOLO and yaw CNN separately, then follow the baseline decision tree above.
6. Only if retraining is required, create the project-owned Roboflow resource and refactor the necessary collection/training path; continue using the established shared Drive layout.
7. Before live movement, write the full safety state machine and add fake-hardware/fault-injection tests.
8. Define calibration-derived acceptance thresholds, promote the accepted model/configuration, and deploy a versioned release.
9. Build the GitHub Actions/Tailscale deployment in evaluation-only mode, test version switching and rollback, and enable movement-capable deployment only after the hardware and safety gates pass.

## 6. Acceptance checklist

- [ ] `physical-ai/`, machine-specific access details, and credentials are absent from the tracked tree.
- [ ] Each contributor can fetch and push with their own repository-scoped credential.
- [ ] A fresh clone runs CPU-only imports/tests on macOS and Colab; Pi-only camera/GPIO features run on the documented Pi image.
- [ ] A fresh Colab runtime trains from a versioned dataset manifest.
- [ ] Training and Pi inference share preprocessing code or pass the same golden fixtures within the documented numeric tolerance.
- [ ] Every promoted model has a hash, metrics, yaw range, input schema, and source commit.
- [ ] Pi configuration enforces calibrated yaw/pitch bounds, step sizes, center positions, and settling delay.
- [ ] Policy tests prove model, remote, uncalibrated, unsettled, and extra-axis commands are rejected.
- [ ] Recorded-frame inference passes before live servo movement.
- [ ] Live manual aiming passes before any supervised outcome run begins.
- [ ] Deployment has a tested rollback path.

## 7. Current blockers and next decision

The remaining blocker is physical evidence from the actual assembly. The repository now provides the preprocessing contract, positive and no-target capture contracts, actuator-free baseline evaluator, immutable run and model-manifest validation, GPIO-free Pi preview, and one-command CI gate. When the hardware is available, inventory it, calibrate it, capture independent diagnostic sessions, freeze acceptance thresholds, and evaluate the supplied models. Retraining and movement-capable activation remain conditional on that result and the hardware safety gates.

References:

- Google Colab FAQ: https://research.google.com/colaboratory/faq.html
- Google Colab runtime versions: https://research.google.com/colaboratory/runtime-version-faq.html
- Google Colab Secrets example: https://colab.research.google.com/github/google-gemini/cookbook/blob/main/quickstarts/Authentication.ipynb
- GitHub repository limits: https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits
- Picamera2 manual: https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
- Tailscale SSH: https://tailscale.com/docs/features/tailscale-ssh
- Tailscale GitHub Action: https://tailscale.com/docs/integrations/github/github-action
- GitHub Actions secure use: https://docs.github.com/en/actions/reference/security/secure-use
