# THPM 1.0.0rc20

## Final 1.0 graduation candidate

- **Honest support boundaries:** all active adapters without complete real-application certification are visibly Experimental and default-disabled for fresh state.
- **Safer lifecycle handling:** invalid state fails closed, readiness failures stay isolated, and Discord and SwayNC migrations preserve safe user intent.
- **Recoverable cleanup:** incomplete disable or uninstall operations retain recovery data and report exact retry commands.
- **Reproducible source installs:** the complete Python dependency graph is version- and hash-locked across Python 3.11–3.14.
- **Stronger packaging gates:** clean Arch builds, installed-package smoke tests, `.SRCINFO` checks, and exact tagged-archive verification now gate releases.
- **Compatibility fixes:** Shibumi JSONC menu blocks remain valid, and Heroic CSS follows the active Omarchy palette.

Existing schema-1 enablement is grandfathered because older releases cannot distinguish inherited defaults from explicit choices. Review integrations labeled Experimental and disable any you do not want.

## Install or upgrade

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

RC20 is intended to soak for approximately 7–14 days before promotion to stable `1.0.0`.

https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc20
