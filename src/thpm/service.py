from __future__ import annotations

import subprocess

from . import __version__
from .compat import cleanup_gtk, vscode_doctor_warnings
from .files import atomic_copy
from .integrations import apply_enabled
from .migrate import archive as archive_legacy, artifacts as legacy_artifacts, inspect as inspect_legacy, needs_compat
from .omarchy import capabilities, run
from .palette import load as load_palette
from .paths import Paths
from .registry import BY_ID
from .resources import asset
from .snapshot import build as build_snapshot
from .state import StateError, load, mutation_lock, save
from .templates import reconcile as reconcile_templates
from .update import apply as apply_update, check as check_update
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
        menu_surface = str(ui.surface(self.paths)["surface"])
        return envelope(
            "ui-state",
            summary="THPM plugin state",
            version=__version__,
            counts=counts,
            plugins=plugins,
            menuSurface=menu_surface,
            errors=[],
        )

    def ui_surface(self, requested: str | None = None) -> dict[str, object]:
        result = ui.surface(self.paths, requested)
        return envelope(
            "ui-surface",
            summary=f"Omarchy menu opens the {str(result['surface']).upper()}",
            result=result,
            errors=[],
        )

    def set_enabled(self, plugin_id: str, value: bool, *, confirmed: bool = False, refresh: bool = True) -> dict[str, object]:
        operation = "plugin-enable" if value else "plugin-disable"
        plugin = BY_ID.get(plugin_id)
        if plugin is None:
            return envelope(operation, False, summary=f"unknown plugin: {plugin_id}", errors=[{"message": "unknown plugin"}])
        view = next(item for item in self.views() if item["id"] == plugin_id)
        if value and not view["available"]:
            return envelope(operation, False, summary=f"{plugin_id} is unavailable", errors=[{"message": "required application or theme asset is unavailable"}])
        if value and plugin.confirmation and not confirmed:
            return envelope(operation, False, summary=f"confirmation required to enable {plugin_id}",
                confirmationRequired=True, plugin=view, errors=[])
        with mutation_lock(self.paths):
            enabled = load(self.paths)
            enabled[plugin_id] = value
            conflict = {"discord": "discord-system24", "discord-system24": "discord"}.get(plugin_id)
            if value and conflict:
                enabled[conflict] = False
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            if not value and plugin_id == "gtk-css-compat":
                changed.extend(cleanup_gtk(self.paths))
        errors: list[dict[str, str]] = []
        refreshed = False
        if value and refresh:
            try:
                completed = run("theme", "refresh", check=False, timeout=180)
                refreshed = completed.returncode == 0
                if not refreshed:
                    errors.append({"message": completed.stderr.strip() or "theme refresh failed"})
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append({"message": f"theme refresh failed: {exc}"})
        summary = f"{plugin_id} {'enabled' if value else 'disabled'}"
        if errors:
            summary += "; theme refresh failed"
        return envelope(operation, not errors, summary=summary, changed=changed, refreshed=refreshed,
            plugins=self.views(), errors=errors)

    def doctor(self, plugin_id: str | None = None) -> dict[str, object]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        caps = capabilities()
        if not caps.available: errors.append({"message": "Omarchy 4 capabilities missing: " + ", ".join(caps.missing)})
        try: load_palette(self.paths.current_theme / "colors.toml")
        except (OSError, ValueError) as exc: errors.append({"message": str(exc)})
        try:
            plugins = self.views()
        except StateError as exc:
            errors.append({"message": str(exc)})
            plugins = []
        if plugin_id: plugins = [p for p in plugins if p["id"] == plugin_id]
        if plugin_id and not plugins: errors.append({"message": f"unknown plugin: {plugin_id}"})
        for plugin in plugins:
            for warning in plugin["warnings"]: warnings.append({"plugin": str(plugin["id"]), "message": str(warning)})
        local_compat = next((plugin for plugin in plugins if plugin["id"] == "vscode-local-compat"), None)
        if local_compat and local_compat["enabled"] and local_compat.get("applicable", True):
            known = {(item.get("plugin"), item["message"]) for item in warnings}
            for message in vscode_doctor_warnings(self.paths):
                entry = ("vscode-local-compat", message)
                if entry not in known:
                    warnings.append({"plugin": entry[0], "message": entry[1]})
        return envelope("doctor", not errors, summary=f"{len(errors)} errors, {len(warnings)} warnings", plugins=plugins, errors=errors, warnings=warnings, capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)})

    def reconcile(self, refresh: bool = False) -> dict[str, object]:
        with mutation_lock(self.paths):
            changed = reconcile_templates(self.paths, load(self.paths))
            atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
            changed.append(str(self.paths.hook_file))
        if refresh: run("theme", "refresh")
        return envelope("reconcile", summary=f"reconciled {len(changed)} files", changed=changed, plugins=self.views(), errors=[])

    def install_check(self) -> dict[str, object]:
        caps = capabilities()
        missing_assets = [str(asset(kind)) for kind in ("templates", "hooks", "qml") if not asset(kind).is_dir()]
        errors = ([{"message": item} for item in caps.missing] +
            [{"message": f"packaged asset directory missing: {item}"} for item in missing_assets])
        return envelope("install-check", not errors, summary="installation prerequisites satisfied" if not errors else "installation prerequisites missing",
            capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)}, errors=errors)

    def install(self, with_ui: bool = True) -> dict[str, object]:
        check = self.install_check()
        if not check["ok"]:
            return envelope("install", False, summary="Omarchy 4 is required", errors=check["errors"])
        migrated, legacy_files = inspect_legacy(self.paths)
        compat_required = needs_compat(self.paths, legacy_files)
        with mutation_lock(self.paths):
            enabled = load(self.paths)
            enabled.update(migrated)
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
            changed.append(str(self.paths.hook_file))
            legacy_archive = archive_legacy(self.paths, legacy_files, legacy_artifacts(self.paths))
            if compat_required:
                atomic_copy(asset("compat", "theme-env.sh"), self.paths.legacy_compat_file, 0o644)
                changed.append(str(self.paths.legacy_compat_file))
        ui_result: dict[str, object] = {"installed": False, "skipped": True}
        if with_ui: ui_result = ui.install(self.paths)
        return envelope("install", summary="THPM installed", changed=changed, migratedTo=str(legacy_archive) if legacy_archive else None, ui=ui_result, errors=[])

    def uninstall(self) -> dict[str, object]:
        with mutation_lock(self.paths):
            disabled = {plugin_id: False for plugin_id in BY_ID}
            changed = reconcile_templates(self.paths, disabled)
            changed.extend(cleanup_gtk(self.paths))
            if self.paths.hook_file.exists():
                self.paths.hook_file.unlink()
                changed.append(str(self.paths.hook_file))
            compat_asset = asset("compat", "theme-env.sh")
            if self.paths.legacy_compat_file.is_file() and compat_asset.is_file() and self.paths.legacy_compat_file.read_bytes() == compat_asset.read_bytes():
                self.paths.legacy_compat_file.unlink()
                changed.append(str(self.paths.legacy_compat_file))
        ui_result = ui.remove(self.paths)
        self.paths.update_cache_file.unlink(missing_ok=True)
        if self.paths.install_metadata.is_file():
            try:
                if 'origin = "source"' in self.paths.install_metadata.read_text():
                    self.paths.install_metadata.unlink()
            except OSError:
                pass
        return envelope("uninstall", summary="THPM integration files removed", changed=changed, ui=ui_result, errors=[])

    def hook_run(self, event: str, event_args: list[str] | tuple[str, ...] = ()) -> dict[str, object]:
        if event != "theme-set":
            return envelope("hook-run", False, summary=f"unsupported hook event: {event}",
                event=event, eventArgs=list(event_args), errors=[{"message": "unsupported hook event"}])
        with mutation_lock(self.paths):
            result = apply_enabled(self.paths, load(self.paths))
        theme_name = event_args[0] if event_args else ""
        subject = f"theme {theme_name}" if theme_name else "active theme"
        counts = result.get("counts") or {"applied": 0, "unchanged": 0, "skipped": 0, "failed": len(result["errors"])}
        summary = (f"processed {subject}: {counts['applied']} applied, {counts['unchanged']} unchanged, "
            f"{counts['skipped']} skipped, {counts['failed']} failed")
        return envelope("hook-run", not result["errors"], summary=summary,
            event=event, eventArgs=list(event_args), themeName=theme_name or None, **result)

    def run_theme(self) -> dict[str, object]:
        completed = run("theme", "refresh", check=False, timeout=180)
        return envelope("run", completed.returncode == 0, summary="theme refreshed" if completed.returncode == 0 else "theme refresh failed", stdout=completed.stdout, errors=[] if completed.returncode == 0 else [{"message": completed.stderr.strip()}])

    def migrate(self) -> dict[str, object]:
        enabled_updates, files = inspect_legacy(self.paths)
        compat_required = needs_compat(self.paths, files)
        with mutation_lock(self.paths):
            enabled = load(self.paths); enabled.update(enabled_updates); save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            destination = archive_legacy(self.paths, files, legacy_artifacts(self.paths))
            if compat_required:
                atomic_copy(asset("compat", "theme-env.sh"), self.paths.legacy_compat_file, 0o644)
                changed.append(str(self.paths.legacy_compat_file))
        return envelope("migrate", summary=f"migrated {len(files)} legacy hooks", archive=str(destination) if destination else None, changed=changed, errors=[])

    def update_check(self, force: bool = False) -> dict[str, object]:
        result = check_update(self.paths, force)
        ok = result.get("status") != "error"
        summary = {"available": "THPM update available", "current": "THPM is current", "unsupported": "installation origin is unsupported", "error": "update check failed"}.get(str(result.get("status")), "update status")
        errors = [{"message": str(result["error"])}] if result.get("error") else []
        return envelope("update-check", ok, summary=summary, result=result, errors=errors)

    def update_apply(self) -> dict[str, object]:
        result = apply_update(self.paths)
        ok = result.get("status") in {"updated", "started", "current"}
        summary = {"updated": "THPM updated", "started": "package update started", "current": "THPM is current"}.get(str(result.get("status")), "THPM update not applied")
        return envelope("update-apply", ok, summary=summary, result=result, errors=[] if ok else [{"message": str(result.get("error", result.get("status")))}])
