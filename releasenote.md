## THPM 1.0.0rc7 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### A proper command-line experience

THPM commands now show useful work while it happens instead of disappearing into silence and returning with “done.”

- Animated spinner for active work.
- Stage-based progress bar driven by real service events—not a fake timer.
- Elapsed time and concise phase labels.
- Semantic color for active, successful, warning, and failed states.
- Structured completion cards and integration result tables.
- Update version, package origin, next-action, and migration details where relevant.
- `--verbose` / `-v` stage logs, changed paths, and captured command output.
- Automatic non-animated output when redirected or piped.
- Full `NO_COLOR` support.
- Stable, decoration-free `--json` output for scripts and UI clients.

The progress surface covers update, install, reconcile, run, enable, disable, migrate, and uninstall workflows. Source updates report download, checksum verification, runtime staging, activation, integration synchronization, and control-panel refresh phases. AUR updates report the handoff to Omarchy’s package presentation terminal, where package-manager logs remain interactive.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report command-output or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc7)
