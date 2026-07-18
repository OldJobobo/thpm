from __future__ import annotations

import shutil  # Kept as the shared command probe patch point for callers and tests.

from .integrations import inspect_readiness
from .models import PluginView
from .paths import Paths
from .registry import NATIVE, PLUGINS


def build(paths: Paths, enabled: dict[str, bool]) -> list[PluginView]:
    result: list[PluginView] = []
    for plugin in PLUGINS:
        available, missing, readiness_warnings = inspect_readiness(
            plugin.id, paths, shutil.which
        )
        assets = [
            name
            for name in plugin.theme_assets
            if (paths.current_theme / name).is_file()
        ]
        is_enabled = enabled.get(plugin.id, plugin.default_enabled)
        warnings = list(readiness_warnings) if is_enabled else []
        if is_enabled and not available:
            warnings.append("enabled but not actionable: " + ", ".join(missing))
        result.append(
            PluginView(
                id=plugin.id,
                label=plugin.label,
                category=plugin.category,
                description=plugin.description,
                kind=plugin.kind,
                ownership="thpm" if available else "unavailable",
                enabled=enabled.get(plugin.id, plugin.default_enabled),
                available=available,
                commands=list(plugin.commands),
                missing=missing,
                themeAssets=assets,
                templates=list(plugin.templates),
                warnings=warnings,
                confirmationRequired=plugin.confirmation,
            )
        )
    result.extend(
        PluginView(
            id=p.id,
            label=p.label,
            category=p.category,
            description=p.description,
            kind=p.kind,
            ownership="native",
            enabled=True,
            available=True,
        )
        for p in NATIVE
    )
    return result
