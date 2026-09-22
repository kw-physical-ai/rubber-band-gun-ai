#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <user@host> <release-root> <commit-sha>" >&2
  exit 2
fi

target="$1"
release_root="$2"
commit_sha="$3"
release_dir="${release_root}/releases/${commit_sha}"

if [[ ! "$target" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.:-]+$ ]]; then
  echo "invalid deployment target: $target" >&2
  exit 2
fi
if [[ ! "$release_root" =~ ^/[A-Za-z0-9._/-]+$ ]] || [[ "$release_root" == *".."* ]]; then
  echo "invalid release root: $release_root" >&2
  exit 2
fi
if [[ ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "commit SHA must be 40 lowercase hexadecimal characters" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [[ "$(git rev-parse HEAD)" != "$commit_sha" ]]; then
  echo "requested release does not match the checked-out commit" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "tracked files differ from the checked-out commit" >&2
  exit 1
fi

staging_root="$(mktemp -d)"
trap 'rm -rf "$staging_root"' EXIT
staging_dir="$staging_root/release"
tracked_list="$staging_root/tracked-files"
mkdir -p "$staging_dir"
git ls-files > "$tracked_list"
rsync -a --files-from="$tracked_list" ./ "$staging_dir/"

(
  cd "$staging_dir"
  while IFS= read -r path; do
    shasum -a 256 "$path"
  done < "$tracked_list"
) > "$staging_dir/.release-manifest.sha256"

ssh "$target" "mkdir -p '$release_dir'"
rsync -az --delete "$staging_dir/" "${target}:${release_dir}/"
ssh "$target" "cd '$release_dir' && sha256sum -c .release-manifest.sha256 && ln -sfnT '$release_dir' '${release_root}/current'"

echo "Evaluation release synchronized: ${target}:${release_dir}"
echo "No service was started and no actuator command was issued."
