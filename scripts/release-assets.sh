#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(<"$repo_dir/VERSION")"
output_dir="${1:-$repo_dir/dist/release}"
archive="$output_dir/thpm-$version.tar.gz"

mkdir -p "$output_dir"
git -C "$repo_dir" archive --format=tar.gz --prefix="thpm-$version/" -o "$archive" HEAD
(
    cd "$output_dir"
    sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256"
)
printf '%s\n%s\n' "$archive" "$archive.sha256"
