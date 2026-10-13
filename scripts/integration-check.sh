#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: scripts/integration-check.sh <integration-id> <theme-a> <theme-b> [--app "<name version>"]

Walk one integration through a real-application check on this desktop:
enable, switch to two Omarchy themes, disable, and confirm by eye that the
application followed each step. Prints the row to record in
docs/integration-support.md.

The previous theme and the integration's enabled state are restored on exit.
USAGE
}

app=""
positional=()
while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --app) app="${2:?--app needs a value}"; shift 2 ;;
        *) positional+=("$1"); shift ;;
    esac
done
((${#positional[@]} == 3)) || { usage >&2; exit 2; }
id="${positional[0]}"
theme_a="${positional[1]}"
theme_b="${positional[2]}"
[[ "$theme_a" != "$theme_b" ]] || { printf 'The two themes must differ\n' >&2; exit 2; }

for command in thpm omarchy-theme-set omarchy-theme-current python3; do
    command -v "$command" >/dev/null || { printf '%s is required\n' "$command" >&2; exit 1; }
done

was_enabled="$(thpm list --json | python3 -c '
import json, sys
plugins = {item["id"]: item for item in json.load(sys.stdin)["plugins"]}
plugin = plugins.get(sys.argv[1])
if plugin is None or plugin.get("ownership") != "thpm":
    sys.exit(f"{sys.argv[1]} is not an active THPM integration")
print("yes" if plugin["enabled"] else "no")
' "$id")"
original_theme="$(omarchy-theme-current)"

restore() {
    status=$?
    trap - EXIT INT TERM
    printf '\nRestoring the previous state...\n'
    if [[ "$was_enabled" == yes ]]; then thpm enable "$id" || true; else thpm disable "$id" || true; fi
    omarchy-theme-set "$original_theme" || true
    exit "$status"
}
trap restore EXIT INT TERM

confirm() {
    local answer
    read -r -p "$1 [y/N] " answer
    [[ "$answer" == [yY]* ]] || { printf 'Not confirmed: %s does not pass this check.\n' "$id" >&2; exit 1; }
}

printf 'Checking %s. Open the application now if it is not running.\n' "$id"
thpm enable "$id"
omarchy-theme-set "$theme_a"
confirm "Does the application show $theme_a? (Restart it first if THPM reported that it needs one.)"
omarchy-theme-set "$theme_b"
confirm "Does the application now show $theme_b?"
thpm disable "$id"
confirm "After disabling, is the application back to its own look and are your own settings intact?"

[[ -n "$app" ]] || read -r -p 'Application and version (for example the output of pacman -Q <package>): ' app
omarchy="$(omarchy-version 2>/dev/null || printf unknown)"
who="$(git config user.name 2>/dev/null || id -un)"
printf '\n%s passed. Record this in the "Last real-application check" column:\n\n' "$id"
printf '%s · %s · Omarchy %s · THPM %s · %s\n' \
    "$(date +%F)" "$app" "$omarchy" "$(thpm --version | awk '{print $NF}')" "$who"
