# Quattro native-ownership compatibility plan

Status: implemented in the working tree; upstream Omarchy follow-up and release packaging remain pending

## Goal

THPM 1.x remains an Omarchy 4/Quattro-native integration manager. It does not restore the pre-1.0 hook runtime or duplicate Omarchy's theme engine. It temporarily covers capabilities that legacy THPM supplied and that Omarchy's declared native handlers do not yet implement.

The compatibility behavior continues to run through the single `90-thpm` dispatcher after Omarchy's native post-theme commands.

## Verified gaps

### GTK CSS

Quattro's `omarchy-theme-set-gnome` sets color mode, `Adwaita`/`Adwaita-dark`, and icons. It does not consume an active-theme `gtk.css`. Current THPM has no GTK adapter and reports only the narrower `native-gnome` record.

Legacy THPM's `10-gtk.sh` deployed theme CSS to GTK 3 and GTK 4 after Omarchy's native action. Retiring that adapter before native parity caused a real compatibility regression.

### Bundled local VS Code themes

Quattro's `omarchy-theme-set-vscode` supports Marketplace extension IDs and its own generated `local.omarchy-theme` extension. A descriptor naming a theme-bundled `local.*` extension is still passed to `--install-extension` as if it were a Marketplace ID, and the requested theme name is selected even if installation fails.

Legacy THPM's `30-vscode.sh` packaged a theme's `vscode-extension/` source as a VSIX, installed it, and used a source hash to avoid unnecessary reinstallations. Current THPM has no equivalent adapter and reports VS Code as wholly native-owned.

### Palette resolution

THPM currently validates raw TOML against a fixed set of semantic keys. That is not the complete Quattro contract.

Quattro's canonical consumer is `omarchy-theme-color --file COLORS --all`. It accepts canonical semantic files and applies Omarchy-owned aliases and derivations for:

- `background`/`foreground` and `color0..color15`;
- mode and `theme_type`;
- missing shades and bright colors;
- selection, muted, orange, brown, and related semantic roles.

This is not only a third-party legacy-theme concern. Current stock Omarchy themes such as Last Horizon, Solitude, Vantablack, and White omit raw values that THPM requires. THPM rejects those raw files, while `omarchy-theme-color --all` resolves every value THPM needs.

Therefore, calling the Omarchy resolver is the native implementation. Reimplementing its alias cascade in THPM or requiring every derived value to be written literally would create a second, drifting theme contract.

## Design decisions

### 1. Follow the Omarchy palette API

Change `palette.load()` to resolve through:

```bash
omarchy-theme-color --file <colors.toml> --all
```

The loader will:

1. locate `omarchy-theme-color` on `PATH`;
2. execute it with a short timeout and captured output;
3. parse its tab-separated key/value output;
4. require the semantic values THPM actually consumes;
5. validate mode and resolved color formats;
6. return only the normalized values needed by THPM.

If the command is unavailable, the current strict semantic TOML parser may remain as a diagnostic fallback. THPM must not embed its own copy of Omarchy's alias and color-mixing implementation.

Doctor and the TUI will use the same loader. A palette accepted and fully resolved by Omarchy will therefore be accepted by THPM. Resolver failure, malformed output, or missing resolved values remains an error.

Update the README requirement from “legacy palette aliases are intentionally unsupported” to: pre-4 path layouts are unsupported, while color resolution follows the installed Omarchy 4 resolver.

### 2. Add conditional compatibility integrations

Add two named integrations:

- `gtk-css-compat`
- `vscode-local-compat`

They are enabled by default but distinguish applicability from readiness:

- not applicable: the active theme does not request the capability;
- unavailable: the theme requests it but a prerequisite is missing;
- applied, unchanged, or failed: normal execution outcomes.

A non-applicable compatibility integration does not create warnings or count as attention. This avoids presenting a harmless conditional fallback as a broken or successful no-op.

Existing native records remain read-only but describe their real scope:

- GNOME mode and icons are native;
- Marketplace and generated editor themes are native;
- theme-provided GTK CSS and bundled local editor extensions use THPM compatibility coverage until Omarchy advertises parity.

### 3. Deploy GTK CSS through managed files

When the active theme provides `gtk.css`:

1. atomically synchronize it to:
   - `~/.config/gtk-3.0/thpm-theme.css`;
   - `~/.config/gtk-4.0/thpm-theme.css`;
2. add a delimited import at the start of each user `gtk.css`;
3. preserve all user content outside the managed block;
4. report changed and already-current files;
5. report that running GTK applications may need to restart.

When the next theme does not provide `gtk.css`, remove only the managed imports and THPM-owned stylesheets so stale theme CSS does not survive a theme switch.

Do not initially kill Nautilus or `xdg-desktop-portal-gtk`, overwrite complete user stylesheets, or fight Omarchy's native mode selection. Validate GTK 3, GTK 4, libadwaita, and Nautilus behavior first. Restore `adw-gtk3[-dark]` selection only if functional testing proves it is required and the package is present.

### 4. Restore local editor themes with a data-only boundary

Apply the fallback only when:

- `vscode.json` declares a `local.*` extension ID;
- `vscode-extension/package.json` exists;
- `publisher.name` matches the descriptor ID;
- the manifest contributes the requested theme label.

Before packaging, reject executable extension capabilities, including `main`, `browser`, activation events, scripts, native binaries, symlinks, and unsupported contribution types. Permit only a theme manifest, theme JSON, documentation, and static assets.

Then:

1. hash normalized source paths and contents;
2. build a deterministic temporary VSIX in Python;
3. store per-editor source hashes under `$XDG_STATE_HOME/thpm/`;
4. install only when the matching extension is absent or the source changed;
5. support available VS Code, Insiders, VSCodium, and Cursor commands;
6. bound subprocesses and capture failures;
7. verify the extension appears in `--list-extensions` before reporting success.

Do not initially accept arbitrary prebuilt VSIX files. The source-only, theme-only contract is safer and aligns with the data-only direction in the plugin security design.

Omarchy's native handler already writes `workbench.colorTheme`; the fallback should install and verify the missing extension rather than create a competing settings editor.

### 5. Make native coverage diagnostic

Normal status can use cheap file and source-hash checks. Doctor performs bounded editor-command verification.

Warn only when a capability is requested but unsatisfied, for example:

- active `gtk.css` is not synchronized;
- a `local.*` descriptor has no valid bundled source;
- the local extension is absent or stale;
- the requested theme label does not match the manifest.

Do not report native records as unhealthy merely because an optional asset is absent.

## Implementation order

1. Add palette resolver tests and switch `palette.load()` to `omarchy-theme-color`.
2. Update Doctor, TUI palette loading, README, and architecture documentation.
3. Add applicability/readiness support for conditional compatibility integrations.
4. Implement managed GTK CSS synchronization and cleanup.
5. Implement validated theme-only VSIX packaging, hashing, installation, and verification.
6. Add native coverage diagnostics and frontend copy.
7. Add migration aliases:
   - legacy `gtk` to `gtk-css-compat`;
   - legacy `vscode` to `vscode-local-compat`.
8. Validate on canonical semantic themes, resolver-derived stock themes, a legacy ANSI-compatible theme, Dos-Moos, and themes requesting neither fallback.

## Acceptance tests

### Palette

- complete semantic palette resolves;
- legacy ANSI palette resolves through Omarchy;
- stock themes that omit derived values resolve;
- light-mode and `theme_type` behavior matches Omarchy;
- resolver timeout, nonzero exit, malformed rows, missing keys, and invalid values fail clearly;
- strict fallback works when the resolver is absent.

### GTK

- GTK 3 and GTK 4 imports are installed atomically;
- user CSS outside managed blocks survives;
- repeated application is unchanged;
- switching to a theme without `gtk.css` removes only THPM-owned content;
- restart guidance is reported without killing applications.

### VS Code family

- a valid theme-only local extension installs once;
- unchanged source is not reinstalled;
- changed source is reinstalled;
- Marketplace descriptors remain native and untouched;
- manifest/descriptor identity mismatch fails;
- executable or unsafe extension content is rejected;
- install timeout and nonzero exit are isolated and reported;
- installed extension and contributed label are verified.

### Ownership and UI

- non-applicable fallbacks create no attention;
- requested but unavailable fallbacks create actionable warnings;
- native records describe only native coverage;
- all compatibility outcomes appear in CLI, JSON, TUI, and QML consistently.

## Implementation outcome

The working-tree implementation now includes:

- canonical palette resolution through `omarchy-theme-color --all`, with strict semantic fallback only when the resolver is absent;
- conditional applicability in the shared plugin model and both frontends;
- managed GTK 3/GTK 4 imports, stale-output cleanup, symlink preservation, and restart guidance;
- data-only local editor source validation, identity and contribution checks, traversal/symlink/file/count/size limits, deterministic VSIX packaging, Omarchy toggle support, source markers, bounded installation, and registration verification;
- narrowed native ownership descriptions, synchronization warnings, Doctor verification, and legacy migration aliases.

Validation completed locally:

- all 92 behavioral tests pass;
- every installed stock Omarchy theme resolves through the new palette loader;
- representative local Aether theme bundles validate successfully;
- a generated VSIX installs and registers in isolated VS Code user-data and extension directories;
- QML passes `qmllint`;
- the wheel build includes the compatibility module.

No live GTK configuration or normal VS Code profile was modified during validation.

## Upstream boundary

Open corresponding Omarchy issues for official GTK CSS ownership, bundled local editor-extension handling, and capability reporting. Keep THPM fallbacks idempotent and conditional so they naturally become unchanged or removable when the installed Omarchy version gains equivalent native behavior.
