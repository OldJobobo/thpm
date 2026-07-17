#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
runtime_dir="${THPM_RUNTIME_DIR:-$data_home/thpm/runtime}"
user_bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
staged="${runtime_dir}.next-$$"
previous="${runtime_dir}.previous"
activated=false
launcher_installed=false

cleanup() {
    rm -rf "$staged"
    if [[ "$launcher_installed" == true && ! -d "$previous" && -L "$user_bin/thpm" && "$(readlink "$user_bin/thpm")" == "$runtime_dir/bin/thpm" ]]; then
        rm -f "$user_bin/thpm"
    fi
    if [[ "$activated" == true ]]; then
        rm -rf "$runtime_dir"
        if [[ -d "$previous" ]]; then
            mv "$previous" "$runtime_dir"
        fi
    fi
}
trap cleanup ERR INT TERM

mkdir -p "$(dirname "$runtime_dir")"
rm -rf "$staged"
python3 -m venv "$staged"
"$staged/bin/python" -m pip install --disable-pip-version-check --no-input 'textual>=8.2.8,<9'
site_packages="$("$staged/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
cp -R "$repo_dir/src/thpm" "$site_packages/thpm"
mkdir -p "$staged/share/thpm"
cp -R "$repo_dir/assets/." "$staged/share/thpm/"
install -Dm755 "$repo_dir/assets/bin/thpm" "$staged/bin/thpm"

# These checks are deliberately non-mutating. No migration or user configuration
# is touched until the complete replacement runtime has passed validation.
"$staged/bin/thpm" --version
"$staged/bin/python" -c 'from thpm.tui import ThpmTui'
"$staged/bin/thpm" install --check "$@"

rm -rf "$previous"
if [[ -d "$runtime_dir" ]]; then
    mv "$runtime_dir" "$previous"
fi
activated=true
mv "$staged" "$runtime_dir"

# Perform the per-user mutation exactly once. A failure restores the prior runtime.
"$runtime_dir/bin/thpm" install "$@"

mkdir -p "$user_bin"
ln -sfn "$runtime_dir/bin/thpm" "$user_bin/thpm"
launcher_installed=true
install_metadata="$data_home/thpm/install.toml"
channel=stable
[[ "$(<"$repo_dir/VERSION")" == *rc* ]] && channel=rc
metadata_tmp="$install_metadata.tmp-$$"
printf 'origin = "source"\nrepository = "oldjobobo/thpm"\nchannel = "%s"\n' "$channel" > "$metadata_tmp"
mv "$metadata_tmp" "$install_metadata"

rm -rf "$previous"
activated=false
trap - ERR INT TERM
printf 'Installed thpm %s in %s. Ensure %s is in PATH.\n' "$(<"$repo_dir/VERSION")" "$runtime_dir" "$user_bin"
