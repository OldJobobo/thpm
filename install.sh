#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
runtime_dir="${THPM_RUNTIME_DIR:-$data_home/thpm/runtime}"
user_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"

python3 -m venv "$runtime_dir"
"$runtime_dir/bin/python" -m pip install --disable-pip-version-check --no-input 'textual>=8.2.8,<9'
site_packages="$("$runtime_dir/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
rm -rf "$site_packages/thpm"
rm -rf "$site_packages"/thpm-*.dist-info "$site_packages"/thpm-*.egg-info
cp -R "$repo_dir/src/thpm" "$site_packages/thpm"
rm -rf "$runtime_dir/share/thpm"
mkdir -p "$runtime_dir/share/thpm"
cp -R "$repo_dir/assets/." "$runtime_dir/share/thpm/"
install -Dm755 "$repo_dir/assets/bin/thpm" "$runtime_dir/bin/thpm"

# Validate the prepared runtime and complete the capability-checked core install
# before replacing an existing launcher. Service.install performs migration only
# after confirming that the required Omarchy routes are available.
"$runtime_dir/bin/thpm" install --no-ui "$@"

mkdir -p "$user_bin"
ln -sfn "$runtime_dir/bin/thpm" "$user_bin/thpm"
install_metadata="$data_home/thpm/install.toml"
mkdir -p "$(dirname "$install_metadata")"
printf 'origin = "source"\nrepository = "oldjobobo/thpm"\nchannel = "stable"\n' > "$install_metadata"
"$user_bin/thpm" install "$@"
printf 'Installed thpm %s in %s. Ensure %s is in PATH.\n' "$(<"$repo_dir/VERSION")" "$runtime_dir" "$user_bin"
