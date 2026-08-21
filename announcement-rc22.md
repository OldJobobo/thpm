# THPM 1.0.0rc22

## Zen theming and safer desktop integration

- **Modern Zen colors:** the generated fallback now themes current Zen chrome, sidebar controls, navigation surfaces, the URL bar, and app-content wrapper from the active Omarchy palette.
- **Clean browser migration:** complete legacy Firefox and Zen hook imports are removed without disturbing unrelated user CSS, and restart notices appear only after profile files change.
- **Self-healing graphical manager:** stale QML is synchronized automatically, Shell readiness is verified, and the TUI opens as a recovery surface when graphical launch fails.
- **Transactional menu updates:** all user-scoped menu writers share one lock and restore prior menu or UI state after validation, encoding, or persistence failures.
- **Safer source rollback:** relative, absolute, and dangling symlinks are restored exactly, with complete template ownership read from the staged runtime.
- **Predictable Zed setup:** direct setup preserves the existing `zed-extra` synchronization state instead of silently opting users in.
- **Complete CLI help:** every command, nested action, argument, and public flag is now documented in built-in help.

## Install or upgrade

```sh
curl -fsSL https://raw.githubusercontent.com/OldJobobo/thpm/main/scripts/install-arch-release.sh | bash
```

RC22 remains a release candidate. Please report Zen theming, graphical-manager recovery, menu synchronization, update rollback, Zed setup, or packaging issues.

https://github.com/OldJobobo/thpm/releases/tag/v1.0.0rc22
