#!/usr/bin/env bash
set -euo pipefail

repository="OldJobobo/thpm"
version="${1:-}"

usage() {
    cat <<'EOF'
Usage: scripts/install-arch-release.sh [VERSION]

Download a verified THPM GitHub release source archive, build its Arch package,
install it through pacman, and complete THPM's per-user setup.

VERSION defaults to the newest published GitHub release, including release candidates.
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

if [[ -z "$version" ]]; then
    releases="$(curl --fail --silent --show-error --location \
        --header "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$repository/releases?per_page=1")"
    tag="$(printf '%s\n' "$releases" | awk -F '"' '/"tag_name"[[:space:]]*:/{print $4; exit}')"
    [[ "$tag" == v* ]] || {
        printf 'Could not determine the latest published THPM release\n' >&2
        exit 1
    }
    version="${tag#v}"
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
checksum_assignment="$(grep -E "^sha256sums=\\('([0-9a-f]{64}|SKIP)'\\)$" "$package_dir/PKGBUILD" || true)"
if [[ ! "$checksum_assignment" =~ ^sha256sums=\(\'([0-9a-f]{64}|SKIP)\'\)$ ]]; then
    printf 'Release PKGBUILD checksum is not canonical\n' >&2
    exit 1
fi
package_hash="${BASH_REMATCH[1]}"
placeholder_hash="$(printf '0%.0s' {1..64})"
if [[ "$package_hash" == "$placeholder_hash" || "$package_hash" == "SKIP" ]]; then
    sed -i "s|^sha256sums=.*$|sha256sums=('$expected_hash')|" "$package_dir/PKGBUILD"
elif [[ "$package_hash" != "$expected_hash" ]]; then
    printf 'Release PKGBUILD checksum does not match the verified archive\n' >&2
    exit 1
fi
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
