#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(<"$repo_dir/VERSION")"
output_dir="${1:-$repo_dir/dist/release}"
archive="$output_dir/thpm-$version.tar.gz"

if [[ -n "$(git -C "$repo_dir" status --porcelain)" ]]; then
    echo "release assets require a clean working tree" >&2
    exit 1
fi
head_version="$(git -C "$repo_dir" show HEAD:VERSION | tr -d '\n')"
[[ "$head_version" == "$version" ]] || { echo "working VERSION does not match HEAD" >&2; exit 1; }
tag="$(git -C "$repo_dir" describe --tags --exact-match HEAD 2>/dev/null || true)"
[[ "$tag" == "v$version" ]] || { echo "HEAD must be tagged v$version" >&2; exit 1; }
qml_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$repo_dir/assets/qml/manifest.json")"
[[ "$qml_version" == "$version" ]] || { echo "QML manifest version does not match VERSION" >&2; exit 1; }
grep -Fq "__version__ = \"$version\"" "$repo_dir/src/thpm/__init__.py" || { echo "Python fallback version does not match VERSION" >&2; exit 1; }

mkdir -p "$output_dir"
git -C "$repo_dir" archive --format=tar.gz --prefix="thpm-$version/" -o "$archive" HEAD
(
    cd "$output_dir"
    sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256"
)
printf '%s\n%s\n' "$archive" "$archive.sha256"
