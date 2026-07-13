# thpm

`thpm` is an Omarchy 4.x-native manager for theme integrations that Omarchy does not own. It installs one theme hook, lets Omarchy render semantic-color templates, and exposes the same plugin state through its CLI and the native Omarchy menu.

This is a new MIT-licensed implementation. It is not a continuation or relicensing of `imbypass/omarchy-theme-hook`; no source, tests, documentation, comments, or Git history from that project are included. See [PROVENANCE.md](PROVENANCE.md).

## Requirements

- Omarchy 4.x (Quattro)
- Python 3.11 or newer
- Optional: Omarchy Shell for the native menu manager

Pre-4.0 Omarchy layouts and legacy palette aliases are intentionally unsupported.

## Install

For a source checkout:

```bash
./install.sh
```

For Arch Linux, build either package from `packaging/aur`:

```bash
(cd packaging/aur/thpm && makepkg -si)
```

The source installer first migrates an existing `theme-hook-plugin-manager` installation, then installs the new package into a private, dependency-free Python runtime at `~/.local/share/thpm/runtime`. It does not invoke pip and respects Arch Linux's externally-managed Python environment. It preserves enabled plugin state, archives recognized legacy files under `~/.local/state/thpm/legacy-backups/`, removes obsolete legacy launchers and control files, and installs the new hook and Omarchy menu extension. Unrecognized user files are left in place. If a custom hook still sources the former helper path, THPM installs a small independently authored transition shim for its status helpers instead of retaining the old library.

The AUR packages declare the former package name as replaced/conflicting, so pacman handles the package-level transition. After installation, `thpm install` performs the per-user migration, discovers Omarchy capabilities, installs the single hook, reconciles templates, and installs the native menu extension.

## Use

```bash
thpm list
thpm enable firefox
thpm disable firefox
thpm doctor
thpm run
thpm ui open
thpm uninstall
```

All commands accept `--json`. The GUI is available at **Omarchy Menu → Style → Theme Hook Plugins** after installation.

Plugin output is isolated: one failing optional integration is reported without preventing other enabled integrations from running. Omarchy-native integrations are shown read-only so ownership stays clear.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
bash -n install.sh uninstall.sh assets/hooks/90-thpm
```

See [docs/architecture.md](docs/architecture.md) and [docs/plugins.md](docs/plugins.md) for the contracts.

The stable and VCS AUR submission trees are under `packaging/aur/thpm` and `packaging/aur/thpm-git`. Replace the stable package's `SKIP` checksum with the tagged archive's SHA-256 before submission, then regenerate `.SRCINFO` with `makepkg --printsrcinfo`.

## License

MIT. See [LICENSE](LICENSE).
