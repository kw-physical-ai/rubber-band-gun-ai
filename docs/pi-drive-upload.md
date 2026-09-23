# Raspberry Pi direct Google Drive upload

Use this setup to send completed capture bundles from the Pi directly to a shared folder in the owner's My Drive. The Pi signs in to the existing owner account with the narrow `drive.file` OAuth scope. It can read and modify files created through this rclone client, plus any pre-existing file explicitly opened or shared with the OAuth app, but it cannot read unrelated existing Drive files.

This is practical least privilege, not a hard folder sandbox. `drive.file` is the actual OAuth boundary; `root_folder_id` only makes one folder appear as the rclone root and anyone who can edit the Pi's rclone configuration can remove that convenience setting. A user holding the Pi token can still change or delete app-created uploads and create new Drive files. Because the Linux account is shared, use this flow only for non-sensitive course data and revoke the OAuth grant after the course.

## Resulting Drive layout

```text
My Drive/
└── rubber-band-gun-ai-data/       # existing owner folder, shared with teammates
    ├── pi-upload/                 # created by rclone, then moved here in Drive
    │   ├── raw/
    │   └── smoke/
    ├── processed/                 # written by Colab
    └── runs/                      # written by Colab
```

Do not create `pi-upload/` in Colab or the Drive web UI. Rclone must create it so the `drive.file` grant can access it. Moving that app-created folder afterward does not turn the existing parent folder or neighboring files into app-accessible data.

## 1. Create a narrow Google OAuth client

Rclone's shared Google client ID is being retired during 2026, so create a dedicated desktop OAuth client.

1. While signed in to the Google account that owns `rubber-band-gun-ai-data`, create a Google Cloud project named `rubber-band-gun-ai-uploader`.
2. Enable the Google Drive API.
3. In Google Auth Platform, configure the app name, support email, and audience. Use `External` for a personal Gmail account, or `Internal` only if the account belongs to the relevant Google Workspace. If the External app remains in Testing, add the owner account as a test user.
4. Add only `https://www.googleapis.com/auth/drive.file` to the app's Drive scopes. Do not add the full `drive` or `drive.readonly` scope.
5. Create an OAuth client whose application type is `Desktop app`.
6. Keep the client ID and client secret out of Git, chat, screenshots, and notebook output. Enter them directly during Pi configuration.

Testing-mode grants expire after seven days. For continued personal use, follow the current rclone guidance for publishing the OAuth app; an unverified personal app can show a warning. Do not broaden the requested Drive scope to avoid that warning.

## 2. Install and authorize rclone on the Pi

Install a current rclone release using the [official installation instructions](https://rclone.org/install/). The installer form is:

```bash
curl -fsSL https://rclone.org/install.sh -o /tmp/install-rclone.sh
less /tmp/install-rclone.sh
sudo bash /tmp/install-rclone.sh
rclone version
```

Through the Pi's VNC session, log in as the same non-root runtime user that will run uploads, then run:

```bash
rclone config
```

Create a remote with these values; prompt numbers can differ by rclone version, so select by name:

- name: `project-drive`
- storage: `drive`
- client ID and secret: the new Desktop app values
- scope: `drive.file`
- root folder ID: blank for now
- service account: none
- Shared Drive: no
- browser authorization: yes; sign in to the existing Drive owner account

The Google consent screen must describe access to files opened or created with the app, not all Drive files. If it asks for all Drive files, cancel and correct the scope before continuing. Confirm the saved remote without exposing its token:

```bash
rclone config redacted project-drive
```

The output must contain `scope = drive.file`. Do not use `rclone config show`, which prints the decrypted configuration, and do not post even redacted output without checking it yourself.

## 3. Let rclone create its ingress folder

On the Pi, create the folder and capture its Drive object ID before moving it:

```bash
rclone mkdir project-drive:pi-upload
PI_UPLOAD_FOLDER_ID="$(
  rclone lsjson project-drive: --dirs-only --no-modtime --no-mimetype |
    python3 -c 'import json,sys; matches=[x["ID"] for x in json.load(sys.stdin) if x["Name"] == "pi-upload"]; assert len(matches) == 1, matches; print(matches[0])'
)"
echo "$PI_UPLOAD_FOLDER_ID"
```

Open Google Drive in the browser. Move the rclone-created `pi-upload` folder under the existing `rubber-band-gun-ai-data` folder. Do not replace it with a manually created folder.

Back on the Pi, make that object the remote root and create its two ingress directories:

```bash
rclone config update project-drive \
  root_folder_id "$PI_UPLOAD_FOLDER_ID" \
  config_refresh_token=false
rclone mkdir project-drive:raw
rclone mkdir project-drive:smoke
rclone lsd project-drive:
```

The final listing should contain only `raw` and `smoke`. In Drive, confirm that they appear under `rubber-band-gun-ai-data/pi-upload/` and that unrelated personal files do not appear in `rclone lsd project-drive:`.

Display the active config path, then protect the local refresh token. This prevents accidental disclosure to other Linux users, but it does not protect it from teammates who share the same runtime login:

```bash
rclone config file
chmod 700 ~/.config/rclone
chmod 600 ~/.config/rclone/rclone.conf
```

The permission commands assume `rclone config file` reports the default path under `$HOME/.config/rclone`. If it reports another path, apply the equivalent modes to that directory and file instead. Do not run `rclone config` with `sudo`.

## 4. Upload one completed bundle

Copy `scripts/pi/upload-drive-bundle.sh` to the Pi once. Upload the current smoke bundle with:

```bash
bash upload-drive-bundle.sh \
  "$HOME/rbg-smoke/$CAPTURE_ID" \
  project-drive:smoke
```

A future real capture uses:

```bash
bash upload-drive-bundle.sh \
  "$HOME/captures/$CAPTURE_ID" \
  project-drive:raw
```

The script validates the completed local bundle, removes its write permissions, freezes a verified manifest snapshot, copies payload files without deleting the source, verifies again after transfer, and publishes the snapshot as `manifest.json` last. Colab independently verifies that manifest before consuming the bundle. This detects accidental missing, modified, or unsupported filesystem entries; it does not prove who produced the data or defend against someone who controls the shared runtime account.

If an upload is interrupted before `manifest.json` appears remotely, rerun the same command with the unchanged local bundle; immutable matching files are reused. If rclone reports an immutable-file conflict, inspect the remote capture directory. Remove that incomplete directory through Drive only after confirming it has no valid completion manifest/report, then create a fresh capture ID and retry. Never overwrite a completed capture ID.

## 5. Revoke after the course

Remove the rclone app's access from the Google account's third-party connections, then delete the config file reported by `rclone config file` from the Pi. Revocation invalidates the refresh token; deleting only the Pi file does not revoke a copied token.

Reference: [rclone Google Drive backend](https://rclone.org/drive/) and [Google Drive API scope guidance](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
