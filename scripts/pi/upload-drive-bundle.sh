#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <completed-bundle-directory> <rclone-remote-parent>" >&2
  echo "example: $0 ~/rbg-smoke/smoke-20260922T123456Z project-drive:smoke" >&2
  exit 2
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone is not installed" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed" >&2
  exit 1
fi

bundle_dir="$(cd "$1" && pwd -P)"
remote_parent="${2%/}"
if [[ "$remote_parent" != "project-drive:raw" && "$remote_parent" != "project-drive:smoke" ]]; then
  echo "destination must be project-drive:raw or project-drive:smoke" >&2
  exit 1
fi
manifest_path="$bundle_dir/manifest.json"
if [[ -L "$manifest_path" || ! -f "$manifest_path" ]]; then
  echo "completed bundle has no manifest.json: $bundle_dir" >&2
  exit 1
fi

verify_bundle() {
  local manifest_to_verify="${1:-$manifest_path}"
  python3 - "$bundle_dir" "$manifest_to_verify" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2])
if manifest_path.is_symlink() or not manifest_path.is_file():
    raise SystemExit("manifest must be an ordinary file")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
capture_id = manifest.get("capture_id")
if not isinstance(capture_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", capture_id):
    raise SystemExit(f"invalid capture ID: {capture_id}")
if bundle.name != capture_id:
    raise SystemExit(f"bundle directory and capture ID differ: {bundle.name} != {capture_id}")

entries = manifest.get("files")
if not isinstance(entries, list) or not entries:
    raise SystemExit("manifest contains no files")

expected = set()
for entry in entries:
    if not isinstance(entry, dict):
        raise SystemExit(f"invalid manifest entry: {entry}")
    relative_name = entry.get("path")
    relative = Path(relative_name) if isinstance(relative_name, str) else None
    if relative is None or relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"unsafe manifest path: {relative_name}")
    if relative_name in expected:
        raise SystemExit(f"duplicate manifest path: {relative_name}")
    expected.add(relative_name)
    path = bundle / relative
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"missing or unsupported file: {relative_name}")
    if path.stat().st_size != entry.get("bytes"):
        raise SystemExit(f"size mismatch: {relative_name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise SystemExit(f"SHA-256 mismatch: {relative_name}")

all_paths = list(bundle.rglob("*"))
if any(path.is_symlink() for path in all_paths):
    raise SystemExit("bundle contains a symbolic link")
if any(not path.is_file() and not path.is_dir() for path in all_paths):
    raise SystemExit("bundle contains a non-regular filesystem object")
actual = {
    path.relative_to(bundle).as_posix()
    for path in all_paths
    if path.is_file() and path.relative_to(bundle).as_posix() != "manifest.json"
}
if actual != expected:
    raise SystemExit("bundle files do not exactly match the manifest")
print(capture_id)
PY
}

# A completed capture is immutable. Removing write bits blocks accidental background writers;
# users who share this Linux account remain inside the trust boundary and can override the mode.
capture_id="$(verify_bundle)"
chmod -R a-w "$bundle_dir"
manifest_snapshot_dir="$(mktemp -d)"
trap 'rm -f "$manifest_snapshot_dir/manifest.json"; rmdir "$manifest_snapshot_dir"' EXIT
manifest_snapshot="$manifest_snapshot_dir/manifest.json"
cp "$manifest_path" "$manifest_snapshot"
if [[ "$(verify_bundle "$manifest_snapshot")" != "$capture_id" ]]; then
  echo "bundle identity changed while making the manifest snapshot" >&2
  exit 1
fi

remote_dir="$remote_parent/$capture_id"
echo "Uploading verified bundle: $bundle_dir -> $remote_dir"

# Upload the manifest last so its presence means every payload file passed a remote check.
rclone copy "$bundle_dir" "$remote_dir" \
  --exclude '/manifest.json' \
  --immutable \
  --checksum \
  --check-first \
  --progress
rclone check "$bundle_dir" "$remote_dir" --exclude '/manifest.json'

# Recheck after the payload transfer, then compare the stable payload once more before
# publishing the completion marker.
if [[ "$(verify_bundle "$manifest_snapshot")" != "$capture_id" ]]; then
  echo "bundle identity changed during upload" >&2
  exit 1
fi
rclone check "$bundle_dir" "$remote_dir" --exclude '/manifest.json'
rclone copyto "$manifest_snapshot" "$remote_dir/manifest.json" \
  --immutable \
  --checksum \
  --progress
rclone check "$bundle_dir" "$remote_dir" --exclude '/manifest.json'
rclone check "$manifest_snapshot_dir" "$remote_dir" --include '/manifest.json'

echo "Drive upload verified: $remote_dir"
echo "Local bundle retained: $bundle_dir"
