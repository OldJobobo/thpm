# THPM

**Theme Hook Plugin Manager for Omarchy 4**

THPM keeps applications outside Omarchy’s native theme coverage synchronized with your active Omarchy theme. Choose the integrations you want, switch themes normally, and THPM applies each supported color surface from one graphical control panel, terminal UI, or CLI.

## What THPM gives you

- **One control center** for browsing, enabling, disabling, and checking theme integrations.
- **Automatic theme synchronization** through Omarchy’s normal theme-change hook.
- **Graphical and terminal interfaces** backed by the same state and safety rules.
- **Safe cleanup** that restores displaced files or previous selections when restoration data is available.
- **Honest outcomes** for applied, unchanged, skipped, unavailable, and failed integrations.
- **Private support reports** that users can send to the maintainer without exposing configuration contents or raw environments.

THPM also shows Omarchy-owned integrations as read-only records, so it is clear which application owns each theme surface.

## Requirements

- Omarchy 4.x
- Python 3.11 or newer
- Textual 8.2.8 or newer within the supported 8.x series (installed automatically by source installs; packaged as `python-textual` on Arch)
- Optional: Omarchy Shell for the graphical control panel and menu entry
- Optional: `nautilus` and `nautilus-python` for the default-disabled Nautilus palette integration

Earlier Omarchy layouts are not supported.

## Install

Install THPM from the AUR through Omarchy, then complete its user setup:

```bash
omarchy pkg aur add thpm
thpm install
```

Open **Theme Hook Plugins** from Omarchy Menu, or launch either interface directly:

```bash
thpm ui open
thpm tui
```

Use `thpm install --no-ui` if you only want the terminal UI and CLI. Add the graphical control panel later with `thpm ui install`.

### Install from a source checkout

```bash
./install.sh
```

This creates a private user installation. Use either the AUR package or the source installation, not both.

## Quick start

See what THPM can manage on your system:

```bash
thpm list
thpm doctor
```

Enable an available integration. Enabling it applies the active theme immediately and keeps it synchronized after later theme changes:

```bash
thpm enable fzf
thpm doctor fzf
```

Disable it and restore its prior managed state:

```bash
thpm disable fzf
```

Every integration is disabled by default for new installations. Integrations marked **Experimental** are opt-in and may still need real-application certification. Existing schema-1 state from older releases can preserve previously saved enablement, including values inherited from former defaults; after upgrading, review `thpm status` and disable any integration you did not intentionally choose. `fzf` and `zellij` are currently Supported; see the [integration support register](docs/integration-support.md) for the current evidence and status of every integration.

## Using THPM

| Interface | Open it | Best for |
| --- | --- | --- |
| Graphical control panel | Omarchy Menu or `thpm ui open` | Everyday integration management |
| Terminal UI | `thpm tui` | Full-screen terminal management |
| CLI | `thpm status`, `thpm enable ID` | Shell workflows and automation |

The graphical control panel and terminal UI share four sections:

- **Overview** — integration and system status at a glance.
- **Integrations** — search, inspect, enable, and disable application adapters.
- **Doctor** — readiness checks and actionable warnings.
- **System** — apply the active theme, reconcile generated files, choose the menu interface, and manage updates.

In the terminal UI, use `1`–`4` to change sections, `/` to search, `Space` or `Enter` to toggle an integration, `r` to refresh, and `q` to quit. Mouse and normal Tab navigation are also supported. Use a terminal at least 80×24.

Useful CLI commands:

```bash
thpm status
thpm list
thpm enable <integration>
thpm disable <integration>
thpm doctor [integration]
thpm run
thpm reconcile --refresh
thpm report [integration]
thpm update
thpm uninstall
```

Add `--json` to non-interactive commands when you need machine-readable output.

## Integrations

THPM currently covers these application groups:

| Group | Integrations |
| --- | --- |
| Terminal | Fish, fzf, Superfile, Zellij |
| Desktop | GTK CSS compatibility, Branding extras, Qt6ct, nwg-dock-hyprland |
| Editors and writing | Local VS Code themes, Typora, Obsidian Terminal, Zed authored themes, Hermes |
| Browsers | Firefox, Zen Browser, Qutebrowser |
| Messaging | Discord/Vencord, Discord System24 |
| Media | Spotify/Spicetify, Cava, cliamp |
| Games | Steam, Heroic |
| Compatibility | Pi live theme reload |

`fzf` and Zellij are Supported. All other active integrations are Experimental and opt-in. Omarchy-owned integrations appear as read-only records rather than duplicate controls. The [integration support register](docs/integration-support.md) is the authoritative status list.

## Application setup

Some integrations require the application or its theming tool to be initialized first. `thpm doctor <integration>` shows the exact missing prerequisite.

### Steam and Adwaita-for-Steam

The Omarchy way to install the recommended [AdwSteamGtk](https://github.com/Foldex/AdwSteamGtk) manager is:

```bash
omarchy pkg aur add adwsteamgtk
```

After installing AdwSteamGtk, you should:

1. Open **AdwSteamGtk** from your application launcher, or run `adwaita-steam-gtk`.
2. Choose your preferred skin options.
3. Select **Install** to apply Adwaita-for-Steam.
4. Fully exit and reopen Steam.

You do not need to keep AdwSteamGtk running in the background. AdwSteamGtk is currently independent of THPM.

THPM’s Experimental Steam integration does not yet recognize AdwSteamGtk. It requires the standalone installer at `~/.local/share/steam-adwaita/install.py` and otherwise remains **Unavailable**. Run `thpm report steam` to confirm what THPM detected. THPM never terminates Steam because doing so could interrupt a game or download.

### Nautilus

The Experimental `nautilus-palette` integration requires separately installed `nautilus` and `nautilus-python`; THPM diagnoses these optional dependencies but never installs them. When enabled, it restorably installs an XDG-aware Nautilus Python extension and atomically generated palette CSS. Extension changes require a Nautilus restart, while later CSS-only theme changes reload in open windows. Disable and uninstall restore displaced files only while THPM still owns them and preserve later user edits.

### GNOME accent compatibility

`gnome-accent-compat` is a separate Experimental opt-in because it changes the desktop-wide `org.gnome.desktop.interface accent-color` setting for all libadwaita applications. It maps the active semantic accent to GNOME's supported named accents, records the previous value, and restores it only while the current value still matches THPM's last write. Missing schema, key, write, or desktop DBus access fails closed; concurrent user changes are preserved.

### Spotify

Complete Spicetify’s one-time backup, then enable the integration:

```bash
spicetify backup apply
thpm enable spotify
```

THPM updates the Omarchy color scheme without overwriting an existing Spicetify stylesheet.

### Cava

Cava 0.10.6 or newer is required. Setup changes Cava’s selected color theme, so confirmation is required. A saved `cava = true` value from releases where Cava was enabled by default remains disabled until confirmed setup records a durable opt-in marker. THPM preserves comments, formatting, symlinked dotfile layouts, unrelated edits, and the previous selector for guarded restoration:

```bash
thpm enable cava
thpm doctor cava
```

If the selector or generated theme needs repair:

```bash
thpm doctor cava --fix
```

### Firefox and Zen

Launch the browser once before enabling its integration so a default profile exists. THPM manages its own `userChrome.css` import and restores that managed change when disabled.

### Discord

`discord` and `discord-system24` are mutually exclusive Vencord themes. Enable only the surface you want. Both require an existing supported client theme directory.

### Zed authored themes

When the active Omarchy theme supplies `zed.json` or `aether.zed.json`, enable authored-theme synchronization with:

```bash
thpm enable zed-extra
```

Use `thpm zed status` to inspect the selected source and Zed theme state.

## Restart behavior

Choose whether safely restartable running applications restart automatically after a theme change or remain open with a notification:

```bash
thpm config restart-policy automatic
thpm config restart-policy notify
```

THPM never launches an application that was closed. Applications without a safe restart contract are reported instead of being killed.

## Troubleshooting and support reports

Start with Doctor:

```bash
thpm doctor
thpm doctor steam
```

Create a report for the affected integration:

```bash
thpm report steam
```

Reports are written to `~/.local/state/thpm/reports/`. Send the generated JSON file to the THPM maintainer.

Support reports include THPM and runtime versions, the active theme, integration readiness, Doctor results, and recent bounded operation outcomes. They omit file contents, raw process environments, host identity, unrelated arguments, and unbounded command output. Home paths and secret-like values are redacted.

THPM’s private operation journal is stored under `~/.local/state/thpm/logs/` with mode `0600` and bounded rotation. Logging is best-effort and records outcomes and durations without raw environments or configuration contents. Reports normalize home paths, remove URL credentials, queries, and fragments, redact secret-like fields and authorization values, and cap recent history and total size.

## Update

Update THPM and synchronize the active theme from any interface, or run:

```bash
thpm update
```

After a direct package-manager upgrade, refresh generated outputs and the graphical control panel when requested:

```bash
thpm reconcile --refresh
thpm ui install
```

Opening the graphical control panel also synchronizes its installed files automatically.

## Uninstall

For an AUR installation, remove THPM’s managed integrations first, then remove the package:

```bash
thpm uninstall && omarchy pkg drop thpm
```

For a source installation, run this from its checkout:

```bash
./uninstall.sh
```

THPM preserves unrelated and user-modified configuration. If a managed file cannot be restored safely, uninstall reports the retained path and keeps the recovery data instead of claiming success. External tools remain responsible for reversing their own effects, including an Adwaita-for-Steam patch.

## Documentation

- [Integration support and certification](docs/integration-support.md)
- [Integration behavior and prerequisites](docs/plugins.md)
- [Architecture](docs/architecture.md)
- [Visual architecture map](docs/architecture-map.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Provenance](PROVENANCE.md)

## License

THPM is available under the [MIT License](LICENSE).
