from __future__ import annotations

import shutil

from .models import PluginView
from .paths import Paths
from .registry import NATIVE, PLUGINS


def build(paths: Paths, enabled: dict[str, bool]) -> list[PluginView]:
    result: list[PluginView] = []
    for plugin in PLUGINS:
        missing = [command for command in plugin.commands if shutil.which(command) is None]
        assets = [name for name in plugin.theme_assets if (paths.current_theme / name).is_file()]
        available = not missing or bool(assets) or not plugin.commands
        result.append(PluginView(id=plugin.id, label=plugin.label, category=plugin.category,
            description=plugin.description, kind=plugin.kind,
            ownership="thpm" if available else "unavailable",
            enabled=enabled.get(plugin.id, plugin.default_enabled), available=available,
            commands=list(plugin.commands), missing=missing, themeAssets=assets,
            templates=list(plugin.templates),
            warnings=[] if available else ["required application commands are unavailable"],
            confirmationRequired=plugin.confirmation))
    result.extend(PluginView(id=p.id, label=p.label, category=p.category,
        description=p.description, kind=p.kind, ownership="native", enabled=True,
        available=True) for p in NATIVE)
    return result
