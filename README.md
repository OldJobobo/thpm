# thpm

`thpm` is an Omarchy 4.x-native manager for theme integrations that Omarchy does not own. It installs one theme hook, lets Omarchy render semantic-color templates, and exposes the same plugin state through a CLI and an Omarchy Shell QML panel.

This is a new MIT-licensed implementation. It is not a continuation or relicensing of `imbypass/omarchy-theme-hook`; no source, tests, documentation, comments, or Git history from that project are included. See [PROVENANCE.md](PROVENANCE.md).

## Requirements

- Omarchy 4.x (Quattro)
- Python 3.11 or newer
- Optional: Omarchy Shell for the graphical manager

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

After installation, `thpm install` discovers Omarchy capabilities, installs the single hook, reconciles templates, and installs the QML manager when Omarchy Shell is running.

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
