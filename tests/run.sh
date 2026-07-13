#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest discover -s "$repo_dir/tests" -v
python3 -m compileall -q "$repo_dir/src"
bash -n "$repo_dir/install.sh" "$repo_dir/uninstall.sh" "$repo_dir/assets/hooks/90-thpm" "$repo_dir/scripts/release-assets.sh"
