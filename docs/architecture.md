# Architecture

THPM has four deliberately narrow layers:

1. `thpm` owns registry state, capability checks, locking, migration, and JSON responses.
2. Omarchy owns palette parsing and template rendering. THPM places opted-in `.tpl` files in `~/.config/omarchy/themed`; Omarchy emits their generated files into the active theme.
3. One hook at `~/.config/omarchy/hooks/theme-set.d/90-thpm` invokes the integration adapters after a theme switch.
4. The QML control panel is a normal compositor-managed `FloatingWindow` and a client of `thpm --json`; it does not duplicate registry or persistence logic or implement its own window-management gestures.
5. The Textual TUI runs through `thpm tui` and calls the same Python `Service` in background workers, keeping the interface responsive without creating a second state or mutation path.

The canonical palette is the active Omarchy 4 `colors.toml` as resolved by `omarchy-theme-color --all`. THPM validates the resolved semantic values instead of maintaining a second alias/derivation cascade, and never derives state from generated application files.

State is stored in `$XDG_STATE_HOME/thpm/state.toml`. Mutations use an advisory runtime lock and atomic replacement. Each hook adapter runs behind an error boundary so one integration cannot abort the remaining plugins. Adapter results distinguish applied, unchanged, skipped, and failed work; hook responses include per-status counts, changed paths, actions, warnings, and errors. Readiness checks are shared by snapshots, enable policy, Doctor, and hook execution so a plugin cannot appear actionable to one caller and inert to another.

Omarchy-native behavior is outside THPM. Foot, tmux, GNOME mode/icons, Marketplace and generated VS Code-family themes, general Obsidian theming, keyboard theming, and Omarchy terminal reload behavior are displayed as native read-only records. Two conditional compatibility integrations run after those native handlers: managed GTK CSS deployment and validated theme-only local editor extension installation. They are non-applicable, not unhealthy, when the active theme does not request those capabilities.

Source updates use stable GitHub release assets with a mandatory SHA-256 companion file. A new runtime is staged and validated before atomic activation; the previous runtime and THPM-owned integration files are restored if reconciliation fails. Pacman-owned installations are never overwritten and instead hand off to AUR in an interactive Omarchy terminal.

Source runtimes are private virtual environments containing THPM and the supported Textual 8.x dependency range. Staged updates install dependencies and import the TUI before activation, so a dependency or frontend failure participates in the same rollback boundary as integration reconciliation. Arch packages use the system `python-textual` package instead.

The TUI reads the active semantic `colors.toml` when it starts and on manual refresh. Palette errors select a bundled fallback theme and are reported as degraded presentation, not as a fatal application error.

Omarchy Menu owns one THPM entry. Its target is selected by `thpm ui surface` or the Menu launcher control in either frontend and persisted in `$XDG_STATE_HOME/thpm/ui.toml`; the CLI, GUI, and TUI all use the same service operation. Installation and self-update re-render the entry from that preference without changing the availability of either frontend.
