## THPM 1.0.0rc10 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### Update-flow documentation

This release documents the AUR update behavior introduced in rc9: `thpm update` keeps the upgrade in the invoking terminal, suppresses routine package-manager confirmations, allows normal password authentication when required, and reconciles integrations after installation.

The plugin security design now also reflects the policy already enforced by the shared service: sensitive integrations require explicit confirmation, and unavailable integrations are rejected consistently across CLI, JSON, TUI, and QML callers.

This documentation-only release is intentionally suitable for validating the rc9-to-rc10 AUR update path.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report update-flow or integration issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc10)
