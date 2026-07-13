#!/usr/bin/env bash
set -euo pipefail

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
runtime_dir="${THPM_RUNTIME_DIR:-$data_home/thpm/runtime}"
user_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
launcher="$user_bin/thpm"
if [[ -x "$launcher" ]]; then
    "$launcher" uninstall || true
fi
if [[ -L "$launcher" && "$(readlink -f "$launcher")" == "$runtime_dir/bin/thpm" ]]; then
    rm -f "$launcher"
fi
rm -rf "$runtime_dir"
