# thpm

`thpm` is an Omarchy 4.x-native manager for theme integrations that Omarchy does not own. It installs one theme hook, lets Omarchy render semantic-color templates, and exposes the same plugin state through a CLI, an Omarchy Shell QML panel, and a full-screen terminal UI.

This is a new MIT-licensed implementation. It is not a continuation or relicensing of `imbypass/omarchy-theme-hook`; no source, tests, documentation, comments, or Git history from that project are included. See [PROVENANCE.md](PROVENANCE.md).

## Requirements

- Omarchy 4.x (Quattro)
- Python 3.11 or newer
- Textual 8.2.8 or newer within the supported 8.x series (installed automatically by source installs; packaged as `python-textual` on Arch)
- Optional: Omarchy Shell for the graphical manager and menu launchers

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

The source installer first migrates an existing `theme-hook-plugin-manager` installation, then installs THPM and its pinned Textual dependency range into a private Python runtime at `~/.local/share/thpm/runtime`. Pip runs only inside that isolated virtual environment, preserving Arch Linux's externally-managed system Python. The installer preserves enabled plugin state, archives recognized legacy files under `~/.local/state/thpm/legacy-backups/`, removes obsolete legacy launchers and control files, and installs the hook plus both control-panel launchers. Unrecognized user files are left in place. If a custom hook still sources the former helper path, THPM installs a small independently authored transition shim for its status helpers instead of retaining the old library.

The AUR packages declare the former package name as replaced/conflicting, so pacman handles the package-level transition. After installation, `thpm install` performs the per-user migration and discovers Omarchy capabilities, installs the single hook, reconciles templates, and installs the QML manager when Omarchy Shell is running.

## Use

```bash
thpm list
thpm enable firefox
thpm disable firefox
thpm doctor
thpm run
thpm ui open
thpm tui
thpm update check
thpm update apply
thpm uninstall
```

All service commands accept `--json`. The graphical panel is available directly with `thpm ui open`, and the alternate terminal application with `thpm tui`. Omarchy Menu contains one **Theme Hook Plugins** entry; choose which frontend it opens with `thpm ui surface gui`, `thpm ui surface tui`, or flip it with `thpm ui surface toggle`. Run `thpm ui surface` without an argument to inspect the current target. Both frontends have an overview dashboard and dedicated Integrations, Doctor, and System sections for toggling plugins, checking health, reapplying or reconciling the active theme, and managing updates.

The TUI uses the active Omarchy semantic palette and falls back to a readable built-in dark theme if the palette is unavailable. Use `1`–`4` to change sections, `/` to search integrations, `Space` or `Enter` to toggle the selected integration, `r` to refresh, and `q` to quit. Mouse controls and normal Tab navigation are also supported. Terminals smaller than 80×24 show a resize prompt instead of a damaged layout.

Plugin output is isolated: one failing optional integration is reported without preventing other enabled integrations from running. Omarchy-native integrations are shown read-only so ownership stays clear.

The two Discord choices are mutually exclusive: `discord` provides the compact palette mapping, while `discord-system24` provides the full System24 surface. Both prefer a matching asset shipped by the active theme and fall back to an Omarchy-rendered semantic-palette template.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
bash -n install.sh uninstall.sh assets/hooks/90-thpm
```

See [docs/architecture.md](docs/architecture.md) and [docs/plugins.md](docs/plugins.md) for the contracts.

Source updates follow stable GitHub releases and require matching `thpm-<version>.tar.gz` and `thpm-<version>.tar.gz.sha256` assets. Build both from committed content with `scripts/release-assets.sh`. Package-managed installations hand updates back to AUR rather than overwriting pacman-owned files.

The stable and VCS AUR submission trees are under `packaging/aur/thpm` and `packaging/aur/thpm-git`. Replace the stable package's `SKIP` checksum with the tagged archive's SHA-256 before submission, then regenerate `.SRCINFO` with `makepkg --printsrcinfo`.

## License

MIT. See [LICENSE](LICENSE).
