#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(<"$repo_dir/VERSION")"
output_dir="${1:-$repo_dir/dist/release}"
archive="$output_dir/thpm-$version.tar.gz"

python3 "$repo_dir/scripts/verify-release.py" metadata --require-clean --require-tag

mkdir -p "$output_dir"
git -C "$repo_dir" -c tar.umask=0002 archive --format=tar.gz --prefix="thpm-$version/" -o "$archive" HEAD
(
    cd "$output_dir"
    sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256"
)
python3 "$repo_dir/scripts/verify-release.py" artifact "$archive" "$archive.sha256" --ref HEAD
printf '%s\n%s\n' "$archive" "$archive.sha256"
