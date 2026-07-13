from __future__ import annotations

import shutil
from pathlib import Path

from .paths import Paths
from .registry import BY_ID

LEGACY_NAMES = {"fish", "fzf", "branding", "discord", "discord-system24", "gtk", "qt6ct", "spotify", "superfile", "tmux", "vicinae", "zellij", "typora", "nwg-dock-hyprland", "zed", "swaync", "foot-live-colors", "cursor", "vscode", "windsurf", "obsidian-terminal", "cava", "firefox", "hermes", "qutebrowser", "steam", "zen", "cliamp", "heroic"}
MAPPING = {"nwg-dock-hyprland": "nwg-dock", "zed": "zed-extra"}


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


def archive(paths: Paths, files: list[Path]) -> Path | None:
    if not files: return None
    destination = paths.thpm_state_dir / "legacy-hooks"
    destination.mkdir(parents=True, exist_ok=True)
    for path in files: shutil.move(str(path), destination / path.name)
    return destination
