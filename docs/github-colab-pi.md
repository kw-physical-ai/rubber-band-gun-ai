# GitHub, Colab, and Raspberry Pi connection

## Current scope

The first connection is evaluation-only:

```text
GitHub main -> Colab environment check
GitHub main -> GitHub Actions -> Tailscale -> Pi release directory
```

Neither path starts a motor or firing process.

## GitHub collaboration

Work on short-lived branches, open a pull request into `main`, and merge only after the `python` CI job succeeds. The present GitHub plan cannot enforce branch protection on this private repository, so this is a team rule for now. Do not make the course repository public as a workaround.

## Colab

1. Create a fine-grained GitHub token for only `kw-physical-ai/rubber-band-gun-ai` with repository contents read access.
2. In Colab, open the Secrets panel and add it as `GITHUB_TOKEN`.
3. Sign in to GitHub in the browser, allow Colab access to private repositories when prompted, and then open `notebooks/00_environment_check.ipynb` from the README badge. The notebook secret cannot grant access to the notebook before it opens.
4. Run all cells in a fresh runtime.
5. Approve Drive mounting and verify these directories:
   - `MyDrive/rubber-band-gun-ai-data/pi-upload/raw`
   - `MyDrive/rubber-band-gun-ai-data/pi-upload/smoke`
   - `MyDrive/rubber-band-gun-ai-data/processed`
   - `MyDrive/rubber-band-gun-ai-data/runs`

The Pi-owned `pi-upload/` tree is created during [Pi direct Drive upload](pi-drive-upload.md) setup; do not create it from Colab or the Drive web UI. Use [the data-flow smoke test](data-flow-smoke-test.md) to send one unlabeled camera bundle through Pi, Drive, and Colab before collecting real data.

Use an individual token per student. Do not paste tokens into notebook cells or share them with the team.

### CLI boundary

Standard hosted Colab does not provide an official CLI for creating a free runtime and remotely executing a notebook. Keep notebook sources in Git and validate them locally with:

```bash
python scripts/check-notebooks.py
```

Run GPU cells in the Colab UI. Colab Enterprise has `gcloud colab` runtime and notebook-execution APIs, but it requires a Google Cloud project, IAM, and billed runtime resources and is outside the initial course setup.

## Raspberry Pi interactive inventory

From a local development machine at the repository root:

```bash
export PI_SSH_TARGET='<pi-user>@<tailscale-host>'
scp scripts/pi/inventory.sh "${PI_SSH_TARGET}:/tmp/rbg-inventory.sh"
ssh "$PI_SSH_TARGET" 'bash /tmp/rbg-inventory.sh'
```

This script is read-only. Save the output in an Issue before selecting Pi packages.

## Manual evaluation synchronization

After a commit exists, run from the repository root:

```bash
export PI_SSH_TARGET='<pi-user>@<tailscale-host>'
export PI_RELEASE_ROOT='<absolute-release-root>'
scripts/deploy-eval.sh \
  "$PI_SSH_TARGET" \
  "$PI_RELEASE_ROOT" \
  "$(git rev-parse HEAD)"
```

This only copies a versioned release and updates the `current` symlink. It does not start a service.
The script refuses a dirty tracked worktree or a SHA different from `HEAD`, transfers only Git-tracked files, verifies a SHA-256 manifest on the Pi, and then switches `current`.

## GitHub Actions deployment preparation

Repository variables:

- `PI_DEPLOY_ENABLED=false` initially
- `PI_HOST`: Pi Tailscale hostname or address
- `PI_USER`: dedicated Pi deployment account
- `PI_RELEASE_ROOT`: absolute release directory owned by that account

Required secrets before enabling deployment:

- `TS_OAUTH_CLIENT_ID`
- `TS_OAUTH_SECRET`
- `PI_DEPLOY_SSH_KEY`
- `PI_SSH_KNOWN_HOSTS`

The Pi needs the matching deploy-only public key. This automation key is independent of the shared class password and is not distributed to team members.

After configuring the Tailscale `tag:ci` policy, the `pi-evaluation` GitHub environment, and secrets, set `PI_DEPLOY_ENABLED=true` and manually run the `Deploy evaluation release` workflow. It always deploys the checked-out commit from `main`; concurrent deployments are serialized. Add required reviewers to the environment before enabling it. Keep automatic push deployment disabled until rollback has been tested.
