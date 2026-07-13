from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import __version__
from .files import atomic_copy
from .integrations import apply_enabled
from .migrate import archive as archive_legacy, inspect as inspect_legacy
from .omarchy import capabilities, run, shell_running
from .palette import load as load_palette
from .paths import Paths
from .registry import BY_ID
from .resources import asset
from .snapshot import build as build_snapshot
from .state import load, mutation_lock, save
from .templates import reconcile as reconcile_templates
from . import ui

SCHEMA_VERSION = 1


def envelope(operation: str, ok: bool = True, **fields: object) -> dict[str, object]:
    return {"schemaVersion": SCHEMA_VERSION, "ok": ok, "operation": operation, "busy": False, "summary": fields.pop("summary", ""), **fields}


class Service:
    def __init__(self, paths: Paths | None = None):
        self.paths = paths or Paths.discover()

    def views(self) -> list[dict[str, object]]:
        return [view.json() for view in build_snapshot(self.paths, load(self.paths))]

    def state(self) -> dict[str, object]:
        plugins = self.views()
        counts = {key: sum(1 for p in plugins if predicate(p)) for key, predicate in {
            "enabled": lambda p: p["enabled"] and p["ownership"] == "thpm",
            "disabled": lambda p: not p["enabled"] and p["ownership"] == "thpm",
            "native": lambda p: p["ownership"] == "native",
            "unavailable": lambda p: not p["available"],
            "attention": lambda p: bool(p["warnings"]),
        }.items()}
        return envelope("ui-state", summary="THPM plugin state", version=__version__, counts=counts, plugins=plugins, errors=[])

    def set_enabled(self, plugin_id: str, value: bool) -> dict[str, object]:
        if plugin_id not in BY_ID:
            return envelope("plugin-enable" if value else "plugin-disable", False, summary=f"unknown plugin: {plugin_id}", errors=[{"message": "unknown plugin"}])
        with mutation_lock(self.paths):
            enabled = load(self.paths)
            enabled[plugin_id] = value
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
        return envelope("plugin-enable" if value else "plugin-disable", summary=f"{plugin_id} {'enabled' if value else 'disabled'}", changed=changed, plugins=self.views(), errors=[])

    def doctor(self, plugin_id: str | None = None) -> dict[str, object]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        caps = capabilities()
        if not caps.available: errors.append({"message": "Omarchy 4 capabilities missing: " + ", ".join(caps.missing)})
        try: load_palette(self.paths.current_theme / "colors.toml")
        except (OSError, ValueError) as exc: errors.append({"message": str(exc)})
        plugins = self.views()
        if plugin_id: plugins = [p for p in plugins if p["id"] == plugin_id]
        if plugin_id and not plugins: errors.append({"message": f"unknown plugin: {plugin_id}"})
        for plugin in plugins:
            for warning in plugin["warnings"]: warnings.append({"plugin": str(plugin["id"]), "message": str(warning)})
        return envelope("doctor", not errors, summary=f"{len(errors)} errors, {len(warnings)} warnings", plugins=plugins, errors=errors, warnings=warnings, capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)})

    def reconcile(self, refresh: bool = False) -> dict[str, object]:
        with mutation_lock(self.paths):
            changed = reconcile_templates(self.paths, load(self.paths))
            atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
            changed.append(str(self.paths.hook_file))
        if refresh: run("theme", "refresh")
        return envelope("reconcile", summary=f"reconciled {len(changed)} files", changed=changed, plugins=self.views(), errors=[])

    def install(self, with_ui: bool = True) -> dict[str, object]:
        caps = capabilities()
        if not caps.available: return envelope("install", False, summary="Omarchy 4 is required", errors=[{"message": item} for item in caps.missing])
        migrated, legacy_files = inspect_legacy(self.paths)
        with mutation_lock(self.paths):
            enabled = load(self.paths)
            enabled.update(migrated)
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
            changed.append(str(self.paths.hook_file))
            legacy_archive = archive_legacy(self.paths, legacy_files)
        ui_result: dict[str, object] = {"installed": False, "skipped": True}
        if with_ui and shell_running(): ui_result = ui.install(self.paths)
        return envelope("install", summary="THPM installed", changed=changed, migratedTo=str(legacy_archive) if legacy_archive else None, ui=ui_result, errors=[])

    def uninstall(self) -> dict[str, object]:
        with mutation_lock(self.paths):
            disabled = {plugin_id: False for plugin_id in BY_ID}
            changed = reconcile_templates(self.paths, disabled)
            if self.paths.hook_file.exists():
                self.paths.hook_file.unlink()
                changed.append(str(self.paths.hook_file))
        ui_result = ui.remove(self.paths)
        return envelope("uninstall", summary="THPM integration files removed", changed=changed, ui=ui_result, errors=[])

    def hook_run(self, theme_name: str = "") -> dict[str, object]:
        result = apply_enabled(self.paths, load(self.paths))
        return envelope("hook-run", not result["errors"], summary=f"applied theme {theme_name}".strip(), **result)

    def run_theme(self) -> dict[str, object]:
        completed = run("theme", "refresh", check=False, timeout=180)
        return envelope("run", completed.returncode == 0, summary="theme refreshed" if completed.returncode == 0 else "theme refresh failed", stdout=completed.stdout, errors=[] if completed.returncode == 0 else [{"message": completed.stderr.strip()}])

    def migrate(self) -> dict[str, object]:
        enabled_updates, files = inspect_legacy(self.paths)
        with mutation_lock(self.paths):
            enabled = load(self.paths); enabled.update(enabled_updates); save(self.paths, enabled)
            destination = archive_legacy(self.paths, files)
            changed = reconcile_templates(self.paths, enabled)
        return envelope("migrate", summary=f"migrated {len(files)} legacy hooks", archive=str(destination) if destination else None, changed=changed, errors=[])
