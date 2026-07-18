from __future__ import annotations

import shutil  # Kept as the shared command probe patch point for callers and tests.

from .compat import (
    gtk_requested,
    gtk_synchronized,
    vscode_local_requested,
    vscode_marker_current,
)
from .integrations import inspect_applicability, inspect_readiness
from .models import PluginView
from .paths import Paths
from .registry import NATIVE, PLUGINS


def _compat_synchronized(plugin_id: str, paths: Paths) -> bool:
    if plugin_id == "gtk-css-compat":
        return gtk_synchronized(paths)
    if plugin_id == "vscode-local-compat":
        return vscode_marker_current(paths)
    return True


def _native_warnings(
    plugin_id: str, paths: Paths, enabled: dict[str, bool]
) -> list[str]:
    if (
        plugin_id == "native-gnome"
        and gtk_requested(paths)
        and not enabled.get("gtk-css-compat", True)
    ):
        return [
            "active theme GTK CSS requires the disabled THPM compatibility integration"
        ]
    if (
        plugin_id == "native-vscode"
        and vscode_local_requested(paths)
        and not enabled.get("vscode-local-compat", True)
    ):
        return [
            "bundled local editor theme requires the disabled THPM compatibility integration"
        ]
    return []


def build(paths: Paths, enabled: dict[str, bool]) -> list[PluginView]:
    result: list[PluginView] = []
    for plugin in PLUGINS:
        applicable = inspect_applicability(plugin.id, paths)
        available, missing, readiness_warnings = inspect_readiness(
            plugin.id, paths, shutil.which
        )
        assets = [
            name
            for name in plugin.theme_assets
            if (paths.current_theme / name).is_file()
        ]
        is_enabled = enabled.get(plugin.id, plugin.default_enabled)
        warnings = list(readiness_warnings) if is_enabled and applicable else []
        if is_enabled and applicable and not available:
            warnings.append("enabled but not actionable: " + ", ".join(missing))
        elif is_enabled and applicable and not _compat_synchronized(plugin.id, paths):
            warnings.append("requested compatibility output is not synchronized")
        result.append(
            PluginView(
                id=plugin.id,
                label=plugin.label,
                category=plugin.category,
                description=plugin.description,
                kind=plugin.kind,
                ownership="thpm" if available else "unavailable",
                enabled=is_enabled,
                available=available,
                applicable=applicable,
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
            id=plugin.id,
            label=plugin.label,
            category=plugin.category,
            description=plugin.description,
            kind=plugin.kind,
            ownership="native",
            enabled=True,
            available=True,
            warnings=_native_warnings(plugin.id, paths, enabled),
        )
        for plugin in NATIVE
    )
    return result
