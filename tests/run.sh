#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest discover -s "$repo_dir/tests" -v
python3 -m compileall -q "$repo_dir/src"
bash -n "$repo_dir/install.sh" "$repo_dir/uninstall.sh" "$repo_dir/assets/hooks/90-thpm" "$repo_dir/scripts/install-arch-release.sh" "$repo_dir/scripts/release-assets.sh" "$repo_dir/scripts/update-vencord-base.sh" "$repo_dir/scripts/agent-worktree.sh" "$repo_dir/scripts/setup-dev.sh" "$repo_dir/.githooks/pre-commit" "$repo_dir/.githooks/pre-push"
if command -v qmllint >/dev/null 2>&1; then
  qmllint "$repo_dir/assets/qml/Panel.qml.in"
fi
