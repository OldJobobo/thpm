# thpm

`thpm` is an Omarchy 4.x-native manager for theme integrations that Omarchy does not own. It installs one theme hook, lets Omarchy render semantic-color templates, and exposes the same plugin state through a CLI, an Omarchy Shell QML panel, and a full-screen terminal UI.

This is a new MIT-licensed implementation. It is not a continuation or relicensing of `imbypass/omarchy-theme-hook`; no source, tests, documentation, comments, or Git history from that project are included. See [PROVENANCE.md](PROVENANCE.md).

## Requirements

- Omarchy 4.x (Quattro)
- Python 3.11 or newer
- Textual 8.2.8 or newer within the supported 8.x series (installed automatically by source installs; packaged as `python-textual` on Arch)
- Optional: Omarchy Shell for the graphical manager and menu launchers

Pre-4.0 Omarchy path layouts are intentionally unsupported. Palette interpretation follows the installed Omarchy 4 `omarchy-theme-color` resolver, including aliases and derived values that Quattro accepts. Omarchy's canonical `background`, `dark_background`, `foreground`, and related long names are authoritative; THPM normalizes them to its private short-key TUI schema after resolution. If a custom theme emits conflicting canonical and short values, a non-empty canonical value wins; an empty canonical value is treated as absent so resolver output from short-only compatibility themes remains usable.

## Integration support status

An integration appearing in THPM does not by itself establish end-to-end application support. The current [integration support register](docs/integration-support.md) records the reference Omarchy environment, each active adapter's default and lifecycle disposition, a repeatable certification protocol, adapter-specific real-application evidence, retired cleanup, and the maintainer signoff template. At this audit point, every active adapter is Experimental, visibly labeled, and default-disabled for new state. Existing schema-1 `true` values are grandfathered because older releases serialized inherited defaults and cannot distinguish them from later explicit choices; they are not evidence of certification or opt-in. Existing users should review and disable integrations they do not want. Cava remains the exception and still requires its separate consent marker. Automated coverage varies from shared rendering/ownership machinery to integration-specific lifecycle tests, but no row yet records all required application versions, observed loader effects, and maintainer signoff. Treat these adapters as Experimental built-ins rather than stable compatibility guarantees until their rows are promoted through reviewed evidence.

## Install

### Omarchy / AUR

Install the stable package, then complete the per-user setup:

```bash
omarchy pkg aur add thpm
thpm install
```

The package installs THPM and its assets under `/usr`. The required `thpm install` step creates your theme hook and templates, migrates an older installation, and deploys the graphical manager and menu entry under your user configuration. Pacman cannot safely perform that per-user setup on its own. Use `thpm install --no-ui` only when you intentionally do not want the graphical manager; you can add it later with `thpm ui install`.

While AUR submissions are unavailable, install or upgrade directly from the newest published GitHub release with:

```bash
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves GitHub's newest published release—including release candidates—then downloads its source archive and mandatory SHA-256 file, verifies the source, builds the stable Arch package with `makepkg`, installs it through pacman, and runs the per-user `thpm install` step. It does not install an untracked Python runtime or replace pacman ownership. To inspect it first, download the same URL to a file before running it; pass an explicit version argument to pin an older release.

To build locally instead, choose either the stable package or the development package; they conflict, so install only one:

```bash
(cd packaging/aur/thpm && makepkg -si)       # stable release
# or
(cd packaging/aur/thpm-git && makepkg -si)   # latest main branch
thpm install
```

After a direct package-manager upgrade, reconcile generated theme output when the release requests it:

```bash
thpm reconcile --refresh
```

Once the self-healing menu launcher has been installed, the graphical manager needs no separate redeployment step after upgrades. Its menu action compares packaged and deployed frontend assets, repairs plugin discovery and enablement, verifies that the asynchronous QML panel actually opened, and falls back to the terminal interface in a floating window if graphical recovery fails. An idempotent user `post-update` hook keeps that stable launcher in place before Omarchy's AUR phase; the next click synchronizes any newer QML installed later in the update.

`thpm update` synchronizes package state, integrations, the active theme, and the graphical control panel from the CLI, TUI, or GUI. Direct `pacman` or AUR-helper upgrades cannot safely rewrite user configuration from the package transaction, so the stable launcher performs that synchronization in the desktop user's context.

### Source checkout

```bash
./install.sh
```

The source installer builds and validates a private runtime at `~/.local/share/thpm/runtime`, activates it with rollback protection, and then runs the per-user migration and integration setup. Pip runs only inside that isolated environment and installs the exact universal wheels pinned with SHA-256 hashes in `requirements-source.lock`; source distributions and unlisted dependency versions are rejected. Recognized legacy files are archived under `~/.local/state/thpm/legacy-backups/`; unrecognized user files are left alone.

## Use

Common commands:

```bash
thpm list
thpm status
thpm enable firefox
thpm disable firefox
thpm doctor
thpm run
thpm reconcile
thpm reconcile --refresh
thpm zed status
thpm zed setup
thpm ui status
thpm ui install
thpm ui sync
thpm ui open
thpm ui remove
thpm tui
thpm update
thpm update check
thpm update status
thpm uninstall
```

Interactive commands use a color-aware live progress surface. `thpm run` advances through the enabled integrations as they actually start and finish, showing the current integration and a truthful completed/total count instead of waiting at a fabricated outer-stage percentage. Each integration outcome is appended to a persistent outline as soon as it completes while the live bar continues beneath it. Use `--verbose` (or `-v`) to add adapter details, stage history, changed paths, and captured command output, or `--quiet` (or `-q`) to suppress progress. Redirected progress is emitted as flushed plain lines, `NO_COLOR=1` disables ANSI color, and `--json` remains a single stable, decoration-free document for automation.

For AUR installations, `thpm update` runs Yay synchronously in the invoking terminal with routine package confirmations disabled, then reconciles integrations after installation. Password authentication can still appear normally. Callers without a TTY use an Omarchy terminal fallback so authorization and package output remain visible.

Non-interactive service commands accept `--json`. The interactive `thpm tui` command intentionally rejects JSON mode. The graphical control panel is available directly with `thpm ui open`, and the alternate terminal application with `thpm tui`. The graphical frontend is a normal compositor-managed window, so Hyprland controls its focus, movement, resizing, and workspace placement; a title-matched window rule can make it float by default. Omarchy Menu contains one **Theme Hook Plugins** entry; choose which frontend it opens from the **Menu launcher** control in either frontend's System section, with `thpm ui surface gui` or `thpm ui surface tui`, or flip it with `thpm ui surface toggle`. Run `thpm ui surface` without an argument to inspect the current target. Both frontends have an overview dashboard and dedicated Integrations, Doctor, and System sections for toggling plugins, checking health, reapplying or reconciling the active theme, and managing updates.

The TUI uses the active Omarchy semantic palette and falls back to a readable built-in dark theme if the palette is unavailable. Use `1`–`4` to change sections, `/` to search integrations, `Space` or `Enter` to toggle the selected integration, `r` to refresh, and `q` to quit. Mouse controls and normal Tab navigation are also supported. Terminals smaller than 80×24 show a resize prompt instead of a damaged layout.

Plugin output is isolated: one failing optional integration is reported without preventing other enabled integrations from running. Hook and JSON output distinguish applied, unchanged, skipped, and failed integrations, and Doctor flags enabled plugins that are no longer actionable. Terminal-driven Omarchy theme changes send the same live integration outline and final summary to stderr because Omarchy discards normal hook stdout. `thpm run` consumes the same structured hook events through a private channel while the refresh is still running, then returns the authoritative final report and failure status without executing adapters twice. Redirected output stays plain, and `NO_COLOR=1` disables ANSI color. THPM-generated fallbacks are refused if Omarchy leaves an unresolved `{{ ... }}` placeholder, preventing malformed generated content from being copied into application configuration; explicit theme-provided assets keep their existing precedence. Conditional GTK CSS and validated local VS Code theme fallbacks cover Quattro native-ownership gaps only when the active theme requests them. Omarchy-native integrations are shown read-only so ownership stays clear. Disabling an integration stops future synchronization, removes its rendered THPM template, and restores displaced files or prior selections when THPM has restoration data. Unrelated and user-modified configuration is preserved. Uninstall applies the same guarded cleanup before removing THPM's hook, templates, and control surfaces. If promised restoration cannot be completed, disable or uninstall fails with `cleanupIncomplete`, reports retained paths and a retry command, and keeps the recovery records needed for another attempt. The source uninstaller also retains its private runtime and launcher until service cleanup succeeds.

### User preferences

THPM stores user-editable preferences in `~/.config/thpm/config.toml`. Choose whether restart-capable running applications restart automatically after a theme change or remain open while THPM sends one desktop notification naming the applications that still need restart:

```bash
thpm config
thpm config restart-policy automatic
thpm config restart-policy notify
```

The same control appears as **Restart apps automatically** in the GUI and TUI System sections. The default is `automatic`; THPM never launches an application that was closed. Applications without a safe restart contract, including generic GTK applications and nwg-dock-hyprland, are always reported rather than killed. **Apply active theme** in either frontend, and the equivalent `thpm run`, explicitly force restart-required adapters such as Spotify even when their managed files are already current; ordinary theme hooks retain no-op behavior when nothing changed.

The two Discord choices are mutually exclusive. `discord` provides an Omarchy-colored Midnight surface from THPM's MIT-licensed vendored base, while `discord-system24` provides the more opinionated System24 surface. Both prefer a matching asset shipped by the active theme and fall back to an Omarchy-rendered semantic-palette template. The Midnight fallback imports THPM's hosted base at runtime, so it requires network access; the hosted `main` artifact intentionally remains updateable so Discord selector repairs can land without waiting for a THPM package release.

The opt-in `pi-hot-reload` compatibility integration emits a metadata-only change event after Omarchy atomically replaces `~/.pi/agent/themes/omarchy-system.json`. It first verifies that the installed file exactly matches the current native `pi.json`, then advances only its modification time while preserving its contents, access time, and inode. Long-lived Pi sessions currently using `omarchy-system`—including sessions inside Zellij, Splinterm, and similar persistent terminals—can then repaint; sessions using another global, project, CLI, automatic, or in-memory theme ignore the event.

Cava integration is opt-in because enabling it safely changes the `[color] theme` selector in Cava's user configuration. A saved `cava = true` value from releases where Cava was enabled by default is treated as disabled until confirmed setup succeeds and records a durable opt-in marker. THPM preserves comments, formatting, symlinked dotfile layouts, unrelated edits, and the previous selector for guarded restoration on disable or uninstall. Run `thpm doctor cava` for detailed checks or `thpm doctor cava --fix` for a confirmed transactional repair. Only running Cava processes whose effective config and theme directory can be verified are sent a PID-specific `SIGUSR1`; ambiguous processes are left alone and reported as requiring a manual reload or restart. Cava 0.10.6 or newer is required.

THPM keeps a bounded, mode-`0600` structured operation journal under `~/.local/state/thpm/logs/`. It records integration outcomes and durations without raw environments or configuration contents; logging is best-effort and never changes hook success. For remote troubleshooting, run `thpm report cava` (or another integration ID) to create a privacy-preserving JSON report under `~/.local/state/thpm/reports/`. Use `--output PATH` to choose its destination or `--json` to include the versioned report object in one CLI envelope. Reports normalize home paths wherever they occur, remove URL credentials, queries, and fragments, redact secret-like fields and authorization values, cap recent history and total size, and list omitted/redacted categories.

### Application setup

The Spotify integration expects Spicetify's one-time backup to be complete. THPM's Doctor reports a missing or stale backup instead of letting every theme hook fail. Initialize Spicetify, then enable the integration:

```bash
spicetify backup apply
thpm enable spotify
```

THPM keeps `~/.config/spicetify/Themes/omarchy/color.ini` synchronized, initializes a missing companion `user.css` from its bundled Omarchy stylesheet, and selects the lowercase `omarchy` theme with the `Base` color scheme. Existing stylesheets are never overwritten or removed. It always refreshes Spicetify's generated theme files after a palette change. Under the `automatic` restart policy, an already-running Spotify client is restarted so the colors take effect; under `notify`, Spotify remains open and is named in the pending-restart notification. A closed client stays closed under either policy. Hooks never perform Spicetify's privileged or destructive first-time backup.

Steam requires an initialized client and an Adwaita-for-Steam installer that supports `--color-theme`. When enabled, THPM prefers the active theme's `steam.css`; otherwise it generates Adwaita color variables from `colors.toml`. THPM installs those bytes as the managed `omarchy` color theme in the local Adwaita-for-Steam checkout, invokes the helper with `--color-theme omarchy --accent-color theme`, and verifies the selected import and patched bundles. Applying Adwaita-for-Steam replaces its installed skin and can replace prior helper options. Disabling Steam synchronization removes only THPM-owned generated state and an unmodified managed color-theme file; the external skin persists until you reapply preferred Adwaita-for-Steam options or explicitly uninstall that skin. Client chrome and Library are covered; Store web content remains native and is not themed by this integration.

### Zed authored themes

Omarchy's optional `omazed` package is the generated-color fallback for Zed. THPM does not modify Omazed's executable, hook, or `~/.config/zed/themes/omazed.json`. Instead, the opt-in `zed-extra` integration installs a richer authored asset when the active theme provides `zed.json` or, as a compatibility fallback, `aether.zed.json`. Canonical `zed.json` wins when both exist.

THPM validates the authored JSON and normalizes its single dark or light theme to the stable name **THPM Current** at `~/.config/zed/themes/thpm-current.json`. Run `thpm enable zed-extra` for ongoing synchronization on every theme change; it backs up `settings.json` and safely selects **THPM Current**. `thpm zed setup` only performs that installation and settings selection directly—it does not persistently enable the integration. Normal theme hooks update only the managed theme file and never rewrite Zed settings. Use `thpm zed status` to see the selected source, synchronization state, current Zed selection, and whether Omazed is available. If an authored asset disappears, THPM relinquishes its file and reports the Omazed fallback honestly; select **Omazed** in Zed if you want to switch to generated colors.

## Development

All changes use isolated Git worktrees, short-lived branches, and pull requests. Do not develop directly on `main`; start with [`CONTRIBUTING.md`](CONTRIBUTING.md) and the mandatory agent rules in [`AGENTS.md`](AGENTS.md). Enable the committed local guards once per clone, then create a task worktree:

```bash
scripts/setup-dev.sh
scripts/agent-worktree.sh create <task-slug>
```

From inside the task worktree, run the project checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
bash -n install.sh uninstall.sh assets/hooks/90-thpm assets/hooks/90-thpm-ui scripts/install-arch-release.sh
qmllint assets/qml/Panel.qml.in  # when Qt tooling is installed
```

Run `scripts/zellij-live-test.sh` to apply the checkout's Zellij adapter in an isolated XDG sandbox, open a real themed Zellij session, switch its colors while it is running, and verify restoration on exit. Use `--no-launch` to verify the watched-config refresh and cleanup without opening an interactive session, or `--keep` to retain the restored sandbox for inspection.

Run `scripts/local-arch-package.sh` to package the exact current working tree without creating a release or publishing to AUR. Pass `--install` to install that artifact through pacman so `/usr/bin/thpm`, packaged assets, hooks, and the graphical manager use the local build. The default local package release is `99`, making it visibly distinct from the published package; rebuild the published package with `yay -S thpm --rebuild` to roll back.

Start with the [visual architecture map](docs/architecture-map.md), then see [docs/architecture.md](docs/architecture.md), [docs/plugins.md](docs/plugins.md), and the [Quattro compatibility plan](docs/quattro-compatibility-plan.md) for the detailed contracts and native-ownership boundary.

Source updates follow stable GitHub releases and require matching `thpm-<version>.tar.gz` and `thpm-<version>.tar.gz.sha256` assets. Before merging release preparation, run `python scripts/verify-release.py metadata`; after the merged commit is tagged, `scripts/release-assets.sh` requires clean tag, version, release-note, Python, QML, template, and package metadata and then verifies every archive file against the tagged commit. Package-managed installations hand updates back to AUR rather than overwriting pacman-owned files.

The stable and VCS AUR submission trees are under `packaging/aur/thpm` and `packaging/aur/thpm-git`. After publishing the tagged archive, update the stable package's SHA-256 and the VCS package's tagged `pkgver`, regenerate both `.SRCINFO` files with `makepkg --printsrcinfo`, and run `python scripts/verify-release.py packaging <archive> <archive.sha256>`. This finalization is a follow-up packaging pull request because an archive cannot contain its own digest. Keep `SKIP` only for the VCS package.

## License

MIT. See [LICENSE](LICENSE).
