#!/usr/bin/env bash
set -euo pipefail

user_bin="$(python3 -c 'import site; print(site.USER_BASE + "/bin")')"
if [[ -x "$user_bin/thpm" ]]; then
    "$user_bin/thpm" uninstall || true
fi
python3 -m pip uninstall -y thpm
