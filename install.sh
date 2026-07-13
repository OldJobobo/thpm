#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
    THPM_ASSET_DIR="$repo_dir/assets" \
    python3 -m thpm migrate
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
runtime_dir="${THPM_RUNTIME_DIR:-$data_home/thpm/runtime}"
user_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"

python3 -m venv --without-pip "$runtime_dir"
site_packages="$("$runtime_dir/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
rm -rf "$site_packages/thpm"
cp -R "$repo_dir/src/thpm" "$site_packages/thpm"
rm -rf "$runtime_dir/share/thpm"
mkdir -p "$runtime_dir/share/thpm"
cp -R "$repo_dir/assets/." "$runtime_dir/share/thpm/"
install -Dm755 "$repo_dir/assets/bin/thpm" "$runtime_dir/bin/thpm"
mkdir -p "$user_bin"
ln -sfn "$runtime_dir/bin/thpm" "$user_bin/thpm"
"$user_bin/thpm" install "$@"
printf 'Installed thpm %s in %s. Ensure %s is in PATH.\n' "$(<"$repo_dir/VERSION")" "$runtime_dir" "$user_bin"
