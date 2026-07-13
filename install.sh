#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
    THPM_ASSET_DIR="$repo_dir/assets" \
    python3 -m thpm migrate
python3 -m pip install --user --upgrade "$repo_dir"
user_bin="$(python3 -c 'import site; print(site.USER_BASE + "/bin")')"
"$user_bin/thpm" install "$@"
printf 'Installed thpm %s. Ensure %s is in PATH.\n' "$(<VERSION)" "$user_bin"
