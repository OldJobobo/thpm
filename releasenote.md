## THPM 1.0.0rc12 is now available

**THPM is built exclusively for Omarchy Quattro and supports Omarchy 4.x only.**

### Install or upgrade through Omarchy

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

### Authored Zed themes, without fighting Omazed

THPM now recognizes both `zed.json` and compatibility `aether.zed.json` assets, validates them, and installs the preferred authored theme under the stable **THPM Current** identity. Run `thpm zed setup` once to back up Zed settings and select it safely; normal theme hooks update only the managed theme file.

`thpm zed status` reports source precedence, synchronization, the current Zed selection, and Omazed availability. Omazed remains independently owned and available as the generated-color fallback—THPM never modifies its output or hooks.

### Safer cleanup and native window presentation

Optional and generated integrations now restore displaced files when disabled or no longer supplied, while preserving user-modified targets and positively identifying legacy managed files before cleanup. The graphical manager also leaves its outer background, border, and rounding to Omarchy Shell and Hyprland instead of drawing duplicate window chrome.

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report Zed, restoration, or graphical-manager issues before the final 1.0.0 release.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc12)
