# Integration support and certification

This document records the 1.0 support boundary for THPM's built-in integrations. Presence in `src/thpm/registry.py` means an adapter is available; it does **not** mean the target application has been certified. The registry remains the source of truth for the active list, and a test keeps the rows below synchronized with it.

## Classification rules

THPM uses the lifecycle defined in the [PRD](PRD.md#fr-16-integration-support-lifecycle):

- **Supported** requires automated artifact and lifecycle coverage, a documented real-application procedure proving that the application loads the result, recorded application and Omarchy versions, and explicit maintainer signoff.
- **Experimental** is visible and opt-in while end-to-end validation is incomplete. It must still preserve user files and support safe disable and uninstall.
- **Retired** is absent from the active registry. Apply is disabled, while guarded cleanup remains.

**Incomplete** in the register is a certification audit result, not a lifecycle stage. Uncertified active adapters remain **Experimental**, visibly labeled, and default-disabled for new state until complete evidence and explicit maintainer signoff support promotion. `fzf` is the first adapter promoted to **Supported** after completing its technical, automated, lifecycle, restoration, visual, and signoff gates; it remains opt-in. Schema 1 serialized every inherited default, so an existing `true` cannot be distinguished from a later explicit re-enable. Those values are grandfathered to avoid silently disabling adapters while leaving application effects behind; they are **not** treated as proof of opt-in or certification. Existing users should review the Experimental labels and disable integrations they do not want. Cava remains the deliberate exception and still requires its separate consent marker. An adapter must be certified and reviewed before its lifecycle changes to Supported or its new-install default can become enabled.

Automated sandbox tests prove portions of parsing, rendering, shared generated-output machinery, ownership, restoration, and failure handling. Coverage depth varies by adapter and does not by itself prove a complete lifecycle. A copied file alone never proves that a real application imports, selects, or displays it.

## Reference environment

This audit was refreshed on **2026-08-16** against the following available platform baseline:

- Parent commit audited: `6092c47`
- Omarchy package: `omarchy-dev 4.0.0.r1758.g9f109a7-1`
- Python: 3.14.7 locally
- Rich package: 15.0.0
- Textual package: 8.2.8
- Parent CI run: [PR #20 run 31965007250](https://github.com/OldJobobo/thpm/actions/runs/31965007250), with successful Python 3.11–3.14 and clean stable/VCS Arch package jobs

This baseline records the host used to audit contracts and the successful parent CI run. It is **not** application certification. The complete `fzf` certification is recorded separately in `docs/certifications/fzf-2026-08-28.md`; every other active integration still lacks a complete repository record containing a real-application version, successful loader observation, and maintainer signoff.

## Repeatable certification procedure

Run certification from the candidate commit in a disposable user account, VM, or disposable application profile. Do not use irreplaceable browser, editor, game-client, or shell configuration. The application-specific command and observation come from the active register below; every integration also follows this common protocol.

### Fixtures and evidence

1. Record the candidate commit and these exact version outputs where available:

   ```bash
   git rev-parse HEAD
   omarchy-version
   python --version
   thpm --version
   <application-command> --version
   <companion-command> --version
   ```

   If an application has no version flag, record its package version (`pacman -Q <package>`) or About-dialog version. Record the exact launch command, including profile/config flags.
2. Use two disposable Omarchy themes. Fixture A must use visually distinct semantic colors and include every authored asset exercised by the adapter. Fixture B must use different semantic colors and omit optional assets when omission/restoration is part of the contract. Record both theme directories and SHA-256 digests of their inputs.
3. Before enabling THPM, create a recognizable baseline at every destination the adapter may displace. Record file type, mode, symlink target, and SHA-256 where applicable. For shared configuration, preserve a copy and add an unrelated sentinel outside THPM's managed block.
4. Store command output, `thpm report <id>`, before/after metadata, and screenshots when visible rendering is the only proof. Do not capture credentials or private configuration contents.

### Execution

Substitute the row's integration ID and fixture names:

```bash
id=<integration-id>
thpm disable "$id"
omarchy-theme-set <fixture-a-name>
thpm enable "$id"
thpm run --verbose
thpm report "$id" --output "${id}-fixture-a.json"
```

Then complete these gates in order:

1. **Initial effect:** launch or refresh the real application with the command named in the row. Prove the loader, selector, import, or external action uses Fixture A; file presence alone fails this gate.
2. **No-op:** invoke the ordinary, non-forced hook path with `thpm hook-run theme-set <fixture-a-name>` without changing the theme. The adapter must report unchanged, must not replace identical files, and must not reload or restart the application. Do not use `thpm run` for this gate: explicit reapplication intentionally forces reload-capable adapters even when content is unchanged.
3. **Theme transition:** select Fixture B with `omarchy-theme-set <fixture-b-name>` and capture the ordinary hook outcome produced by that command. Prove the real application changes to Fixture B using the documented reload/restart contract; do not follow it with a forced `thpm run`.
4. **Disable/restoration:** run `thpm disable "$id"`. Compare destinations with the recorded baseline and verify the application no longer uses THPM output. Unrelated shared-config sentinels must remain.
5. **User modification:** enable again on Fixture A, modify a managed destination in a safe recognizable way, then disable. THPM must preserve the unknown user-modified target and report the preservation or incomplete cleanup honestly. Restore the disposable baseline manually before continuing.
6. **Uninstall/restoration:** reinstall/enable the candidate in the disposable environment, apply Fixture A, run `thpm uninstall`, and repeat baseline and application checks. If cleanup is incomplete, the command must retain recovery data and provide a successful retry path.
7. **Signoff:** attach the completed record template, outputs, metadata, and visual evidence to a pull request. A maintainer reviews the evidence and changes the row to Supported only when every applicable gate passes.

For external actions that are not reversible, replace restoration with proof that THPM warned before execution, recorded the persistent effect, stopped future execution after disable, and described manual reversal. For adapters with both generated and authored paths, repeat the protocol once for each path.

## Active integration register

The **Real-application evidence** column is the adapter-specific addition to the common procedure. Application and Omarchy versions must be added in a signed certification record when the observation is completed.

| Integration ID | Certification audit | Lifecycle disposition | Default | Real-application evidence |
|---|---|---|---:|---|
| `gtk-css-compat` | Incomplete | Experimental | disabled | Launch recorded GTK 3 and GTK 4 test applications and prove supplied `gtk.css` or the `colors.toml` fallback alters rendered surfaces. |
| `vscode-local-compat` | Incomplete | Experimental | disabled | For every claimed installed editor command (`code`, `code-insiders`, `codium`, or `cursor`), install the fixture's data-only extension, select its theme, and prove it renders. |
| `pi-hot-reload` | Incomplete | Experimental | disabled | Keep a recorded `pi` session using `omarchy-system` open across both fixture changes and prove its watcher repaints without rewriting the native file. |
| `fish` | Incomplete | Experimental | disabled | Start a recorded `fish` login session after each change and inspect Fish's effective color variables. |
| `fzf` | Complete | Supported | disabled | Certified on Omarchy 4.0.1 with fzf 0.74.3 and Fish 4.8.1: real `omarchy-theme-set` transitions visibly recolored the complete fzf surface; automated/no-op/disable/user-edit/uninstall/restoration evidence and maintainer signoff are retained in `docs/certifications/fzf-2026-08-28.md`. |
| `branding` | Incomplete | Experimental | disabled | Run `omarchy-launch-about` and `omarchy-launch-screensaver`; prove each authored asset is displayed and independently restored. |
| `discord` | Incomplete | Experimental | disabled | Launch the chosen recorded Vencord client, enable `vencord.theme.css`, and prove both authored and generated Midnight paths render. |
| `discord-system24` | Incomplete | Experimental | disabled | Launch the chosen recorded Vencord client, enable `vencord.theme.css`, and prove both authored and generated System24 paths render. |
| `qt6ct` | Incomplete | Experimental | disabled | Launch recorded `qt6ct`, select the generated scheme in a disposable profile, then prove a Qt 6 test application renders it. |
| `spotify` | Incomplete | Experimental | disabled | With recorded `spotify` and `spicetify` versions and a completed backup, prove refresh plus both restart policies changes colors without launching a closed client. |
| `superfile` | Incomplete | Experimental | disabled | Launch recorded `spf` with a disposable config and prove its theme discovery loads both authored and generated outputs. |
| `typora` | Incomplete | Experimental | disabled | Launch recorded `typora` with a disposable profile, select the generated **THPM** theme, prove Dune/Last Call screen rendering plus neutral print media, and retain restart/restoration evidence. |
| `zellij` | Incomplete | Experimental | disabled | Run `scripts/zellij-live-test.sh` with a recorded `zellij` version, visually prove a running session repaints, and retain restoration evidence from the harness. |
| `obsidian-terminal` | Incomplete | Experimental | disabled | Launch recorded `obsidian` and Terminal community-plugin versions in a disposable vault; prove xterm.js colors change after the documented restart. |
| `nwg-dock` | Incomplete | Experimental | disabled | Record the complete `nwg-dock-hyprland` launch command, restart it with identical flags, and prove the dock loads the installed stylesheet. |
| `zed-extra` | Incomplete | Experimental | disabled | Launch recorded `zeditor` with a disposable profile, select **THPM Current**, prove authored rendering, and verify prior selection/file restoration. |
| `cava` | Incomplete | Experimental | disabled | Run `scripts/cava-live-test.sh` with recorded Cava 0.10.6+; additionally capture visual proof of the selected gradient, PID-specific reload, and restoration. |
| `firefox` | Incomplete | Experimental | disabled | Launch recorded `firefox` with a disposable profile and userChrome enabled; prove import, rendered chrome, restart expectation, and restoration. |
| `zen` | Incomplete | Experimental | disabled | Launch recorded `zen-browser` with a disposable profile and userChrome enabled; prove import, rendered chrome, restart expectation, and restoration. |
| `hermes` | Incomplete | Experimental | disabled | Launch recorded `Hermes` with a disposable config and prove it discovers and renders the generated Omarchy descriptor. |
| `qutebrowser` | Incomplete | Experimental | disabled | Launch recorded `qutebrowser` with a disposable basedir sourcing the generated config and prove the effective UI/web palette. |
| `steam` | Incomplete | Experimental | disabled | With recorded Steam and steam-adwaita versions, apply the fixture, prove the client renders it, and document the external action's persistence/manual reversal. |
| `heroic` | Incomplete | Experimental | disabled | Launch recorded `heroic` with a disposable config and prove its custom-theme loader consumes the installed semantic CSS variables. |
| `cliamp` | Incomplete | Experimental | disabled | Prove a marked authored override is installed and selected in a disposable config, then prove marker removal/disable restores the prior file and selection. Also verify a colors-only theme leaves cliamp's built-in or terminal-ANSI theming untouched. |

## Native ownership records

`native-foot`, `native-tmux`, `native-gnome`, `native-vscode`, `native-obsidian`, and `native-keyboard` describe Omarchy-owned behavior. They are read-only ownership records, not THPM support claims, and are not enabled, disabled, or certified as THPM integrations.

## Retired integrations

| Integration | Lifecycle | Retained behavior |
|---|---|---|
| SwayNC | Retired | Guarded restoration or removal of the former managed `colors.css` output. |
| Typora | Retired | Guarded restoration or removal of the former managed stylesheet. |
| Windsurf | Retired | Guarded cleanup of the historical local theme extension after the editor's replacement. |
| Vicinae | Retired | Guarded cleanup of both historical managed theme destinations. |

Retired cleanup remains covered by automated tests and is retained indefinitely unless it becomes unsafe.

## Certification record template

```text
Integration ID:
THPM version/commit:
Omarchy package version:
Application and companion-tool versions:
Exact launch command and disposable profile/config path:
Fixture A/B paths and input SHA-256 digests:
Initial loader/selector/render observation:
No-op result:
Theme-transition and reload/restart result:
Disable/restoration result:
User-modification preservation result:
Uninstall/restoration or persistent-effect result:
Evidence links:
Maintainer and signoff date:
```

A failed or partial run remains useful evidence but does not promote the integration.
