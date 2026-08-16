#!/usr/bin/env bash
set -euo pipefail

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
runtime_dir="${THPM_RUNTIME_DIR:-$data_home/thpm/runtime}"
user_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
launcher="$user_bin/thpm"
runtime_launcher="$runtime_dir/bin/thpm"
if [[ -L "$launcher" && -x "$runtime_launcher" ]] \
    && launcher_target="$(readlink -f -- "$launcher")" \
    && runtime_target="$(readlink -f -- "$runtime_launcher")" \
    && [[ "$launcher_target" == "$runtime_target" ]]; then
    if ! "$runtime_launcher" uninstall; then
        echo "THPM cleanup is incomplete; runtime retained for: thpm uninstall" >&2
        exit 1
    fi
    rm -f "$launcher"
fi
rm -rf "$runtime_dir"
