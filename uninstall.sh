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
    "$runtime_launcher" uninstall || true
    rm -f "$launcher"
fi
rm -rf "$runtime_dir"
