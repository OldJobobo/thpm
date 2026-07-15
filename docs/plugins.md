# Plugin contract

Plugins are records in `src/thpm/registry.py` and adapters in `src/thpm/integrations.py`. A plugin may consume an Omarchy-rendered THPM template, a theme-provided optional asset, or perform a guarded external action.

Rules:

- Read colors only from the active Omarchy 4 `colors.toml` contract.
- Do not write files owned by an Omarchy-native integration.
- Preserve user-owned content; use a clearly delimited managed block when editing a shared file.
- Treat a missing optional app or theme asset as unavailable, not fatal.
- Reload only the application the adapter owns.
- Add behavioral tests for paths, generated files, and preservation behavior.

Template names start with `thpm-` and end in `.tpl`. Omarchy renders each into the active theme without the `.tpl` suffix. An adapter then atomically installs that generated output where the application expects it.

The Discord integrations are mutually exclusive. `discord` prefers a theme-provided `vencord.theme.css` and otherwise uses the semantic-palette template. `discord-system24` follows the same pattern with `vencord-system24.theme.css` and its generated System24 fallback. Both install the selected output as `vencord.theme.css` in existing supported client theme directories.

The Zellij adapter prefers a theme-provided `zellij.kdl` and otherwise uses the generated semantic-palette fallback. It normalizes the installed theme declaration to `thpm-current`, writes it to `~/.config/zellij/themes/thpm.kdl`, selects it in `config.kdl`, and removes the delimited inline block used by pre-1.0 THPM. Content outside that legacy block is preserved.
