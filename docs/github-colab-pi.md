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

### Four-person access setup

An organization owner performs this once:

1. In `kw-physical-ai`, open **People → Invite member** and invite the other three GitHub accounts as organization **Member**, not Owner.
2. Create a team such as `project-members`, add all four members, and give that team **Write** access to `rubber-band-gun-ai`.
3. Keep organization/repository administration with the owners. Write access is the equal day-to-day role: it supports branches, pushes, issues, pull requests, reviews, Actions visibility, and merge under the repository rules without granting deletion or security-setting control.
4. Each member clones with their own GitHub account and SSH key, and creates their own repository-scoped Colab token. Never share one person's SSH key or token.

If this organization will never contain another repository, organization base permission `Write` is possible, but a repository team makes the intended scope explicit and is safer when another project is added later. GitHub's current [organization repository role table](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization) is the authority for what `Write` can do.

### Access matrix

| Surface | Team access | Kept separate |
| --- | --- | --- |
| GitHub organization | All four students are `Member` | Owner and billing responsibilities |
| GitHub repository | `project-members` team has `Write` | Owner/Admin-only organization and repository settings |
| Google Drive | All four Google accounts are `Editor` on `rubber-band-gun-ai-data` only | The owner's unrelated My Drive files |
| Colab | Each member opens the GitHub notebook and mounts the shared folder | Runtime, GitHub token, Drive consent and Secret |
| Raspberry Pi | Only current hardware operators need Tailscale and SSH/VNC access | Pi rclone OAuth token and deployment key |
| GitHub Actions deployment | Team reviews code and one `Write` member manually dispatches an enabled workflow | Secret values are entered once and never shared in chat or local config |

One-time completion checklist:

- [ ] All four GitHub invitations have been accepted.
- [ ] All four members belong to `project-members`.
- [ ] `project-members` has `Write` access to `rubber-band-gun-ai`.
- [ ] The three additional Google accounts are Editors of `rubber-band-gun-ai-data`.
- [ ] Every member has added the shared folder shortcut directly under My Drive with the same folder name.
- [ ] Every member has created an individual repository-scoped `GITHUB_TOKEN` and passed `00_environment_check.ipynb`.
- [ ] Hardware operators can reach the Pi without storing an address, password or private key in Git.

The detailed behavior behind CI, upload, dataset creation and optional Pi deployment is in [Automation flow](automation-flow.md).

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

Share the single `rubber-band-gun-ai-data` folder with the four Google accounts as **Editor**. Each member adds a shortcut for that shared folder directly under **My Drive** with the same name, so every notebook can use `/content/drive/MyDrive/rubber-band-gun-ai-data`. Do not share the entire personal Drive. Google Drive folder permissions are inherited, and an Editor can add, move, edit, or delete content in the shared folder, so raw immutability is a team convention rather than an access-control guarantee. See Google's current [folder sharing behavior](https://support.google.com/drive/answer/7166529).

A Colab notebook loaded from GitHub, its runtime, Drive authorization, and Colab Secrets are separate: every member opens the GitHub notebook and authorizes their own runtime and accounts. Sharing one running Colab VM or another member's Secret is neither required nor expected. The [Colab FAQ](https://research.google.com/colaboratory/faq.html) confirms that sharing a notebook does not share its virtual machine.

The Pi keeps its existing folder-scoped Drive OAuth/rclone configuration. Team members need Drive folder access for Colab, but they do not copy the Pi token. Likewise, shared Pi access does not require personal GitHub credentials on the Pi; use a repository-scoped read-only deploy key for pulls or deploy a reviewed release from GitHub Actions when that path is enabled.

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

Repository `Write` users can [create, replace, or delete repository Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), although GitHub does not reveal an existing secret value. A merged workflow can also consume configured secrets. Therefore equal `Write` access is an equal code-trust boundary: require another team member's PR review for workflow changes and never print, download, or redistribute the secret values.

After configuring the Tailscale `tag:ci` policy and repository secrets, set `PI_DEPLOY_ENABLED=true` and manually run the `Deploy evaluation release` workflow. It always deploys the checked-out commit from `main`; concurrent deployments are serialized. GitHub documents that [required environment reviewers are available only for public repositories on Free, Pro, and Team](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), so this private repository cannot rely on a platform-enforced second approver under those plans. Keep deployment disabled until the team has tested rollback and chosen either a documented two-person team rule or a plan/protection mechanism that enforces the desired gate. Keep automatic push deployment disabled.
