#!/usr/bin/env bash
set -euo pipefail

repository="OldJobobo/thpm"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
version="${1:-}"

usage() {
    cat <<'EOF'
Usage: scripts/install-arch-release.sh [VERSION]

Download a verified THPM GitHub release source archive, build its Arch package,
install it through pacman, and complete THPM's per-user setup.

VERSION defaults to the checkout VERSION file or the version published on main.
EOF
}

if [[ "$version" == "-h" || "$version" == "--help" ]]; then
    usage
    exit 0
fi
if (( EUID == 0 )); then
    printf 'Run this installer as your normal user; it invokes sudo only for pacman.\n' >&2
    exit 1
fi
for command in curl makepkg sha256sum sudo tar; do
    command -v "$command" >/dev/null || {
        printf '%s is required\n' "$command" >&2
        exit 1
    }
done

if [[ -z "$version" && -f "$script_dir/../VERSION" ]]; then
    version="$(<"$script_dir/../VERSION")"
fi
if [[ -z "$version" ]]; then
    version="$(curl --fail --silent --show-error --location \
        "https://raw.githubusercontent.com/$repository/main/VERSION")"
fi
version="${version//$'\r'/}"
version="${version//$'\n'/}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]+)?$ ]] || {
    printf 'Invalid THPM version: %s\n' "$version" >&2
    exit 2
}

archive_name="thpm-$version.tar.gz"
checksum_name="$archive_name.sha256"
release_url="https://github.com/$repository/releases/download/v$version"
work_dir="$(mktemp -d --tmpdir thpm-release-install.XXXXXX)"
cleanup() {
    rm -rf -- "$work_dir"
}
trap cleanup EXIT INT TERM

printf 'Downloading THPM %s release sources...\n' "$version"
curl --fail --silent --show-error --location \
    --output "$work_dir/$archive_name" "$release_url/$archive_name"
curl --fail --silent --show-error --location \
    --output "$work_dir/$checksum_name" "$release_url/$checksum_name"

read -r expected_hash expected_name extra < "$work_dir/$checksum_name"
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$expected_name" == "$archive_name" && -z "${extra:-}" ]] || {
    printf 'Release checksum file has an unexpected format\n' >&2
    exit 1
}
printf '%s  %s\n' "$expected_hash" "$work_dir/$archive_name" | sha256sum --check --status - || {
    printf 'Release source checksum verification failed\n' >&2
    exit 1
}
printf 'Verified release source SHA-256: %s\n' "$expected_hash"

tar --extract --gzip --file "$work_dir/$archive_name" --directory "$work_dir"
source_root="$work_dir/thpm-$version"
package_dir="$source_root/packaging/aur/thpm"
[[ -f "$package_dir/PKGBUILD" && -f "$package_dir/thpm.install" ]] || {
    printf 'Release archive does not contain the stable Arch packaging files\n' >&2
    exit 1
}
cp -- "$work_dir/$archive_name" "$package_dir/$archive_name"

printf 'Building the verified release source with makepkg...\n'
(
    cd "$package_dir"
    makepkg --syncdeps --cleanbuild --clean --force --noconfirm
)
packages=("$package_dir"/thpm-"$version"-*-any.pkg.tar.*)
if (( ${#packages[@]} != 1 )) || [[ ! -f "${packages[0]}" ]]; then
    printf 'Could not identify the built Arch package\n' >&2
    exit 1
fi

printf 'Installing %s through pacman...\n' "${packages[0]##*/}"
sudo pacman -U --noconfirm -- "${packages[0]}"

printf 'Completing THPM user setup...\n'
/usr/bin/thpm install
printf '\nInstalled THPM %s from verified GitHub release sources.\n' "$version"
