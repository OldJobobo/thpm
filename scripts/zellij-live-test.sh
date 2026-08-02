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
selected_config="$sandbox/selected-config.kdl"
hot_reload_report="$sandbox/hot-reload.json"
hot_reload_log="$sandbox/hot-reload.log"
hot_reload_pid=""
applied=false

export PYTHONPATH="$repo_dir/src"
export THPM_ASSET_DIR="$repo_dir/assets"
export HOME="$sandbox/home"
export XDG_CONFIG_HOME="$sandbox/config"
export XDG_STATE_HOME="$sandbox/state"
export XDG_DATA_HOME="$sandbox/data"
export XDG_CACHE_HOME="$sandbox/cache"
export XDG_RUNTIME_DIR="$sandbox/run"
unset ZELLIJ_CONFIG_FILE ZELLIJ_CONFIG_DIR

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
    if [[ -n "$hot_reload_pid" ]]; then
        kill "$hot_reload_pid" >/dev/null 2>&1 || true
        wait "$hot_reload_pid" >/dev/null 2>&1 || true
    fi
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
    "$sandbox/home" \
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
zellij_check="$(zellij setup --check 2>&1)"
grep -Fq "[LOOKING FOR CONFIG FILE FROM]: \"$config\"" <<<"$zellij_check" || {
    printf 'FAIL: Zellij did not select the sandbox config\n%s\n' "$zellij_check" >&2
    exit 1
}
cp -- "$config" "$selected_config"
printf 'PASS: local source applied a valid thpm-current theme.\n'

apply_live_update() {
    "$python_bin" - "$source_palette" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text()
replacements = {
    '#002b36': '#1b1028',
    '#00212a': '#140b20',
    '#00191f': '#0d0716',
    '#073642': '#342047',
    '#586e75': '#6c3f83',
    '#eee8d5': '#f7d7ff',
    '#268bd2': '#ff4fd8',
    '#2aa198': '#62e6ff',
}
for old, new in replacements.items():
    content = content.replace(old, new)
path.write_text(content)
PY
    "$python_bin" -m thpm --json hook-run theme-set zellij-live-test --quiet \
        >"$hot_reload_report" 2>"$hot_reload_log"
    cmp -s -- "$config" "$selected_config"
    "$python_bin" - "$hot_reload_report" "$config" "$installed_theme" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text())
changed = set(payload.get("changed", []))
missing = {sys.argv[2], sys.argv[3]} - changed
if missing:
    raise SystemExit(f"live update did not report rewritten paths: {sorted(missing)}")
PY
}

if [[ "$launch" == true ]]; then
    printf '\nLaunching Zellij with the initial sandbox theme.\n'
    printf 'Its colors should switch live after two seconds without restarting the session.\n'
    printf 'Exit the session with Ctrl-q to run the restoration check.\n\n'
    (
        sleep 2
        apply_live_update
    ) &
    hot_reload_pid=$!
    zellij --session "$session"
    wait "$hot_reload_pid"
    hot_reload_pid=""
    printf 'Did the running session visibly switch colors? [y/N] '
    read -r observed </dev/tty || observed=""
    case "$observed" in
        y|Y|yes|YES|Yes) ;;
        *) printf 'FAIL: live color reload was not visually confirmed.\n' >&2; exit 1 ;;
    esac
    printf 'PASS: the running Zellij session visibly reloaded its colors.\n'
else
    apply_live_update
    printf 'PASS: a later theme update refreshed watched config.kdl without changing its content.\n'
fi

restore
