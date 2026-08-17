## THPM 1.0.0rc21 is now available

**THPM is built for Omarchy Quattro and targets Omarchy 4.x. RC21 is a focused reliability release for updates and desktop appearance diagnostics.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves the newest published GitHub release, verifies its source archive and checksum, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc21

### Updates now synchronize every THPM surface

`thpm update` now completes the package upgrade, integration reconciliation, active-theme refresh, and graphical control-panel installation as one coordinated transaction. Users no longer need to run `thpm ui install` after every THPM-managed update.

The same behavior is available from the CLI, Textual TUI, and QML control panel. Interactive CLI updates stay in the current terminal. TUI, QML, and non-TTY human callers open a visible Omarchy terminal for package authorization and receive the final structured result through a private mode-`0600` handoff file.

If the package update commits but theme or control-panel synchronization fails, THPM reports the committed partial failure honestly and provides the exact recovery command instead of presenting the operation as a total success or losing the result.

### Doctor finds stale GTK and desktop appearance state

Doctor now detects unmanaged and stale GTK CSS—including recognizable Aether overrides—legacy `gtk-application-prefer-dark-theme` settings, GNOME color-scheme or GTK-theme drift, desktop-portal color-scheme drift, and failed native probes.

The checks remain read-only and ownership-safe. GTK compatibility findings stay attributed to `gtk-css-compat`, while GNOME and portal findings remain under `native-gnome`; THPM does not claim or rewrite configuration it does not own.

### Safer verified release installation

The verified release-source installer can replace the unavoidable pre-tag stable-package checksum placeholder in its temporary build tree after validating the published archive digest. It rejects any non-placeholder checksum that disagrees with the verified release asset.

### Verification

The rc21 preparation passes the complete automated suite: 355 tests, Python 3.11 through 3.14, and clean stable and VCS Arch package builds.

This remains a release candidate. Please report update handoff, graphical-manager synchronization, GTK diagnostics, or packaging issues.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc21)
