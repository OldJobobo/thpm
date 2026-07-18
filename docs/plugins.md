# Plugin contract

Plugins are records in `src/thpm/registry.py` and adapters in `src/thpm/integrations.py`. A plugin may consume an Omarchy-rendered THPM template, a theme-provided optional asset, or perform a guarded external action. Every adapter reports an explicit `applied`, `unchanged`, `skipped`, or `failed` outcome; an empty change list is never treated as evidence that work succeeded. Conditional compatibility integrations also report whether the active theme makes them applicable.

Rules:

- Read colors only from the active Omarchy 4 `colors.toml` contract.
- Do not write files owned by an Omarchy-native integration.
- Preserve user-owned content; use a clearly delimited managed block when editing a shared file.
- Treat a missing optional app or theme asset as unavailable, and report an enabled integration that loses a prerequisite as skipped with a reason.
- Reload only the application the adapter owns, bound the command with a timeout, and report nonzero exits.
- Add behavioral tests for paths, generated files, and preservation behavior.

Template names start with `thpm-` and end in `.tpl`. Omarchy renders each into the active theme without the `.tpl` suffix. An adapter then atomically installs that generated output where the application expects it.

The Discord integrations are mutually exclusive. `discord` prefers a theme-provided `vencord.theme.css` and otherwise uses the semantic-palette template. `discord-system24` follows the same pattern with `vencord-system24.theme.css` and its generated System24 fallback. Both install the selected output as `vencord.theme.css` in existing supported client theme directories.

The Zellij adapter prefers a theme-provided `zellij.kdl` and otherwise uses the generated semantic-palette fallback. It normalizes the installed theme declaration to `thpm-current`, writes it to `~/.config/zellij/themes/thpm.kdl`, selects it in `config.kdl`, and removes the delimited inline block used by pre-1.0 THPM. Content outside that legacy block is preserved.

The GTK compatibility integration synchronizes an active-theme `gtk.css` into THPM-owned GTK 3 and GTK 4 stylesheets and inserts delimited imports into user CSS. It removes only those managed files and blocks when the next theme does not request GTK CSS or the integration is disabled.

The local editor compatibility integration handles `local.*` descriptors backed by `vscode-extension/`. It validates that the package is a data-only theme extension, verifies descriptor/manifest identity and the contributed label, builds a deterministic temporary VSIX, and installs it only when its source hash changed or the extension is absent. Executable extensions, arbitrary contributions, symlinks, unsupported files, and prebuilt VSIX bundles are rejected.

Firefox and Zen require an initialized default browser profile, prefer their theme-provided CSS before generated CSS, and report both the managed stylesheet and `userChrome.css` import. Superfile and Cava likewise prefer their declared theme assets before generated fallbacks. Branding requires at least one branding asset, Discord requires a supported client theme directory, cliamp requires `cliamp.toml`, and Steam requires the steam-adwaita installer. The dock stylesheet has no supported live reload; THPM reports that nwg-dock-hyprland must be restarted instead of claiming a reload occurred.
