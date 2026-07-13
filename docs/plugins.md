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
