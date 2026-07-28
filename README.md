# thpm

`thpm` is an Omarchy 4.x-native manager for theme integrations that Omarchy does not own. It installs one theme hook, lets Omarchy render semantic-color templates, and exposes the same plugin state through a CLI, an Omarchy Shell QML panel, and a full-screen terminal UI.

This is a new MIT-licensed implementation. It is not a continuation or relicensing of `imbypass/omarchy-theme-hook`; no source, tests, documentation, comments, or Git history from that project are included. See [PROVENANCE.md](PROVENANCE.md).

## Requirements

- Omarchy 4.x (Quattro)
- Python 3.11 or newer
- Textual 8.2.8 or newer within the supported 8.x series (installed automatically by source installs; packaged as `python-textual` on Arch)
- Optional: Omarchy Shell for the graphical manager and menu launchers

Pre-4.0 Omarchy path layouts are intentionally unsupported. Palette interpretation follows the installed Omarchy 4 `omarchy-theme-color` resolver, including aliases and derived values that Quattro accepts. Omarchy's canonical `background`, `dark_background`, `foreground`, and related long names are authoritative; THPM normalizes them to its private short-key TUI schema after resolution. If a custom theme emits conflicting canonical and short values, a non-empty canonical value wins; an empty canonical value is treated as absent so resolver output from short-only compatibility themes remains usable.

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

The AUR packages declare the former package name as replaced/conflicting, so pacman handles the package-level transition. Omarchy is listed as an optional host integration because its official packages come from Omarchy's own repository rather than the Arch repositories or the unrelated placeholder currently using the `omarchy` name on the AUR. THPM still requires Omarchy 4 to install and operate its theme integrations, verifies the needed command routes at runtime, and reports missing capabilities instead of partially installing. After installation, `thpm install` performs the per-user migration, installs the single hook, reconciles templates, installs the QML manager when Omarchy Shell is running, and completes any pending one-time template refresh migration.

Upgrades from `1.0.0rc4` need one active-theme regeneration after the corrected templates are installed. `thpm install` and the first normal `thpm reconcile` perform this versioned, idempotent migration automatically and record success under `$XDG_STATE_HOME/thpm/migrations/`; a failed refresh remains pending and is retried. Built-in source updates—including upgrades launched by rc4's older updater—detect the rollbackable activation window, defer the refresh, and report the explicit handoff command after activation. Source installation performs the refresh only after runtime, launcher, and metadata activation can no longer roll back. AUR users who update the package without rerunning installation should run:

```bash
thpm reconcile --refresh
```

## Use

```bash
thpm list
thpm enable firefox
thpm disable firefox
thpm doctor
thpm run
thpm zed status
thpm zed setup
thpm ui open
thpm tui
thpm update
thpm update check
thpm update status
thpm uninstall
```

Interactive commands use a color-aware progress surface with an animated spinner, a stage-based progress bar, elapsed time, semantic success and failure colors, a verified completion card, stage logs, changed paths, and captured command output by default. Use `--quiet` (or `-q`) for compact human output. `--verbose` remains an explicit alias for the default detailed mode. Animation is automatically disabled when output is redirected; `NO_COLOR=1` disables ANSI color, and `--json` remains stable and decoration-free for automation.

For AUR installations, `thpm update` runs Yay synchronously in the invoking terminal with routine package confirmations disabled, then reconciles integrations after installation. Password authentication can still appear normally. Callers without a TTY use an Omarchy terminal fallback so authorization and package output remain visible.

All service commands accept `--json`. The graphical control panel is available directly with `thpm ui open`, and the alternate terminal application with `thpm tui`. The graphical frontend is a normal compositor-managed window, so Hyprland controls its focus, movement, resizing, and workspace placement; a title-matched window rule can make it float by default. Omarchy Menu contains one **Theme Hook Plugins** entry; choose which frontend it opens from the **Menu launcher** control in either frontend's System section, with `thpm ui surface gui` or `thpm ui surface tui`, or flip it with `thpm ui surface toggle`. Run `thpm ui surface` without an argument to inspect the current target. Both frontends have an overview dashboard and dedicated Integrations, Doctor, and System sections for toggling plugins, checking health, reapplying or reconciling the active theme, and managing updates.

The TUI uses the active Omarchy semantic palette and falls back to a readable built-in dark theme if the palette is unavailable. Use `1`–`4` to change sections, `/` to search integrations, `Space` or `Enter` to toggle the selected integration, `r` to refresh, and `q` to quit. Mouse controls and normal Tab navigation are also supported. Terminals smaller than 80×24 show a resize prompt instead of a damaged layout.

Plugin output is isolated: one failing optional integration is reported without preventing other enabled integrations from running. Hook and JSON output distinguish applied, unchanged, skipped, and failed integrations, and Doctor flags enabled plugins that are no longer actionable. THPM-generated fallbacks are refused if Omarchy leaves an unresolved `{{ ... }}` placeholder, preventing malformed generated content from being copied into application configuration; explicit theme-provided assets keep their existing precedence. Conditional GTK CSS and validated local VS Code theme fallbacks cover Quattro native-ownership gaps only when the active theme requests them. Omarchy-native integrations are shown read-only so ownership stays clear. Disabling an integration stops future synchronization and removes its THPM template, but deliberately preserves configuration already installed into an application. Likewise, uninstall removes THPM's hook, templates, and control surfaces without deleting application configuration that may have been modified by the user.

The two Discord choices are mutually exclusive: `discord` provides the compact palette mapping, while `discord-system24` provides the full System24 surface. Both prefer a matching asset shipped by the active theme and fall back to an Omarchy-rendered semantic-palette template.

### Zed authored themes

Omarchy's optional `omazed` package is the generated-color fallback for Zed. THPM does not modify Omazed's executable, hook, or `~/.config/zed/themes/omazed.json`. Instead, the opt-in `zed-extra` integration installs a richer authored asset when the active theme provides `zed.json` or, as a compatibility fallback, `aether.zed.json`. Canonical `zed.json` wins when both exist.

THPM validates the authored JSON and normalizes its single dark or light theme to the stable name **THPM Current** at `~/.config/zed/themes/thpm-current.json`. Run `thpm zed setup` once to enable the integration, back up `settings.json` under THPM state, and safely select that stable name without discarding JSONC comments or keys outside the replaced theme value. Normal theme hooks update only the managed theme file and never rewrite Zed settings. Use `thpm zed status` to see the selected source, synchronization state, current Zed selection, and whether Omazed is available. If an authored asset disappears, THPM relinquishes its file and reports the Omazed fallback honestly; select **Omazed** in Zed if you want to switch to generated colors.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
bash -n install.sh uninstall.sh assets/hooks/90-thpm
qmllint assets/qml/Panel.qml.in  # when Qt tooling is installed
```

See [docs/architecture.md](docs/architecture.md), [docs/plugins.md](docs/plugins.md), and the [Quattro compatibility plan](docs/quattro-compatibility-plan.md) for the contracts and native-ownership boundary.

Source updates follow stable GitHub releases and require matching `thpm-<version>.tar.gz` and `thpm-<version>.tar.gz.sha256` assets. Build both from committed content with `scripts/release-assets.sh`. Package-managed installations hand updates back to AUR rather than overwriting pacman-owned files.

The stable and VCS AUR submission trees are under `packaging/aur/thpm` and `packaging/aur/thpm-git`. Replace the stable package's `SKIP` checksum with the tagged archive's SHA-256 before submission, then regenerate `.SRCINFO` with `makepkg --printsrcinfo`.

## License

MIT. See [LICENSE](LICENSE).
