#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${THPM_PYTHON:-/usr/bin/python}"
launch=true
keep=false

usage() {
    cat <<'EOF'
Usage: scripts/zellij-live-test.sh [--no-launch] [--keep]

Run the checkout's Zellij integration in an isolated XDG sandbox.

  --no-launch  Apply and restore the theme without opening Zellij.
  --keep       Keep the restored sandbox for inspection after the test.
EOF
}

while (($#)); do
    case "$1" in
        --no-launch) launch=false ;;
        --keep) keep=true ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ -x "$python_bin" ]] || { printf '%s is required\n' "$python_bin" >&2; exit 1; }
command -v zellij >/dev/null || { printf 'zellij is required\n' >&2; exit 1; }

sandbox="$(mktemp -d --tmpdir thpm-zellij-live.XXXXXX)"
session="thpm-zellij-live-$$"
source_palette="$sandbox/state/omarchy/current/theme/colors.toml"
config="$sandbox/config/zellij/config.kdl"
installed_theme="$sandbox/config/zellij/themes/thpm.kdl"
expected_config="$sandbox/expected-config.kdl"
expected_theme="$sandbox/expected-theme.kdl"
applied=false

export PYTHONPATH="$repo_dir/src"
export THPM_ASSET_DIR="$repo_dir/assets"
export XDG_CONFIG_HOME="$sandbox/config"
export XDG_STATE_HOME="$sandbox/state"
export XDG_DATA_HOME="$sandbox/data"
export XDG_CACHE_HOME="$sandbox/cache"
export XDG_RUNTIME_DIR="$sandbox/run"

restore() {
    local result=0
    [[ "$applied" == true ]] || return 0
    printf '\nRestoring the sandbox through THPM...\n'
    rm -f -- "$source_palette"
    "$python_bin" -m thpm hook-run theme-set zellij-live-test --quiet || result=$?
    cmp -s -- "$config" "$expected_config" || {
        printf 'FAIL: Zellij config was not restored\n' >&2
        result=1
    }
    cmp -s -- "$installed_theme" "$expected_theme" || {
        printf 'FAIL: displaced themes/thpm.kdl was not restored\n' >&2
        result=1
    }
    applied=false
    if ((result == 0)); then
        printf 'PASS: previous config selection and displaced theme were restored.\n'
    fi
    return "$result"
}

finish() {
    local result=$?
    trap - EXIT INT TERM
    zellij delete-session --force "$session" >/dev/null 2>&1 || true
    restore || result=1
    if [[ "$keep" == true ]]; then
        printf 'Restored sandbox kept at: %s\n' "$sandbox"
    else
        rm -rf -- "$sandbox"
    fi
    exit "$result"
}
trap finish EXIT INT TERM

mkdir -p -- \
    "$sandbox/config/zellij/themes" \
    "$sandbox/state/omarchy/current/theme" \
    "$sandbox/run"

cat >"$expected_config" <<'EOF'
theme "default"; /* restored after the test */
pane_frames true
EOF
cp -- "$expected_config" "$config"

cat >"$expected_theme" <<'EOF'
themes {
    user-original {
        fg 255 255 255
        bg 0 0 0
    }
}
EOF
cp -- "$expected_theme" "$installed_theme"

cat >"$source_palette" <<'EOF'
mode = "dark"
bg = "#002b36"
dark_bg = "#00212a"
darker_bg = "#00191f"
lighter_bg = "#073642"
selection = "#586e75"
muted = "#657b83"
dark_fg = "#839496"
fg = "#eee8d5"
light_fg = "#fdf6e3"
bright_fg = "#ffffff"
red = "#dc322f"
yellow = "#b58900"
orange = "#cb4b16"
green = "#859900"
cyan = "#2aa198"
blue = "#268bd2"
magenta = "#d33682"
brown = "#8b6f47"
bright_red = "#ff5f5f"
bright_yellow = "#d7af00"
bright_green = "#afd700"
bright_cyan = "#5fd7d7"
bright_blue = "#5fafff"
bright_magenta = "#ff5faf"
active_border_color = "#268bd2"
EOF

"$python_bin" - <<'PY'
from thpm.paths import Paths
from thpm.state import defaults, save

enabled = {plugin_id: False for plugin_id in defaults()}
enabled["zellij"] = True
save(Paths.discover(), enabled)
PY

printf 'Using checkout: '
"$python_bin" -c 'import thpm.integrations; print(thpm.integrations.__file__)'
printf 'Sandbox: %s\n\nApplying the development theme...\n' "$sandbox"
"$python_bin" -m thpm hook-run theme-set zellij-live-test --quiet
applied=true

grep -Fq 'theme "thpm-current"; /* restored after the test */' "$config" || {
    printf 'FAIL: config.kdl does not select thpm-current\n' >&2
    exit 1
}
grep -Fq 'themes {' "$installed_theme" || {
    printf 'FAIL: normalized theme was not installed\n' >&2
    exit 1
}
grep -Fq 'thpm-current {' "$installed_theme" || {
    printf 'FAIL: installed theme was not normalized to thpm-current\n' >&2
    exit 1
}
zellij setup --check >/dev/null
printf 'PASS: local source applied a valid thpm-current theme.\n'

if [[ "$launch" == true ]]; then
    printf '\nLaunching Zellij with the isolated palette-generated test theme.\n'
    printf 'Exit the session with Ctrl-q to run the restoration check.\n\n'
    zellij --session "$session"
fi

restore
