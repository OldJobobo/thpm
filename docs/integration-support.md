# Integration support

This document records which of THPM's built-in integrations are **Supported** and which are **Experimental**. The registry in `src/thpm/registry.py` remains the source of truth for the active list, and a test keeps the rows below synchronized with it.

Every integration is opt-in regardless of status, and every integration — Experimental included — must preserve user files and support safe disable and uninstall. The status says how much evidence there is that the real application picks up the result; it is not a safety boundary.

## What Supported means

An integration is **Supported** when both of these hold:

1. **Automated lifecycle tests** cover apply, no-op reapply, disable/uninstall restoration, and preservation of a user-modified managed file for that integration.
2. **One real-application check is recorded** in the register below: someone switched between two Omarchy themes, saw the real application follow both, and saw it return to its own look after disable. The record is one line — date, application version, Omarchy version, THPM version, and who checked. A user report or a contributor fix made against a real installation counts.

An integration stays **Experimental** while either is missing, and also when it:

- has not yet shipped in a THPM release; or
- changes something beyond THPM's own files that THPM cannot fully put back, such as a desktop-wide setting or another program's installation.

**Retired** integrations are absent from the active registry. Apply is disabled, while guarded cleanup remains.

Repeat the real-application check when an adapter's loading path changes or a user reports that an application stopped following the theme. A failed check moves the integration back to Experimental until it is fixed.

## Recording a real-application check

On an Omarchy desktop with the application installed, run:

```bash
scripts/integration-check.sh <integration-id> <theme-a> <theme-b>
```

The script enables the integration, switches to each theme, disables the integration, and asks you to confirm by eye at each step. It then restores your previous theme and enabled state and prints the line to paste into the **Last real-application check** column. Use two themes with visibly different palettes. For integrations that need an application restart or a manual selection, do that when THPM reports it, before answering.

Change the row's status to Supported and the integration's `support_status` in `src/thpm/registry.py` in the same pull request. Screenshots are welcome in the pull request but are not required.

The longer records for `fzf` and `zellij` under `docs/certifications/` predate this procedure and are kept as they are.

## Active integration register

| Integration ID | Status | Default | Last real-application check | What to look for |
|---|---|---:|---|---|
| `gtk-css-compat` | Experimental | disabled | — | Launch recorded GTK 3 and GTK 4 test applications and prove supplied `gtk.css` or the `colors.toml` fallback alters rendered surfaces. |
| `vscode-local-compat` | Experimental | disabled | — | For every claimed installed editor command (`code`, `code-insiders`, `codium`, or `cursor`), install the fixture's data-only extension, select its theme, and prove it renders. |
| `pi-hot-reload` | Supported | disabled | 2026-10-13 · pi 1.2.0 · Omarchy 4.0.0.r6942 · THPM 1.0.0rc24 · OldJobobo (daily use) | Keep a recorded `pi` session using `omarchy-system` open across both fixture changes and prove its watcher repaints without rewriting the native file. |
| `fish` | Experimental | disabled | — | Start a recorded `fish` login session after each change and inspect Fish's effective color variables. |
| `fzf` | Supported | disabled | 2026-08-28 · fzf 0.74.3 · Omarchy 4.0.1 · OldJobobo · [record](certifications/fzf-2026-08-28.md) | Start a new Fish session after each theme change and open fzf; the whole fzf surface follows the palette. |
| `branding` | Experimental | disabled | — | Run `omarchy-launch-about` and `omarchy-launch-screensaver`; prove each authored asset is displayed and independently restored. |
| `nautilus-palette` | Experimental | disabled | — | With recorded Nautilus and nautilus-python versions, prove the user extension loads, both fixture palettes repaint an open Nautilus window through CSS hot reload, extension changes report restart, and displaced files are restored or preserved. |
| `gnome-accent-compat` | Experimental | disabled | — | In a disposable desktop session, record the prior GNOME accent, prove both fixtures map and hot-reload in libadwaita, then verify disable/uninstall restoration and concurrent user-change preservation. |
| `discord` | Supported | disabled | 2026-10-13 · vesktop 1.6.7 · Omarchy 4.0.0.r6942 · THPM 1.0.0rc24 · OldJobobo (daily use) | Launch the chosen recorded Vencord client, enable `vencord.theme.css`, and prove both authored and generated Midnight paths render. |
| `discord-system24` | Experimental | disabled | — | Launch the chosen recorded Vencord client, enable `vencord.theme.css`, and prove both authored and generated System24 paths render. |
| `qt6ct` | Experimental | disabled | — | Launch recorded `qt6ct`, select the generated scheme in a disposable profile, then prove a Qt 6 test application renders it. |
| `spotify` | Experimental | disabled | — | With recorded `spotify` and `spicetify` versions and a completed backup, prove refresh plus both restart policies changes colors without launching a closed client. |
| `superfile` | Experimental | disabled | — | Launch recorded `spf` with a disposable config and prove its theme discovery loads both authored and generated outputs. |
| `typora` | Experimental | disabled | — | Launch recorded `typora` with a disposable profile, select the generated **THPM** theme, prove Dune/Last Call screen rendering plus neutral print media, and retain restart/restoration evidence. |
| `zellij` | Supported | disabled | 2026-08-28 · Zellij 0.45.0 · Omarchy 4.0.1 · OldJobobo · [record](certifications/zellij-2026-08-28.md) | Keep one Zellij session open across both theme changes; it repaints without a restart. |
| `obsidian-terminal` | Experimental | disabled | — | Launch recorded `obsidian` and Terminal community-plugin versions in a disposable vault; prove xterm.js colors change after the documented restart. |
| `nwg-dock` | Experimental | disabled | — | Record the complete `nwg-dock-hyprland` launch command, restart it with identical flags, and prove the dock loads the installed stylesheet. |
| `zed-extra` | Experimental | disabled | — | Launch recorded `zeditor` with a disposable profile, select **THPM Current**, prove authored rendering, and verify prior selection/file restoration. |
| `cava` | Experimental | disabled | — | Run `scripts/cava-live-test.sh` with recorded Cava 0.10.6+; additionally capture visual proof of the selected gradient, PID-specific reload, and restoration. |
| `thunderbird` | Experimental | disabled | — | Launch recorded `thunderbird` with a disposable profile and legacy stylesheets enabled; prove the generated `about:3pane`/`about:message` content-document import and outer chrome import render, restart expectation, and restoration. |
| `firefox` | Experimental | disabled | — | Launch recorded `firefox` with a disposable profile and userChrome enabled; prove import, rendered chrome, restart expectation, and restoration. |
| `zen` | Experimental | disabled | — | Launch recorded `zen-browser` with a disposable profile and userChrome enabled; prove import, rendered chrome, restart expectation, and restoration. |
| `qutebrowser` | Experimental | disabled | — | Launch recorded `qutebrowser` with a disposable basedir sourcing the generated config and prove the effective UI/web palette. |
| `steam` | Experimental | disabled | — | Semantic generation, isolated installer execution, exact installed palette/import-chain validation, no-op/force, failures, and guarded disable/uninstall restoration have automated coverage. With recorded Steam and steam-adwaita versions, switch dark/light fixtures, manually relaunch only when safe, and prove the real client renders both palettes; verify baseline restoration/user-edit preservation. CSS wiring alone is not visual certification. |
| `heroic` | Experimental | disabled | — | Launch recorded `heroic` with a disposable config and prove its custom-theme loader consumes the installed semantic CSS variables. |
| `cliamp` | Experimental | disabled | — | Prove a marked authored override is installed and selected in a disposable config, then prove marker removal/disable restores the prior file and selection. Also verify a colors-only theme leaves cliamp's built-in or terminal-ANSI theming untouched. |
| `hermes-desktop-local` | Experimental | disabled | — | On a supported Linux Hermes Desktop build/default local profile, select **Local Omarchy** explicitly, keep a remote backend connected, and prove two local semantic palettes repaint the desktop. Verify plugin registration and computed CSS consumption; verify no connection/backend skin/selection writes, no-op hooks, disable/uninstall restoration, and cold-launch behavior. Runtime plugin themes may need reselection after cold launch on builds resolving saved selections before plugin discovery. |

### Steam installer regression evidence

The optional real-installer test copies a reviewed steam-adwaita checkout into an isolated HOME and passes only temporary `--target` paths. It exercises two semantic palettes, validates both installed stylesheets and the import chain, checks ordinary no-op and explicit reapply, and restores source/library baselines. It neither launches Steam nor changes the supplied checkout. To repeat from a task worktree:

```bash
mkdir -p .test-tmp
TMPDIR="$PWD/.test-tmp" THPM_TEST_STEAM_ADWAITA=/path/to/reviewed/steam-adwaita \
  PYTHONPATH=src:tests python3 -m unittest test_steam -v
```

The installed companion checkout at commit `bb35622` passed this test on Omarchy development build `7cc6a55f`. This is installer/loader regression evidence, **not** a real-application check: Steam stays Experimental until a real client is seen rendering both palettes.

## Native ownership records

`native-hermes`, `native-pi`, `native-claude`, `native-t3code`, `native-foot`, `native-tmux`, `native-gnome`, `native-vscode`, `native-obsidian`, and `native-keyboard` describe Omarchy-owned behavior. They are read-only ownership records, not THPM support claims, and are not enabled, disabled, or certified as THPM integrations.

## Retired integrations

| Integration | Lifecycle | Retained behavior |
|---|---|---|
| SwayNC | Retired | Guarded restoration or removal of the former managed `colors.css` output. |
| Windsurf | Retired | Guarded cleanup of the historical local theme extension after the editor's replacement. |
| Vicinae | Retired | Guarded cleanup of both historical managed theme destinations. |
| Hermes | Native-owned / THPM writer retired | Remove the obsolete THPM template; guarded restoration or removal of the historical JSON descriptor only. Never modify Omarchy's YAML skin or Hermes skin selection. |

Retired cleanup remains covered by automated tests and is retained indefinitely unless it becomes unsafe.
