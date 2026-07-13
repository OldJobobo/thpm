#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --user --upgrade .
user_bin="$(python3 -c 'import site; print(site.USER_BASE + "/bin")')"
"$user_bin/thpm" install "$@"
printf 'Installed thpm %s. Ensure %s is in PATH.\n' "$(<VERSION)" "$user_bin"
