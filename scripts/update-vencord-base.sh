#!/usr/bin/env bash
set -euo pipefail

repo="refact0r/midnight-discord"
commit="${1:-}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
asset_parent="$root/assets"
asset_dir="$asset_parent/vencord"
staged_dir=""
backup_dir=""

cleanup() {
    [[ -z "$staged_dir" ]] || rm -rf "$staged_dir"
    if [[ -n "$backup_dir" && -d "$backup_dir" && ! -d "$asset_dir" ]]; then
        mv "$backup_dir" "$asset_dir"
    fi
}
trap cleanup EXIT

if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Usage: scripts/update-vencord-base.sh <40-character-upstream-commit>" >&2
    exit 1
fi

base="https://raw.githubusercontent.com/$repo/$commit"
staged_dir="$(mktemp -d "$asset_parent/.vencord-update.XXXXXX")"
source_css="$staged_dir/.midnight.css"
target="$staged_dir/thpm-midnight.css"
license="$staged_dir/LICENSE.midnight"
provenance="$staged_dir/UPSTREAM.md"

curl --fail --silent --show-error --location "$base/build/midnight.css" > "$source_css"
curl --fail --silent --show-error --location "$base/LICENSE" > "$license"
grep -Fq -- "--background-base-lowest" "$source_css" || {
    echo "Downloaded Midnight build is missing the expected Discord color surface" >&2
    exit 1
}
grep -Fq "MIT License" "$license" || {
    echo "Downloaded Midnight license is not the expected MIT license" >&2
    exit 1
}

{
    cat <<EOF
/*!
 * THPM Midnight Vencord base
 * Derived from refact0r/midnight-discord.
 * Upstream: https://github.com/refact0r/midnight-discord
 * Upstream commit: $commit
 *
 * The complete upstream MIT notice follows so this standalone hosted copy
 * retains the notice required for redistribution.
 *
EOF
    sed -e 's/^$/ */' -e 't' -e 's/^/ * /' "$license"
    printf ' */\n'
    cat "$source_css"
} > "$target"

artifact_sha256="$(sha256sum "$source_css" | awk '{print $1}')"
cat > "$provenance" <<EOF
# THPM Midnight Vencord base

\`thpm-midnight.css\` is a vendored build of
[\`refact0r/midnight-discord\`](https://github.com/refact0r/midnight-discord),
used under its MIT License.

- Upstream commit: \`$commit\`
- Upstream artifact: \`build/midnight.css\`
- Upstream artifact SHA-256: \`$artifact_sha256\`
- Local license copy: \`LICENSE.midnight\`

Run \`scripts/update-vencord-base.sh <commit>\` to stage a newer upstream build,
license, and provenance record together. Test the result in Vesktop before release.
EOF
rm "$source_css"

backup_dir="$asset_parent/.vencord-backup.$$"
if [[ -d "$asset_dir" ]]; then
    mv "$asset_dir" "$backup_dir"
fi
if ! mv "$staged_dir" "$asset_dir"; then
    [[ ! -d "$backup_dir" ]] || mv "$backup_dir" "$asset_dir"
    exit 1
fi
staged_dir=""
rm -rf "$backup_dir"
backup_dir=""

printf 'Updated %s from %s at %s\n' "$asset_dir/thpm-midnight.css" "$repo" "$commit"
printf 'Upstream artifact SHA-256: %s\n' "$artifact_sha256"
