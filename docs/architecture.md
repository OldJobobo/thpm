# Architecture

THPM has four deliberately narrow layers:

1. `thpm` owns registry state, capability checks, locking, migration, and JSON responses.
2. Omarchy owns palette parsing and template rendering. THPM places opted-in `.tpl` files in `~/.config/omarchy/themed`; Omarchy emits their generated files into the active theme.
3. One hook at `~/.config/omarchy/hooks/theme-set.d/90-thpm` invokes the integration adapters after a theme switch.
4. The Omarchy menu extension invokes narrow CLI state checks and toggle actions. THPM owns no compositor surface of its own.

The canonical palette is the active Omarchy 4 `colors.toml`. THPM requires the Quattro semantic keys and never derives state from generated application files.

State is stored in `$XDG_STATE_HOME/thpm/state.toml`. Mutations use an advisory runtime lock and atomic replacement. Each hook adapter runs behind an error boundary so an optional application cannot abort the remaining plugins.

Omarchy-native behavior is outside THPM. Foot, tmux, GNOME, VS Code/Cursor, general Obsidian theming, keyboard theming, and Omarchy terminal reload behavior are displayed as native read-only records.
