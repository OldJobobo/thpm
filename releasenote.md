## THPM 1.0.0rc5 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install

```sh
omarchy pkg aur add thpm && thpm install
```

THPM 1.0.0rc5 fixes the rc4 palette/template schema regression and safely regenerates per-user theme outputs after upgrade.

### Upgrading from rc4

AUR updates launched through THPM reconcile per-user templates after the package succeeds. If THPM was updated through another package workflow, run:

```sh
thpm reconcile --refresh
```

Source updates detect rc4's rollbackable activation window and defer the live refresh until the new runtime is committed. A versioned migration marker is written only after a successful refresh, so interrupted or failed refreshes remain visible and retryable.

### Highlights

- Normalize Omarchy's canonical `background`, `foreground`, and related long palette names for Doctor and the TUI.
- Preserve short-only compatibility when the resolver emits empty canonical rows, while giving non-empty canonical values explicit precedence.
- Convert every affected bundled template—including stripped Spicetify values—to Omarchy's canonical resolver namespace.
- Reject unresolved `{{ ... }}` placeholders before generated fallbacks can be copied into application configuration.
- Surface unresolved output and pending refresh migrations through Doctor, CLI, TUI, and the QML panel.
- Serialize the one-time refresh migration and record completion only after a successful theme refresh.
- Keep rc4-to-rc5 source-update rollback narrow by deferring live integration effects until activation is committed.
- Expand regression coverage for canonical schemas, collisions, stock-theme rendering, generated-output safety, and source/AUR upgrade paths.

### Compatibility scope

Theme-provided assets retain precedence over THPM-generated fallbacks. THPM continues to delegate palette parsing, aliases, derivations, and template rendering to the installed Omarchy 4 resolver rather than maintaining a second theme engine.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report palette, upgrade, or integration-output issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc5)
