from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .paths import Paths
from .registry import BY_ID

LEGACY_NAMES = {"fish", "fzf", "branding", "discord", "discord-system24", "gtk", "qt6ct", "spotify", "superfile", "tmux", "vicinae", "zellij", "typora", "nwg-dock-hyprland", "zed", "swaync", "foot-live-colors", "cursor", "vscode", "windsurf", "cava", "firefox", "hermes", "qutebrowser", "steam", "zen", "cliamp", "heroic"}
MAPPING = {
    "gtk": "gtk-css-compat",
    "vscode": "vscode-local-compat",
    "nwg-dock-hyprland": "nwg-dock",
    "zed": "zed-extra",
}
LEGACY_BINARIES = ("thpm", "thctl", "theme-hook-update")
LEGACY_CONTROL_FILES = (
    "lib/config.sh", "lib/plugin-registry.sh", "lib/theme-env.sh",
    "lib/install-core.sh", "lib/uninstall-core.sh", "version", "update-check",
)


def inspect(paths: Paths) -> tuple[dict[str, bool], list[Path]]:
    enabled: dict[str, bool] = {}
    files: list[Path] = []
    if not paths.hook_dir.is_dir(): return enabled, files
    for path in paths.hook_dir.iterdir():
        name = path.name.removesuffix(".sample").removesuffix(".sh")
        if "-" in name: name = name.split("-", 1)[1]
        if name not in LEGACY_NAMES: continue
        files.append(path)
        mapped = MAPPING.get(name, name)
        if mapped in BY_ID: enabled[mapped] = not path.name.endswith(".sample")
    return enabled, files


def needs_compat(paths: Paths, migrated_hooks: list[Path]) -> bool:
    migrated = set(migrated_hooks)
    if not paths.hook_dir.is_dir(): return False
    for path in paths.hook_dir.iterdir():
        if not path.is_file() or path in migrated: continue
        try: content = path.read_text(errors="ignore")
        except OSError: continue
        if ".local/share/thpm/lib/theme-env.sh" in content or "THPM_THEME_ENV" in content:
            return True
    return False


def artifacts(paths: Paths) -> list[Path]:
    result: list[Path] = []
    user_launcher = paths.home / ".local/bin/thpm"
    if user_launcher.is_file():
        try: content = user_launcher.read_text(errors="ignore")
        except OSError: content = ""
        signatures = ("THPM_CONTROL_LIB_DIR", "/lib/config.sh", "theme-hook-plugin-manager", "THPM_VERSION_FILE")
        if any(signature in content for signature in signatures):
            result.append(user_launcher)
    legacy_share = paths.data_home / "thpm"
    for relative in LEGACY_CONTROL_FILES:
        candidate = legacy_share / relative
        if not candidate.exists(): continue
        if relative == "lib/theme-env.sh":
            try: content = candidate.read_text(errors="ignore")
            except OSError: content = ""
            if "Transitional helpers for independently authored hooks" in content:
                continue
        result.append(candidate)
    skills = legacy_share / "skills"
    if skills.is_dir(): result.append(skills)
    config = paths.thpm_config_dir / "config.toml"
    if config.is_file(): result.append(config)
    dispatcher = paths.config_home / "omarchy/hooks/theme-set"
    if dispatcher.is_file():
        try: content = dispatcher.read_text(errors="ignore")
        except OSError: content = ""
        if "Compatibility shim for older thpm installs" in content or "Omarchy 3.3+ uses colors.toml" in content:
            result.append(dispatcher)
    old_omarchy_bin = paths.data_home / "omarchy/bin"
    result.extend(path for name in LEGACY_BINARIES if (path := old_omarchy_bin / name).is_file())
    return result


def archive(paths: Paths, files: list[Path], extra: list[Path] | None = None) -> Path | None:
    items = list(dict.fromkeys([*files, *(extra or [])]))
    if not items: return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = paths.thpm_state_dir / "legacy-backups" / stamp
    index = 1
    while destination.exists():
        destination = paths.thpm_state_dir / "legacy-backups" / f"{stamp}-{index}"
        index += 1
    for path in items:
        if not path.exists(): continue
        try: relative = path.relative_to(paths.home)
        except ValueError: relative = Path("external") / path.name
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), target)
    for directory in (paths.data_home / "thpm/lib", paths.data_home / "thpm", paths.thpm_config_dir):
        try: directory.rmdir()
        except OSError: pass
    return destination
