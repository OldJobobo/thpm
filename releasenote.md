## THPM 1.0.0rc20 is now available

**THPM is built for Omarchy Quattro and targets Omarchy 4.x. RC20 is the final graduation candidate for THPM 1.0.**

### Install or upgrade the latest release

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

The installer resolves the newest published GitHub release, verifies its source archive and checksum, builds the Arch package with `makepkg`, installs it through pacman, and completes THPM's per-user setup.

## What’s new in rc20

### Honest Experimental integration policy

Every active adapter that still lacks complete real-application certification is now visibly labeled **Experimental** and default-disabled for fresh state. Existing schema-1 enablement is grandfathered because older releases serialized inherited defaults and cannot distinguish them from explicit choices; grandfathering is not evidence of certification or opt-in. Cava remains separately protected by its durable consent marker.

The new integration support register records the reference Omarchy environment, evidence gaps, lifecycle disposition, repeatable certification procedure, and maintainer signoff required before an adapter can become Supported.

### Safer lifecycle and recovery

Persisted state now fails closed when its version is unsupported or Discord variants conflict. Readiness failures are isolated per integration, legacy Discord intent is normalized safely, and fresh SwayNC state is disabled without revoking existing enablement.

Disable and uninstall operations now distinguish committed state from incomplete cleanup. They report structured residuals, retain recovery paths and source ownership metadata, preserve the runtime needed for retries, and provide an exact recovery command instead of silently claiming success.

### Reproducible source and Arch packaging

Source installs and updates now use a complete dependency lock containing exact versions and SHA-256 hashes, require binary wheels, and validate the same graph on Python 3.11 through 3.14. Arch builds use `/usr/bin/python` to avoid mixing pacman modules with mise-managed environments.

CI now builds the exact pull-request checkout as stable and VCS packages in clean Arch environments—including before a release tag exists—validates generated `.SRCINFO`, smoke-tests installed packages, covers Python 3.14, and exposes one required aggregate result. New release gates verify version surfaces, tagged archive bytes and permissions, checksums, and both AUR package trees.

### Compatibility fixes

- Preserve Shibumi Shell's comment-terminated JSONC menu blocks while installing or removing THPM entries.
- Render Heroic's semantic CSS variables from the active Omarchy palette.

### Verification and soak

The rc20 preparation passes the complete automated suite: 339 tests. RC20 should soak for approximately 7–14 days before the accepted commit is promoted to stable `1.0.0`.

Please report lifecycle, upgrade, uninstall, recovery, packaging, or application-integration issues during the soak period.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc20)
