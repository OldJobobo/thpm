from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import __version__, ui
from .compat import cleanup_gtk, vscode_doctor_warnings
from .files import atomic_copy, atomic_text
from .integrations import (
    MANAGED_OUTPUT_PLUGINS,
    OPTIONAL_ASSET_PLUGINS,
    apply_enabled,
    cleanup_managed_outputs,
    cleanup_optional_assets,
    cleanup_zed_assets,
    cleanup_zellij,
    reload_restored_integration,
)
from .integrations import apply as apply_integration
from .migrate import archive as archive_legacy
from .migrate import artifacts as legacy_artifacts
from .migrate import inspect as inspect_legacy
from .migrate import needs_compat
from .omarchy import capabilities, run
from .palette import load as load_palette
from .paths import Paths
from .registry import BY_ID
from .resources import asset
from .snapshot import build as build_snapshot
from .state import StateError, load, migration_lock, mutation_lock, save
from .templates import reconcile as reconcile_templates
from .update import apply as apply_update
from .update import check as check_update
from .zed import ZedThemeError
from .zed import configure_settings as configure_zed_settings
from .zed import status as zed_status
from .zed import validate_settings_edit as validate_zed_settings_edit

SCHEMA_VERSION = 1
CANONICAL_PALETTE_MIGRATION = "canonical-palette-v1"


def _snapshot_file(path: Path) -> tuple[str, bytes | str, int]:
    if path.is_symlink():
        return ("symlink", str(path.readlink()), 0)
    if path.is_file():
        return ("file", path.read_bytes(), path.stat().st_mode & 0o777)
    if path.exists():
        raise RuntimeError(f"rollback path is not a file: {path}")
    return ("missing", b"", 0)


def _restore_file(path: Path, snapshot: tuple[str, bytes | str, int]) -> None:
    kind, content, mode = snapshot
    if path.exists() or path.is_symlink():
        if not path.is_file() and not path.is_symlink():
            raise RuntimeError(f"rollback path is not a file: {path}")
        path.unlink()
    if kind == "missing":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        path.symlink_to(str(content))
        return
    path.write_bytes(bytes(content))
    path.chmod(mode)


def _source_activation_in_progress() -> bool:
    """Recognize both new and rc4 updaters while the previous runtime is rollbackable."""
    runtime = Path(sys.executable).absolute().parent.parent
    return runtime.name == "runtime" and runtime.with_name("runtime.previous").is_dir()


def _migration_status(paths: Paths, *, deferred: bool = False) -> dict[str, object]:
    pending = not paths.canonical_palette_migration_marker.is_file()
    return {
        "id": CANONICAL_PALETTE_MIGRATION,
        "pending": pending,
        "refreshed": False,
        "deferred": deferred and pending,
        "command": "thpm reconcile --refresh" if pending else None,
    }


def _refresh_templates(
    paths: Paths, *, requested: bool = False, deferred: bool = False
) -> tuple[dict[str, object], list[dict[str, str]]]:
    marker = paths.canonical_palette_migration_marker
    status = _migration_status(paths, deferred=deferred)
    pending = bool(status["pending"])
    if deferred or not (requested or pending):
        return status, []
    try:
        completed = run("theme", "refresh", check=False, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return status, [{"message": f"theme refresh failed: {exc}"}]
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "theme refresh failed"
        return status, [{"message": detail}]
    if pending:
        atomic_text(marker, CANONICAL_PALETTE_MIGRATION + "\n")
    status.update(pending=False, refreshed=True, deferred=False, command=None)
    return status, []


def envelope(operation: str, ok: bool = True, **fields: object) -> dict[str, object]:
    return {"schemaVersion": SCHEMA_VERSION, "ok": ok, "operation": operation, "busy": False, "summary": fields.pop("summary", ""), **fields}


class Service:
    def __init__(
        self,
        paths: Paths | None = None,
        progress: Callable[[str, str | None], None] | None = None,
    ):
        self.paths = paths or Paths.discover()
        self.progress = progress

    def _step(self, message: str, detail: str | None = None) -> None:
        if self.progress is not None:
            self.progress(message, detail)

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
        migration = _migration_status(self.paths)
        return envelope(
            "ui-state",
            summary="THPM plugin state",
            version=__version__,
            counts=counts,
            plugins=plugins,
            menuSurface=menu_surface,
            migration=migration,
            warnings=([{"message": "template refresh migration pending; run thpm reconcile --refresh"}] if migration["pending"] else []),
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

    def zed_status(self) -> dict[str, object]:
        result = zed_status(self.paths)
        return envelope(
            "zed-status",
            summary="Zed authored theme status",
            result=result,
            warnings=[{"plugin": "zed-extra", "message": message} for message in result["warnings"]],
            errors=[],
        )

    def zed_setup(self, *, confirmed: bool = False) -> dict[str, object]:
        view = next(item for item in self.views() if item["id"] == "zed-extra")
        if not view["available"] or not view["themeAssets"]:
            return envelope(
                "zed-setup",
                False,
                summary="no valid authored Zed theme is available",
                result=zed_status(self.paths),
                errors=[{"message": "the active theme must provide a valid zed.json or aether.zed.json"}],
            )
        if not confirmed:
            return envelope(
                "zed-setup",
                False,
                summary="confirmation required to configure Zed",
                confirmationRequired=True,
                plugin=view,
                errors=[],
            )
        self._step("Checking Zed theme")
        settings = self.paths.config_home / "zed/settings.json"
        rollback_paths = [
            settings,
            self.paths.zed_settings_backup_file,
            self.paths.config_home / "zed/themes/thpm-current.json",
            self.paths.config_home / "zed/themes/omarchy.json",
        ]
        rollback_paths.extend(
            self.paths.managed_asset_state_dir / f"{key}.{suffix}"
            for key in ("zed-extra", "zed-thpm-current")
            for suffix in ("json", "backup", "legacy-checked")
        )
        try:
            validate_zed_settings_edit(self.paths)
            snapshots = {path: _snapshot_file(path) for path in rollback_paths}
        except (OSError, RuntimeError, UnicodeError, ZedThemeError, ValueError) as exc:
            return envelope(
                "zed-setup",
                False,
                summary=f"unable to configure Zed: {exc}",
                result=zed_status(self.paths),
                errors=[{"message": str(exc)}],
            )

        was_enabled = bool(load(self.paths).get("zed-extra"))
        self._step("Backing up Zed settings")
        try:
            with mutation_lock(self.paths):
                settings_changed = configure_zed_settings(self.paths)
                self._step("Installing and selecting Zed theme")
                enabled = load(self.paths)
                enabled["zed-extra"] = True
                save(self.paths, enabled)
                changed = reconcile_templates(self.paths, enabled)
                result = apply_integration("zed-extra", self.paths)
                changed.extend(result.changed)
        except (OSError, RuntimeError, UnicodeError, ZedThemeError, ValueError) as exc:
            try:
                with mutation_lock(self.paths):
                    for path, snapshot in snapshots.items():
                        _restore_file(path, snapshot)
                    enabled = load(self.paths)
                    enabled["zed-extra"] = was_enabled
                    save(self.paths, enabled)
                    reconcile_templates(self.paths, enabled)
            except (OSError, RuntimeError, UnicodeError, ValueError) as rollback_exc:
                return envelope(
                    "zed-setup",
                    False,
                    summary=f"unable to configure Zed: {exc}; rollback failed: {rollback_exc}",
                    result=zed_status(self.paths),
                    errors=[{"message": str(exc)}, {"message": f"rollback failed: {rollback_exc}"}],
                )
            return envelope(
                "zed-setup",
                False,
                summary=f"unable to configure Zed: {exc}",
                result=zed_status(self.paths),
                errors=[{"message": str(exc)}],
            )
        if settings_changed:
            changed.append(str(settings))
        status = zed_status(self.paths)
        return envelope(
            "zed-setup",
            summary="Zed now uses THPM Current",
            changed=changed,
            result=status,
            warnings=[{"plugin": "zed-extra", "message": message} for message in result.warnings + status["warnings"]],
            errors=[],
        )

    def set_enabled(self, plugin_id: str, value: bool, *, confirmed: bool = False, refresh: bool = True) -> dict[str, object]:
        operation = "plugin-enable" if value else "plugin-disable"
        plugin = BY_ID.get(plugin_id)
        if plugin is None:
            matches = difflib.get_close_matches(plugin_id, BY_ID, n=1, cutoff=0.6)
            suggestion = f"; did you mean {matches[0]}?" if matches else ""
            return envelope(
                operation,
                False,
                summary=f"unknown plugin: {plugin_id}{suggestion}",
                errors=[{"message": f"unknown plugin{suggestion}"}],
            )
        view = next(item for item in self.views() if item["id"] == plugin_id)
        if value and not view["available"]:
            return envelope(operation, False, summary=f"{plugin_id} is unavailable", errors=[{"message": "required application or theme asset is unavailable"}])
        if value and plugin.confirmation and not confirmed:
            return envelope(operation, False, summary=f"confirmation required to enable {plugin_id}",
                confirmationRequired=True, plugin=view, errors=[])
        if value and plugin_id == "zed-extra":
            result = self.zed_setup(confirmed=True)
            result.update(
                operation=operation,
                summary=(
                    "zed-extra enabled"
                    if result["ok"]
                    else str(result.get("summary", "unable to enable zed-extra"))
                ),
                committed=bool(result["ok"]),
                stateChanged=not bool(view["enabled"]) and bool(result["ok"]),
                plugins=self.views(),
            )
            return result
        self._step("Checking integration")
        warnings: list[dict[str, str]] = []
        self._step("Updating integration state")
        with mutation_lock(self.paths):
            enabled = load(self.paths)
            was_enabled = bool(enabled.get(plugin_id))
            enabled[plugin_id] = value
            conflict = {"discord": "discord-system24", "discord-system24": "discord"}.get(plugin_id)
            shared_output_in_use = bool(
                not value and not was_enabled and conflict and enabled.get(conflict)
            )
            if value and conflict:
                enabled[conflict] = False
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            if not value and plugin_id == "gtk-css-compat":
                changed.extend(cleanup_gtk(self.paths))
            elif not value and plugin_id == "zellij":
                cleanup_changed, cleanup_warnings = cleanup_zellij(self.paths)
                changed.extend(cleanup_changed)
                warnings.extend(
                    {"plugin": "zellij", "message": message}
                    for message in cleanup_warnings
                )
            elif not value and plugin_id == "zed-extra":
                cleanup_changed, cleanup_warnings = cleanup_zed_assets(
                    self.paths, assume_legacy=True
                )
                changed.extend(cleanup_changed)
                warnings.extend(
                    {"plugin": plugin_id, "message": message}
                    for message in cleanup_warnings
                )
            elif not value and plugin_id in OPTIONAL_ASSET_PLUGINS:
                cleanup_changed, cleanup_warnings = cleanup_optional_assets(
                    self.paths, plugin_id, assume_legacy=True
                )
                changed.extend(cleanup_changed)
                _actions, reload_warnings = reload_restored_integration(
                    plugin_id, cleanup_changed
                )
                warnings.extend(
                    {"plugin": plugin_id, "message": message}
                    for message in cleanup_warnings + reload_warnings
                )
            elif (
                not value
                and plugin_id in MANAGED_OUTPUT_PLUGINS
                and not shared_output_in_use
            ):
                cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
                    self.paths, plugin_id, assume_legacy=True
                )
                changed.extend(cleanup_changed)
                warnings.extend(
                    {"plugin": plugin_id, "message": message}
                    for message in cleanup_warnings
                )
        errors: list[dict[str, str]] = []
        refreshed = False
        if value and refresh:
            self._step("Refreshing active theme")
            try:
                completed = run("theme", "refresh", check=False, timeout=180)
                refreshed = completed.returncode == 0
                if not refreshed:
                    errors.append({"message": completed.stderr.strip() or "theme refresh failed"})
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append({"message": f"theme refresh failed: {exc}"})
        else:
            self._step("Verifying integration state")
        summary = f"{plugin_id} {'enabled' if value else 'disabled'}"
        if errors:
            summary += "; setting was saved, but theme refresh failed"
        return envelope(
            operation,
            not errors,
            summary=summary,
            committed=True,
            stateChanged=was_enabled != value,
            changed=changed,
            refreshed=refreshed,
            plugins=self.views(),
            errors=errors,
            warnings=warnings,
        )

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
        migration = _migration_status(self.paths)
        if migration["pending"]:
            warnings.append({"message": "template refresh migration pending; run thpm reconcile --refresh"})
        return envelope("doctor", not errors, summary=f"{len(errors)} errors, {len(warnings)} warnings", plugins=plugins, errors=errors, warnings=warnings, migration=migration, capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)})

    def reconcile(
        self, refresh: bool = False, *, defer_upgrade_refresh: bool = False
    ) -> dict[str, object]:
        self._step("Reading integration state")
        deferred = defer_upgrade_refresh or _source_activation_in_progress()
        with migration_lock(self.paths):
            with mutation_lock(self.paths):
                self._step("Rendering managed templates")
                changed = reconcile_templates(self.paths, load(self.paths))
                self._step("Installing theme hook")
                atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
                changed.append(str(self.paths.hook_file))
            self._step("Refreshing active theme" if refresh else "Checking refresh migration")
            migration, errors = _refresh_templates(
                self.paths, requested=refresh, deferred=deferred
            )
        summary = f"reconciled {len(changed)} files"
        if migration["refreshed"]:
            summary += "; theme refreshed"
        elif migration["pending"]:
            summary += "; theme refresh pending (run thpm reconcile --refresh)"
        return envelope(
            "reconcile",
            not errors,
            summary=summary,
            changed=changed,
            refreshed=migration["refreshed"],
            migration=migration,
            plugins=self.views(),
            errors=errors,
        )

    def install_check(self) -> dict[str, object]:
        caps = capabilities()
        missing_assets = [str(asset(kind)) for kind in ("templates", "hooks", "qml") if not asset(kind).is_dir()]
        errors = ([{"message": item} for item in caps.missing] +
            [{"message": f"packaged asset directory missing: {item}"} for item in missing_assets])
        return envelope("install-check", not errors, summary="installation prerequisites satisfied" if not errors else "installation prerequisites missing",
            capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)}, errors=errors)

    def install(self, with_ui: bool = True) -> dict[str, object]:
        self._step("Checking Omarchy capabilities")
        check = self.install_check()
        if not check["ok"]:
            return envelope("install", False, summary="Omarchy 4 is required", errors=check["errors"])
        self._step("Inspecting existing installation")
        migrated, legacy_files = inspect_legacy(self.paths)
        compat_required = needs_compat(self.paths, legacy_files)
        with migration_lock(self.paths):
            with mutation_lock(self.paths):
                self._step("Rendering managed integrations")
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
            if with_ui:
                self._step("Installing control panel")
                ui_result = ui.install(self.paths)
            self._step("Refreshing active theme")
            migration, errors = _refresh_templates(
                self.paths,
                requested=True,
                deferred=_source_activation_in_progress(),
            )
        summary = "THPM installed"
        if migration["refreshed"]:
            summary += "; templates rendered and active theme refreshed"
        elif migration["pending"]:
            summary += "; theme refresh pending (run thpm reconcile --refresh)"
        return envelope(
            "install",
            not errors,
            summary=summary,
            changed=changed,
            migratedTo=str(legacy_archive) if legacy_archive else None,
            ui=ui_result,
            migration=migration,
            errors=errors,
        )

    def uninstall(self) -> dict[str, object]:
        warnings: list[dict[str, str]] = []
        with migration_lock(self.paths):
            with mutation_lock(self.paths):
                disabled = {plugin_id: False for plugin_id in BY_ID}
                changed = reconcile_templates(self.paths, disabled)
                changed.extend(cleanup_gtk(self.paths))
                for plugin_id in sorted(OPTIONAL_ASSET_PLUGINS):
                    if plugin_id == "zed-extra":
                        cleanup_changed, cleanup_warnings = cleanup_zed_assets(
                            self.paths, assume_legacy=True
                        )
                    else:
                        cleanup_changed, cleanup_warnings = cleanup_optional_assets(
                            self.paths,
                            plugin_id,
                            assume_legacy=True,
                        )
                    changed.extend(cleanup_changed)
                    _actions, reload_warnings = reload_restored_integration(
                        plugin_id, cleanup_changed
                    )
                    warnings.extend(
                        {"plugin": plugin_id, "message": message}
                        for message in cleanup_warnings + reload_warnings
                    )
                for plugin_id in sorted(MANAGED_OUTPUT_PLUGINS):
                    cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
                        self.paths,
                        plugin_id,
                        assume_legacy=True,
                    )
                    changed.extend(cleanup_changed)
                    warnings.extend(
                        {"plugin": plugin_id, "message": message}
                        for message in cleanup_warnings
                    )
                zellij_changed, zellij_warnings = cleanup_zellij(self.paths)
                changed.extend(zellij_changed)
                warnings.extend(
                    {"plugin": "zellij", "message": message}
                    for message in zellij_warnings
                )
                if self.paths.hook_file.exists():
                    self.paths.hook_file.unlink()
                    changed.append(str(self.paths.hook_file))
                if self.paths.canonical_palette_migration_marker.exists():
                    self.paths.canonical_palette_migration_marker.unlink()
                    changed.append(str(self.paths.canonical_palette_migration_marker))
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
        return envelope("uninstall", summary="THPM integration files removed", changed=changed, ui=ui_result, errors=[], warnings=warnings)

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
        self._step("Sending refresh to Omarchy")
        self.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="thpm-hook-",
            suffix=".json",
            dir=self.paths.runtime_dir,
            delete=False,
        ) as report_file:
            report_path = Path(report_file.name)
        environment = os.environ.copy()
        environment["THPM_HOOK_REPORT"] = str(report_path)
        try:
            completed = run(
                "theme",
                "refresh",
                check=False,
                timeout=180,
                env=environment,
            )
            try:
                hook_payload = json.loads(report_path.read_text())
            except (OSError, ValueError):
                hook_payload = None
        finally:
            report_path.unlink(missing_ok=True)

        self._step("Verifying refreshed integrations")
        if not isinstance(hook_payload, dict):
            detail = completed.stderr.strip() or completed.stdout.strip()
            errors = (
                [{"message": detail or "theme refresh failed"}]
                if completed.returncode != 0
                else []
            )
            warnings = (
                []
                if errors
                else [
                    {
                        "message": (
                            "THPM hook did not report integration results; "
                            "run thpm reconcile to reinstall it"
                        )
                    }
                ]
            )
            return envelope(
                "run",
                not errors,
                summary=(
                    "theme refreshed without an integration report"
                    if not errors
                    else "theme refresh failed"
                ),
                stdout=completed.stdout,
                errors=errors,
                warnings=warnings,
                results=[],
            )

        raw_counts = hook_payload.get("counts")
        counts: dict[str, int] = {}
        for status in ("applied", "unchanged", "skipped", "failed"):
            value = raw_counts.get(status, 0) if isinstance(raw_counts, dict) else 0
            counts[status] = (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                else 0
            )
        errors = list(hook_payload.get("errors") or [])
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            errors.insert(0, {"message": detail or "theme refresh failed"})
        ok = completed.returncode == 0 and bool(hook_payload.get("ok"))
        subject = (
            f"theme {hook_payload['themeName']}"
            if hook_payload.get("themeName")
            else "active theme"
        )
        summary = (
            f"refreshed {subject}: {counts['applied']} applied, "
            f"{counts['unchanged']} unchanged, {counts['skipped']} skipped, "
            f"{counts['failed']} failed"
        )
        return envelope(
            "run",
            ok,
            summary=summary,
            themeName=hook_payload.get("themeName"),
            counts=counts,
            results=hook_payload.get("results") or [],
            changed=hook_payload.get("changed") or [],
            actions=hook_payload.get("actions") or [],
            warnings=hook_payload.get("warnings") or [],
            errors=errors,
            stdout=completed.stdout,
        )

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
        self._step("Checking release channel")
        result = check_update(self.paths, force)
        ok = result.get("status") != "error"
        summary = {"available": "THPM update available", "current": "THPM is current", "unsupported": "installation origin is unsupported", "error": "update check failed"}.get(str(result.get("status")), "update status")
        errors = [{"message": str(result["error"])}] if result.get("error") else []
        return envelope("update-check", ok, summary=summary, result=result, errors=errors)

    def update_apply(self, *, interactive: bool = True) -> dict[str, object]:
        self._step("Checking for an available release")
        result = apply_update(
            self.paths, progress=self.progress, interactive=interactive
        )
        status = str(result.get("status"))
        refresh_error = str(result.get("refreshError") or "")
        ok = status in {"updated", "started", "current"} and not refresh_error
        summary = {
            "updated": "THPM updated",
            "started": "package update terminal opened; completion is pending",
            "current": "THPM is current",
            "requires-interactive": "AUR updates require an interactive terminal",
        }.get(status, "THPM update not applied")
        if refresh_error:
            summary += "; package updated, but active theme refresh failed"
        if result.get("refreshRequired"):
            summary += "; run thpm reconcile --refresh"
        error = refresh_error or str(result.get("error", status))
        return envelope(
            "update-apply",
            ok,
            summary=summary,
            committed=status == "updated",
            pending=status == "started",
            result=result,
            errors=[] if ok else [{"message": error}],
        )
