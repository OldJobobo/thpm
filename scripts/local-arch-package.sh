#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$repo_dir/dist/local-package"
install_package=false
pkgrel="${THPM_LOCAL_PKGREL:-99}"

usage() {
    cat <<'EOF'
Usage: scripts/local-arch-package.sh [--install] [--output DIR]

Build a normal Arch package from the current working tree without publishing it.

  --install     Install the resulting package with sudo pacman -U.
  --output DIR  Write the package to DIR instead of dist/local-package.

Set THPM_LOCAL_PKGREL to override the default local package release (99).
EOF
}

while (($#)); do
    case "$1" in
        --install)
            install_package=true
            ;;
        --output)
            (($# >= 2)) || { printf '%s\n' '--output requires a directory' >&2; exit 2; }
            output_dir="$2"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

[[ "$pkgrel" =~ ^[1-9][0-9]*$ ]] || {
    printf 'THPM_LOCAL_PKGREL must be a positive integer\n' >&2
    exit 2
}
for command in git makepkg python sha256sum tar; do
    command -v "$command" >/dev/null || {
        printf '%s is required\n' "$command" >&2
        exit 1
    }
done

version="$(<"$repo_dir/VERSION")"
work_dir="$(mktemp -d --tmpdir thpm-local-package.XXXXXX)"
archive="$work_dir/thpm-working-tree.tar.gz"

cleanup() {
    rm -rf -- "$work_dir"
}
trap cleanup EXIT INT TERM

mkdir -p -- "$output_dir"

printf 'Snapshotting the current working tree...\n'
git -C "$repo_dir" ls-files --cached --others --exclude-standard -z \
    | while IFS= read -r -d '' file; do
        [[ -e "$repo_dir/$file" || -L "$repo_dir/$file" ]] && printf '%s\0' "$file"
    done \
    | tar -C "$repo_dir" --null --files-from=- --transform='s,^,thpm-working-tree/,' -czf "$archive"
checksum="$(sha256sum "$archive")"
checksum="${checksum%% *}"

cp -- "$repo_dir/packaging/aur/thpm/thpm.install" "$work_dir/thpm.install"
cat >"$work_dir/PKGBUILD" <<EOF
pkgname=thpm
pkgver=$version
pkgrel=$pkgrel
pkgdesc='Omarchy 4-native manager for external theme integrations (local working-tree build)'
arch=('any')
url='https://github.com/oldjobobo/thpm'
license=('MIT')
depends=('bash' 'python>=3.11' 'python-rich>=14' 'python-rich<16' 'python-textual>=8.2.8' 'python-textual<9')
optdepends=('omarchy: Omarchy 4 host integration (required for installation and theme operations)')
provides=('theme-hook-plugin-manager')
conflicts=('theme-hook-plugin-manager')
replaces=('theme-hook-plugin-manager')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
install=thpm.install
source=('thpm-working-tree.tar.gz')
sha256sums=('$checksum')

build() {
    cd thpm-working-tree
    /usr/bin/python -m build --wheel --no-isolation
}

package() {
    cd thpm-working-tree
    /usr/bin/python -m installer --destdir="\$pkgdir" dist/*.whl
    install -Dm644 -t "\$pkgdir/usr/share/thpm/templates" assets/templates/*
    install -Dm644 -t "\$pkgdir/usr/share/thpm/qml" assets/qml/*
    install -Dm755 assets/hooks/90-thpm "\$pkgdir/usr/share/thpm/hooks/90-thpm"
    install -Dm644 assets/compat/theme-env.sh "\$pkgdir/usr/share/thpm/compat/theme-env.sh"
    install -Dm644 -t "\$pkgdir/usr/share/thpm/vencord" assets/vencord/*
    install -Dm644 -t "\$pkgdir/usr/share/thpm/spicetify" assets/spicetify/*
    install -Dm644 LICENSE "\$pkgdir/usr/share/licenses/\$pkgname/LICENSE"
    install -Dm644 assets/vencord/LICENSE.midnight "\$pkgdir/usr/share/licenses/\$pkgname/LICENSE.midnight"
}
EOF

printf 'Building thpm %s-%s locally...\n' "$version" "$pkgrel"
(
    cd "$work_dir"
    makepkg --clean --force --noconfirm
)

packages=("$work_dir"/thpm-"$version"-"$pkgrel"-any.pkg.tar.*)
(( ${#packages[@]} == 1 )) && [[ -f "${packages[0]}" ]] || {
    printf 'Could not identify the built package\n' >&2
    exit 1
}
package="$output_dir/$(basename -- "${packages[0]}")"
cp -- "${packages[0]}" "$package"

printf '\nBuilt local package:\n  %s\n' "$package"
printf 'This package came from the current working tree and was not published.\n'

if [[ "$install_package" == true ]]; then
    printf '\nInstalling through pacman...\n'
    sudo pacman -U -- "$package"
    printf '\nInstalled package ownership:\n'
    pacman -Qo /usr/bin/thpm
    /usr/bin/thpm --version
    printf '\nSynchronize the live user integration with:\n'
    printf '  /usr/bin/thpm reconcile --refresh\n'
    printf '  /usr/bin/thpm ui install\n'
    printf '\nReturn to the published AUR package with:\n'
    printf '  yay -S thpm --rebuild\n'
else
    printf '\nInstall it when ready with:\n'
    printf '  sudo pacman -U %q\n' "$package"
fi
