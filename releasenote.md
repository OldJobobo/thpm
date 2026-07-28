## THPM 1.0.0rc14 is now available

**THPM is made for Omarchy Quattro and supports Omarchy 4.x.**

### Install or upgrade

```sh
omarchy pkg aur add thpm   # first installation
omarchy update aur pkgs    # update an installed AUR package
```

## What’s new since rc5

### Zed themes now work through THPM

Turn on **Zed authored theme** in THPM and it will install and select the matching Zed theme for you. Your existing Zed settings are backed up first.

If you use Omazed, THPM leaves it available for themes that do not include their own Zed colors.

### Commands no longer appear stuck

Enable and disable commands now show what they are doing instead of sitting at 0%. Prompts remain visible, failures no longer look like successful completions, and misspelled integration names suggest the closest valid name.

### Safer theme switching

THPM is now better at cleaning up after itself. If you disable an integration or switch to a theme that does not support it, THPM restores what was there before whenever possible.

Your own changes are preserved instead of being overwritten or removed.

### A cleaner graphical manager

The graphical manager now follows your Omarchy window style more closely, without the extra border and frame it had before.

### Better terminal feedback

THPM commands now show clearer progress, results, changed files, and useful errors. Use `--quiet` when you want shorter output.

### Smoother updates

Running `thpm update` now installs the available update directly. Package output and password prompts remain visible, theme colors are refreshed after the update, and THPM gives you a clear result when everything is finished. Long-running update steps now stop with an error instead of waiting forever.

### Clearer app support

THPM now does a better job of telling you when an app is missing or when the current theme does not include support for an integration.

### Testing still needed

If you use any of these apps, feedback would be especially helpful:

- Qt6ct
- Vicinae
- nwg-dock-hyprland
- Windsurf
- Qutebrowser
- Heroic Games Launcher
- Spicetify

### Special thanks

Special thanks to our beta testers: @HANCORE, @sodipops, @gnugent, and @signal//directive.

This remains a release candidate. Please report any issues you find.

[View the release](https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc14)
