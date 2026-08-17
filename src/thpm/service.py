from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, ui
from .audit import record_payload
from .cava import (
    CavaError,
    running_cava_requires_restart,
)
from .cava import (
    configure_selector as configure_cava_selector,
)
from .cava import (
    default_config_path as cava_config_path,
)
from .cava import (
    diagnose as diagnose_cava,
)
from .cava import (
    reload_matching_processes as reload_cava_processes,
)
from .cava import (
    restore_selector as restore_cava_selector,
)
from .cava import (
    safe_config_target as safe_cava_config_target,
)
from .cava import (
    selector_state_path as cava_selector_state_path,
)
from .cava import (
    theme_source as cava_theme_source,
)
from .compat import (
    cleanup_gtk,
    gtk_file_doctor_warnings,
    gtk_session_doctor_warnings,
    vscode_doctor_warnings,
)
from .config import ConfigError, Preferences
from .config import load as load_config
from .config import save as save_config
from .files import atomic_copy, atomic_text
from .integrations import (
    MANAGED_OUTPUT_PLUGINS,
    OPTIONAL_ASSET_PLUGINS,
    RETIRED_MANAGED_OUTPUT_PLUGINS,
    RETIRED_OPTIONAL_ASSET_PLUGINS,
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
from .models import ApplyResult
from .omarchy import capabilities, run
from .palette import load as load_palette
from .paths import Paths
from .registry import BY_ID
from .report import build_report, write_report
from .resources import asset
from .snapshot import build as build_snapshot
from .state import (
    StateError,
    complete_cava_opt_in,
    enforce_cava_opt_in,
    load,
    migration_lock,
    mutation_lock,
    save,
)
from .templates import reconcile as reconcile_templates
from .update import apply as apply_update
from .update import check as check_update
from .zed import ZedThemeError
from .zed import configure_settings as configure_zed_settings
from .zed import status as zed_status
from .zed import validate_settings_edit as validate_zed_settings_edit

SCHEMA_VERSION = 1
CANONICAL_PALETTE_MIGRATION = "canonical-palette-v1"


def _merge_migrated_enabled(
    enabled: dict[str, bool], updates: dict[str, bool]
) -> None:
    enabled.update(updates)
    if updates.get("discord-system24"):
        enabled["discord"] = False
    elif updates.get("discord"):
        enabled["discord-system24"] = False


def _cleanup_warning_is_incomplete(message: str) -> bool:
    successful_preservation = (
        "preserved user-modified ",
        "preserved non-file legacy output path: ",
        "preserved untracked Zellij theme instead of deleting it: ",
        "Cava theme selection changed outside THPM; ",
    )
    return not message.startswith(successful_preservation)


def _cleanup_warning_path(message: str) -> str | None:
    candidate = message.rsplit(": ", 1)[-1]
    if not candidate.startswith("/"):
        return None
    path = Path(candidate)
    if path.exists() or path.is_symlink():
        return str(path)
    if path.suffix == ".backup":
        state_path = path.with_suffix(".json")
        if state_path.is_file() and not state_path.is_symlink():
            return str(state_path)
    return None


def _cleanup_retired_integrations(paths: Paths) -> tuple[list[str], list[dict[str, str]]]:
    changed: list[str] = []
    warnings: list[dict[str, str]] = []
    for plugin_id in sorted(RETIRED_OPTIONAL_ASSET_PLUGINS):
        cleanup_changed, cleanup_warnings = cleanup_optional_assets(
            paths, plugin_id, assume_legacy=True
        )
        changed.extend(cleanup_changed)
        warnings.extend(
            {"plugin": plugin_id, "message": message}
            for message in cleanup_warnings
        )
    for plugin_id in sorted(RETIRED_MANAGED_OUTPUT_PLUGINS):
        cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
            paths, plugin_id, assume_legacy=True
        )
        changed.extend(cleanup_changed)
        warnings.extend(
            {"plugin": plugin_id, "message": message}
            for message in cleanup_warnings
        )
    return changed, warnings


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


def _preferences(paths: Paths) -> tuple[Preferences, str | None]:
    try:
        return load_config(paths), None
    except ConfigError as exc:
        return Preferences(restart_policy="notify"), f"{exc}; using notify-only restart policy"


def _notify_restart_required(apps: list[str]) -> bool:
    if not apps or not shutil.which("notify-send"):
        return False
    names = ", ".join(dict.fromkeys(apps))
    body = f"Restart to load the new theme colors: {names}"
    try:
        completed = subprocess.run(
            [
                "notify-send",
                "--app-name=THPM",
                "--icon=preferences-desktop-theme",
                "Theme applied",
                body,
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


class Service:
    def __init__(
        self,
        paths: Paths | None = None,
        progress: Callable[[str, str | None], None] | None = None,
        events: Callable[[dict[str, object]], None] | None = None,
    ):
        self.paths = paths or Paths.discover()
        self.progress = progress
        self.events = events
        self._event_count = 0
        self._finished_event_plugins: set[str] = set()

    def _step(self, message: str, detail: str | None = None) -> None:
        if self.progress is not None:
            self.progress(message, detail)

    def _event(self, event: dict[str, object]) -> None:
        self._event_count += 1
        delivered = True
        if self.events is not None:
            try:
                self.events(event)
            except Exception:
                delivered = False
        activity_event = getattr(self.progress, "event", None)
        if callable(activity_event):
            try:
                activity_event(event)
            except Exception:
                delivered = False
        if (
            delivered
            and event.get("type") == "integration_finished"
            and event.get("plugin")
        ):
            self._finished_event_plugins.add(str(event["plugin"]))

    def _set_total(self, total: int) -> None:
        set_total = getattr(self.progress, "set_total", None)
        if callable(set_total):
            set_total(total)

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
        preferences, config_warning = _preferences(self.paths)
        migration = _migration_status(self.paths)
        warnings = []
        if config_warning:
            warnings.append({"message": config_warning})
        if migration["pending"]:
            warnings.append({"message": "template refresh migration pending; run thpm reconcile --refresh"})
        return envelope(
            "ui-state",
            summary="THPM plugin state",
            version=__version__,
            counts=counts,
            plugins=plugins,
            menuSurface=menu_surface,
            preferences=preferences.json(),
            migration=migration,
            warnings=warnings,
            errors=[],
        )

    def preferences(self) -> dict[str, object]:
        preferences, warning = _preferences(self.paths)
        return envelope(
            "config",
            summary=f"Application restart policy: {preferences.restart_policy}",
            preferences=preferences.json(),
            configFile=str(self.paths.config_file),
            warnings=[{"message": warning}] if warning else [],
            errors=[],
        )

    def restart_policy(self, requested: str | None = None) -> dict[str, object]:
        current, _warning = _preferences(self.paths)
        selected = current.restart_policy
        if requested == "toggle":
            selected = "notify" if selected == "automatic" else "automatic"
        elif requested is not None:
            selected = requested
        if selected not in {"automatic", "notify"}:
            return envelope(
                "config-restart-policy",
                False,
                summary=f"unknown restart policy: {selected}",
                errors=[{"message": "choose automatic or notify"}],
            )
        changed = selected != current.restart_policy or _warning is not None
        if requested is not None:
            with mutation_lock(self.paths):
                save_config(self.paths, Preferences(restart_policy=selected))
        preferences = Preferences(restart_policy=selected)
        return envelope(
            "config-restart-policy",
            summary=f"Application restart policy: {selected}",
            changed=changed and requested is not None,
            preferences=preferences.json(),
            configFile=str(self.paths.config_file),
            warnings=[],
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
        return self._configure_zed(confirmed=confirmed, enable_sync=False)

    def _configure_zed(
        self, *, confirmed: bool, enable_sync: bool
    ) -> dict[str, object]:
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
                enabled["zed-extra"] = was_enabled or enable_sync
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

    def _repair_cava(self, *, enable: bool) -> dict[str, object]:
        operation = "cava-setup" if enable else "doctor"
        started_ns = time.monotonic_ns()

        def response(
            successful: bool,
            summary: str,
            diagnostics: dict[str, object],
            **fields: object,
        ) -> dict[str, object]:
            payload = envelope(
                operation,
                successful,
                summary=summary,
                diagnostics={"cava": diagnostics},
                checks=diagnostics.get("checks", []),
                durationMs=max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
                **fields,
            )
            record_payload(self.paths, payload, plugin="cava")
            return payload

        try:
            enabled_before = load(self.paths)
        except StateError as exc:
            diagnostics = diagnose_cava(
                self.paths, command_path=shutil.which("cava")
            )
            return response(
                False,
                "Cava configuration cannot be repaired",
                diagnostics,
                errors=[{"plugin": "cava", "message": str(exc)}],
            )
        if not enable and not enabled_before.get("cava"):
            diagnostics = diagnose_cava(
                self.paths, command_path=shutil.which("cava")
            )
            return response(
                False,
                "Cava integration is disabled",
                diagnostics,
                errors=[
                    {
                        "plugin": "cava",
                        "message": "run `thpm enable cava` instead",
                    }
                ],
            )
        command = shutil.which("cava")
        diagnostics = diagnose_cava(self.paths, command_path=command)
        version_check = next(
            check
            for check in diagnostics["checks"]
            if check["id"] == "cava.version"
        )
        if command is None or version_check["status"] != "pass":
            return response(
                False,
                "Cava cannot use THPM theme files",
                diagnostics,
                errors=[
                    {"plugin": "cava", "message": str(version_check["summary"])}
                ],
            )
        try:
            config_target = safe_cava_config_target(
                self.paths, cava_config_path(self.paths)
            )
        except CavaError as exc:
            return response(
                False,
                "Cava configuration cannot be repaired safely",
                diagnostics,
                errors=[{"plugin": "cava", "message": str(exc)}],
            )

        # Render the generated fallback before beginning the mutation transaction.
        # This refresh runs with the persisted Cava setting unchanged, so its hook
        # cannot take over or reload Cava midway through setup.
        if cava_theme_source(self.paths) is None:
            prepared = dict(enabled_before)
            prepared["cava"] = True
            with mutation_lock(self.paths):
                reconcile_templates(self.paths, prepared)
            try:
                completed = run("theme", "refresh", check=False, timeout=180)
            except (OSError, subprocess.SubprocessError) as exc:
                completed = None
                refresh_error = str(exc)
            else:
                refresh_error = completed.stderr.strip() if completed.returncode else ""
            if completed is None or completed.returncode != 0 or cava_theme_source(self.paths) is None:
                with mutation_lock(self.paths):
                    reconcile_templates(self.paths, enabled_before)
                return response(
                    False,
                    "unable to render the Cava theme",
                    diagnose_cava(self.paths, command_path=command),
                    errors=[
                        {
                            "plugin": "cava",
                            "message": refresh_error
                            or "theme refresh did not render Cava output",
                        }
                    ],
                )

        output = self.paths.config_home / "cava/themes/thpm"
        state_root = self.paths.managed_asset_state_dir
        rollback_paths = [
            config_target,
            cava_selector_state_path(self.paths),
            self.paths.cava_opt_in_marker,
            output,
            state_root / "generated-cava.json",
            state_root / "generated-cava.backup",
            state_root / "generated-cava.legacy-checked",
        ]
        changed: list[str] = []
        result = ApplyResult("cava", "unchanged")
        old_cava_enabled = bool(enabled_before.get("cava"))
        try:
            with mutation_lock(self.paths):
                snapshots = {path: _snapshot_file(path) for path in rollback_paths}
                current = load(self.paths)
                old_cava_enabled = bool(current.get("cava"))
                current["cava"] = True
                save(self.paths, current)
                changed.extend(reconcile_templates(self.paths, current))
                changed.extend(configure_cava_selector(self.paths))
                try:
                    result = apply_integration(
                        "cava",
                        self.paths,
                        force_reload=True,
                        defer_reload=True,
                    )
                    changed.extend(result.changed)
                    if result.status in {"failed", "skipped"}:
                        raise RuntimeError(result.message)
                    verified = diagnose_cava(self.paths, command_path=command)
                    blocking_ids = {
                        "cava.binary",
                        "cava.version",
                        "cava.config",
                        "cava.selector",
                        "cava.source",
                        "cava.target",
                        "cava.ownership",
                    }
                    blocking = [
                        check
                        for check in verified["checks"]
                        if check["id"] in blocking_ids
                        and check["status"] == "error"
                    ]
                    if blocking:
                        raise RuntimeError(str(blocking[0]["summary"]))
                    # This is the durable boundary between legacy default state
                    # and explicit consent to manage the user's Cava selector.
                    complete_cava_opt_in(self.paths)
                except (
                    OSError,
                    RuntimeError,
                    UnicodeError,
                    ValueError,
                    CavaError,
                    StateError,
                ):
                    for path, snapshot in snapshots.items():
                        _restore_file(path, snapshot)
                    rollback_state = load(self.paths)
                    rollback_state["cava"] = old_cava_enabled
                    save(self.paths, rollback_state)
                    reconcile_templates(self.paths, rollback_state)
                    raise
        except (OSError, RuntimeError, UnicodeError, ValueError, CavaError) as exc:
            failed = diagnose_cava(self.paths, command_path=command)
            return response(
                False,
                "unable to configure Cava",
                failed,
                errors=[{"plugin": "cava", "message": str(exc)}],
            )

        actions, restart_required, reload_warnings = reload_cava_processes(self.paths)
        diagnostics = diagnose_cava(self.paths, command_path=command)
        warnings = [
            {"plugin": "cava", "message": message}
            for message in [*result.warnings, *reload_warnings]
        ]
        return response(
            True,
            "Cava now uses THPM's managed theme",
            diagnostics,
            committed=True,
            stateChanged=not old_cava_enabled,
            changed=list(dict.fromkeys(changed)),
            actions=[*result.actions, *actions],
            restartRequired=list(
                dict.fromkeys([*result.restartRequired, *restart_required])
            ),
            warnings=warnings,
            errors=[],
        )

    def set_enabled(self, plugin_id: str, value: bool, *, confirmed: bool = False, refresh: bool = True) -> dict[str, object]:
        operation = "plugin-enable" if value else "plugin-disable"
        started_ns = time.monotonic_ns()
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
        if value and plugin_id == "cava":
            result = self._repair_cava(enable=True)
            result.update(
                operation=operation,
                summary=(
                    "cava enabled and configured"
                    if result["ok"]
                    else str(result.get("summary", "unable to enable cava"))
                ),
                plugins=self.views(),
            )
            return result
        if value and plugin_id == "zed-extra":
            result = self._configure_zed(confirmed=True, enable_sync=True)
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
        errors: list[dict[str, str]] = []
        cleanup_errors: list[dict[str, str]] = []
        residuals: list[dict[str, object]] = []
        retained_paths: list[str] = []
        restart_required: list[str] = []

        def record_cleanup(messages: list[str]) -> None:
            warnings.extend(
                {"plugin": plugin_id, "message": message} for message in messages
            )
            for message in messages:
                if not _cleanup_warning_is_incomplete(message):
                    continue
                error = {"plugin": plugin_id, "message": message}
                cleanup_errors.append(error)
                errors.append(error)
                retained_path = _cleanup_warning_path(message)
                residual = {"plugin": plugin_id, "message": message}
                if retained_path:
                    retained_paths.append(retained_path)
                    residual["retainedPaths"] = [retained_path]
                residuals.append(residual)

        cava_was_running = bool(
            not value
            and plugin_id == "cava"
            and running_cava_requires_restart(self.paths)
        )
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
                record_cleanup(cleanup_warnings)
            elif not value and plugin_id == "zed-extra":
                cleanup_changed, cleanup_warnings = cleanup_zed_assets(
                    self.paths, assume_legacy=True
                )
                changed.extend(cleanup_changed)
                record_cleanup(cleanup_warnings)
            elif not value and plugin_id in OPTIONAL_ASSET_PLUGINS:
                cleanup_changed, cleanup_warnings = cleanup_optional_assets(
                    self.paths, plugin_id, assume_legacy=True
                )
                changed.extend(cleanup_changed)
                _actions, reload_warnings = reload_restored_integration(
                    plugin_id, cleanup_changed
                )
                record_cleanup(cleanup_warnings)
                warnings.extend(
                    {"plugin": plugin_id, "message": message}
                    for message in reload_warnings
                )
            elif (
                not value
                and plugin_id in MANAGED_OUTPUT_PLUGINS
                and not shared_output_in_use
            ):
                selector_warnings: list[str] = []
                if plugin_id == "cava":
                    selector_changed, selector_warnings = restore_cava_selector(
                        self.paths
                    )
                    changed.extend(selector_changed)
                    record_cleanup(selector_warnings)
                    blocking_selector_warnings = [
                        message
                        for message in selector_warnings
                        if "changed outside THPM" not in message
                    ]
                    if blocking_selector_warnings:
                        residual_message = (
                            "Cava selector could not be restored; preserved "
                            "the still-selected managed theme"
                        )
                        error = {"plugin": "cava", "message": residual_message}
                        cleanup_errors.append(error)
                        errors.append(error)
                        config_path = str(cava_config_path(self.paths))
                        retained_paths.append(config_path)
                        residuals.append(
                            {
                                "plugin": "cava",
                                "message": residual_message,
                                "retainedPaths": [config_path],
                            }
                        )
                else:
                    blocking_selector_warnings = []
                if not blocking_selector_warnings:
                    cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
                        self.paths, plugin_id, assume_legacy=True
                    )
                    changed.extend(cleanup_changed)
                    record_cleanup(cleanup_warnings)
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
        if cava_was_running and not errors:
            restart_required.append("Cava")
        summary = f"{plugin_id} {'enabled' if value else 'disabled'}"
        if cleanup_errors:
            summary += "; setting was saved, but cleanup is incomplete"
        elif errors:
            summary += "; setting was saved, but theme refresh failed"
        payload = envelope(
            operation,
            not errors,
            summary=summary,
            committed=True,
            stateChanged=was_enabled != value,
            cleanupIncomplete=bool(cleanup_errors),
            residuals=residuals,
            retainedPaths=list(dict.fromkeys(retained_paths)),
            recoveryCommand=(
                f"thpm disable {plugin_id}" if cleanup_errors else None
            ),
            changed=changed,
            refreshed=refreshed,
            plugins=self.views(),
            errors=errors,
            warnings=warnings,
            restartRequired=restart_required,
            durationMs=max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
        )
        if plugin_id == "cava":
            record_payload(self.paths, payload, plugin="cava")
        return payload

    def doctor(
        self,
        plugin_id: str | None = None,
        *,
        fix: bool = False,
        confirmed: bool = False,
    ) -> dict[str, object]:
        if fix and plugin_id is None:
            return envelope(
                "doctor",
                False,
                summary="Doctor repair requires one plugin",
                errors=[{"message": "use `thpm doctor <plugin> --fix`"}],
            )
        if fix and plugin_id != "cava":
            return envelope(
                "doctor",
                False,
                summary=f"Doctor repair is not available for {plugin_id}",
                errors=[{"message": "automatic Doctor repair is currently available only for cava"}],
            )
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        caps = capabilities()
        if not caps.available: errors.append({"message": "Omarchy 4 capabilities missing: " + ", ".join(caps.missing)})
        active_palette: dict[str, str] = {}
        try: active_palette = load_palette(self.paths.current_theme / "colors.toml")
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
        known = {(item.get("plugin"), item["message"]) for item in warnings}
        if any(plugin["id"] == "gtk-css-compat" for plugin in plugins):
            for message in gtk_file_doctor_warnings(self.paths):
                entry = ("gtk-css-compat", message)
                if entry not in known:
                    warnings.append({"plugin": entry[0], "message": entry[1]})
                    known.add(entry)
        if (
            active_palette
            and self.paths == Paths.discover()
            and any(plugin["id"] == "native-gnome" for plugin in plugins)
        ):
            for message in gtk_session_doctor_warnings(
                self.paths, str(active_palette.get("mode", "dark"))
            ):
                entry = ("native-gnome", message)
                if entry not in known:
                    warnings.append({"plugin": entry[0], "message": entry[1]})
                    known.add(entry)
        local_compat = next((plugin for plugin in plugins if plugin["id"] == "vscode-local-compat"), None)
        if local_compat and local_compat["enabled"] and local_compat.get("applicable", True):
            known = {(item.get("plugin"), item["message"]) for item in warnings}
            for message in vscode_doctor_warnings(self.paths):
                entry = ("vscode-local-compat", message)
                if entry not in known:
                    warnings.append({"plugin": entry[0], "message": entry[1]})
        checks: list[dict[str, object]] = []
        cava_diagnostics: dict[str, object] | None = None
        cava_view = next((plugin for plugin in plugins if plugin["id"] == "cava"), None)
        if cava_view is not None and (plugin_id == "cava" or cava_view["enabled"]):
            cava_diagnostics = diagnose_cava(
                self.paths, command_path=shutil.which("cava")
            )
            checks = list(cava_diagnostics["checks"])
            for check in checks:
                entry = {"plugin": "cava", "check": str(check["id"]), "message": str(check["summary"])}
                if check["status"] == "error":
                    errors.append(entry)
                elif check["status"] in {"warning", "unknown"}:
                    warnings.append(entry)
        _configured, config_warning = _preferences(self.paths)
        if config_warning:
            warnings.append({"message": config_warning})
        migration = _migration_status(self.paths)
        if migration["pending"]:
            warnings.append({"message": "template refresh migration pending; run thpm reconcile --refresh"})
        payload = envelope(
            "doctor",
            not errors,
            summary=f"{len(errors)} errors, {len(warnings)} warnings",
            plugins=plugins,
            errors=errors,
            warnings=warnings,
            migration=migration,
            capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)},
            checks=checks,
            diagnostics={"cava": cava_diagnostics} if cava_diagnostics else {},
        )
        if not fix:
            return payload
        if cava_diagnostics is None or cava_view is None:
            payload.update(
                ok=False,
                summary="Cava diagnostics are unavailable",
            )
            return payload
        if not cava_view["enabled"]:
            payload.update(
                ok=False,
                summary="Cava integration is disabled",
                errors=[
                    *errors,
                    {"plugin": "cava", "message": "run `thpm enable cava` instead"},
                ],
            )
            return payload
        if not confirmed:
            payload.update(
                ok=False,
                confirmationRequired=True,
                repairPlan=[
                    check["repair"]
                    for check in checks
                    if isinstance(check.get("repair"), dict)
                    and check["repair"].get("available")
                ],
                summary="confirmation required to repair Cava",
            )
            return payload
        return self._repair_cava(enable=False)

    def support_report(
        self, plugin_id: str | None = None, *, output: Path | None = None
    ) -> dict[str, object]:
        if plugin_id is not None and plugin_id not in BY_ID:
            return envelope(
                "report",
                False,
                summary=f"unknown plugin: {plugin_id}",
                errors=[{"message": "choose a registered THPM integration"}],
            )
        doctor = self.doctor(plugin_id)
        plugin_view = next(
            (
                plugin
                for plugin in doctor.get("plugins", [])
                if isinstance(plugin, dict) and plugin.get("id") == plugin_id
            ),
            None,
        )
        try:
            report = build_report(
                self.paths,
                plugin=plugin_id,
                plugin_view=plugin_view,
                doctor=doctor,
            )
            report_path = write_report(self.paths, report, output=output)
        except (OSError, UnicodeError, ValueError) as exc:
            return envelope(
                "report",
                False,
                summary=f"unable to create support report: {exc}",
                errors=[{"message": str(exc)}],
            )
        return envelope(
            "report",
            summary=f"support report saved to {report_path}",
            reportPath=str(report_path),
            shareCommand=f"Share {report_path} with the THPM maintainer",
            report=report,
            errors=[],
        )

    def reconcile(
        self, refresh: bool = False, *, defer_upgrade_refresh: bool = False
    ) -> dict[str, object]:
        self._step("Reading integration state")
        deferred = defer_upgrade_refresh or _source_activation_in_progress()
        with migration_lock(self.paths):
            with mutation_lock(self.paths):
                self._step("Rendering managed templates")
                enabled = load(self.paths)
                save(self.paths, enabled)
                changed = reconcile_templates(self.paths, enabled)
                retired_changed, retired_warnings = _cleanup_retired_integrations(
                    self.paths
                )
                changed.extend(retired_changed)
                self._step("Installing theme hook")
                atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
                atomic_copy(
                    asset("hooks", "90-thpm-ui"),
                    self.paths.post_update_hook_file,
                    0o755,
                )
                changed.extend(
                    (str(self.paths.hook_file), str(self.paths.post_update_hook_file))
                )
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
            warnings=retired_warnings,
            errors=errors,
        )

    def install_check(self) -> dict[str, object]:
        caps = capabilities()
        missing_assets = [
            str(asset(kind))
            for kind in ("templates", "hooks", "qml", "spicetify")
            if not asset(kind).is_dir()
        ]
        errors = ([{"message": item} for item in caps.missing] +
            [{"message": f"packaged asset directory missing: {item}"} for item in missing_assets])
        return envelope("install-check", not errors, summary="installation prerequisites satisfied" if not errors else "installation prerequisites missing",
            capabilities={"routes": sorted(caps.routes), "missing": list(caps.missing)}, errors=errors)

    def install(self, with_ui: bool = True) -> dict[str, object]:
        self._set_total(5 if with_ui else 4)
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
                _merge_migrated_enabled(enabled, migrated)
                enforce_cava_opt_in(self.paths, enabled)
                save(self.paths, enabled)
                changed = reconcile_templates(self.paths, enabled)
                retired_changed, retired_warnings = _cleanup_retired_integrations(
                    self.paths
                )
                changed.extend(retired_changed)
                atomic_copy(asset("hooks", "90-thpm"), self.paths.hook_file, 0o755)
                atomic_copy(
                    asset("hooks", "90-thpm-ui"),
                    self.paths.post_update_hook_file,
                    0o755,
                )
                changed.extend(
                    (str(self.paths.hook_file), str(self.paths.post_update_hook_file))
                )
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
            warnings=retired_warnings,
            errors=errors,
        )

    def uninstall(self) -> dict[str, object]:
        warnings: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        residuals: list[dict[str, object]] = []
        retained_paths: list[str] = []
        restart_required: list[str] = []

        def record_cleanup(plugin_id: str, messages: list[str]) -> None:
            warnings.extend(
                {"plugin": plugin_id, "message": message} for message in messages
            )
            for message in messages:
                if not _cleanup_warning_is_incomplete(message):
                    continue
                retained_path = _cleanup_warning_path(message)
                residual = {"plugin": plugin_id, "message": message}
                if retained_path:
                    retained_paths.append(retained_path)
                    residual["retainedPaths"] = [retained_path]
                residuals.append(residual)
                errors.append({"plugin": plugin_id, "message": message})

        cava_was_running = running_cava_requires_restart(self.paths)
        self._step("Disabling managed integrations")
        with migration_lock(self.paths):
            with mutation_lock(self.paths):
                disabled = {plugin_id: False for plugin_id in BY_ID}
                changed = reconcile_templates(self.paths, disabled)
                changed.extend(cleanup_gtk(self.paths))
                self._step("Restoring managed application files")
                for plugin_id in sorted(
                    OPTIONAL_ASSET_PLUGINS | RETIRED_OPTIONAL_ASSET_PLUGINS
                ):
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
                    record_cleanup(plugin_id, cleanup_warnings)
                    warnings.extend(
                        {"plugin": plugin_id, "message": message}
                        for message in reload_warnings
                    )
                selector_changed, selector_warnings = restore_cava_selector(self.paths)
                changed.extend(selector_changed)
                record_cleanup("cava", selector_warnings)
                blocking_selector_warnings = [
                    message
                    for message in selector_warnings
                    if "changed outside THPM" not in message
                ]
                if blocking_selector_warnings:
                    residual_message = (
                        "preserved the Cava theme target because its still-selected "
                        "configuration could not be restored"
                    )
                    config_path = str(cava_config_path(self.paths))
                    if Path(config_path).exists():
                        retained_paths.append(config_path)
                    warnings.append({"plugin": "cava", "message": residual_message})
                    errors.append({"plugin": "cava", "message": residual_message})
                    residuals.append(
                        {
                            "plugin": "cava",
                            "message": residual_message,
                            "retainedPaths": [config_path],
                        }
                    )
                for plugin_id in sorted(
                    MANAGED_OUTPUT_PLUGINS | RETIRED_MANAGED_OUTPUT_PLUGINS
                ):
                    if plugin_id == "cava" and blocking_selector_warnings:
                        continue
                    cleanup_changed, cleanup_warnings = cleanup_managed_outputs(
                        self.paths,
                        plugin_id,
                        assume_legacy=True,
                    )
                    changed.extend(cleanup_changed)
                    record_cleanup(plugin_id, cleanup_warnings)
                zellij_changed, zellij_warnings = cleanup_zellij(self.paths)
                changed.extend(zellij_changed)
                record_cleanup("zellij", zellij_warnings)
                self._step("Removing theme hook and migration state")
                for hook_file in (
                    self.paths.hook_file,
                    self.paths.post_update_hook_file,
                ):
                    if hook_file.exists():
                        hook_file.unlink()
                        changed.append(str(hook_file))
                if self.paths.canonical_palette_migration_marker.exists():
                    self.paths.canonical_palette_migration_marker.unlink()
                    changed.append(str(self.paths.canonical_palette_migration_marker))
                if not errors and (
                    self.paths.cava_opt_in_marker.exists()
                    or self.paths.cava_opt_in_marker.is_symlink()
                ):
                    self.paths.cava_opt_in_marker.unlink()
                    changed.append(str(self.paths.cava_opt_in_marker))
                compat_asset = asset("compat", "theme-env.sh")
                if self.paths.legacy_compat_file.is_file() and compat_asset.is_file() and self.paths.legacy_compat_file.read_bytes() == compat_asset.read_bytes():
                    self.paths.legacy_compat_file.unlink()
                    changed.append(str(self.paths.legacy_compat_file))
        self._step("Removing control panel")
        ui_result = ui.remove(self.paths)
        self.paths.update_cache_file.unlink(missing_ok=True)
        if not errors:
            for product_dir in (self.paths.thpm_config_dir, self.paths.thpm_state_dir):
                if not product_dir.exists():
                    continue
                try:
                    shutil.rmtree(product_dir)
                    changed.append(str(product_dir))
                except OSError as exc:
                    message = f"could not remove THPM product state: {product_dir}: {exc}"
                    errors.append({"message": message})
                    residuals.append(
                        {
                            "message": message,
                            "retainedPaths": [str(product_dir)],
                        }
                    )
                    retained_paths.append(str(product_dir))
        if not errors and self.paths.install_metadata.is_file():
            try:
                if 'origin = "source"' in self.paths.install_metadata.read_text():
                    self.paths.install_metadata.unlink()
                    changed.append(str(self.paths.install_metadata))
            except OSError as exc:
                message = f"could not remove source installation metadata: {exc}"
                errors.append({"message": message})
                residuals.append(
                    {
                        "message": message,
                        "retainedPaths": [str(self.paths.install_metadata)],
                    }
                )
                retained_paths.append(str(self.paths.install_metadata))
        if cava_was_running and not blocking_selector_warnings:
            restart_required.append("Cava")
        cleanup_incomplete = bool(errors)
        return envelope(
            "uninstall",
            not cleanup_incomplete,
            summary=(
                "THPM integrations and product state removed"
                if not cleanup_incomplete
                else "THPM cleanup is incomplete; recovery data was retained"
            ),
            committed=True,
            cleanupIncomplete=cleanup_incomplete,
            residuals=residuals,
            retainedPaths=list(dict.fromkeys(retained_paths)),
            recoveryCommand="thpm uninstall" if cleanup_incomplete else None,
            changed=changed,
            ui=ui_result,
            errors=errors,
            warnings=warnings,
            restartRequired=restart_required,
        )

    def hook_run(self, event: str, event_args: list[str] | tuple[str, ...] = ()) -> dict[str, object]:
        if event != "theme-set":
            return envelope("hook-run", False, summary=f"unsupported hook event: {event}",
                event=event, eventArgs=list(event_args), errors=[{"message": "unsupported hook event"}])
        preferences, config_warning = _preferences(self.paths)
        force_reload = os.environ.get("THPM_FORCE_RELOAD") == "1"
        with mutation_lock(self.paths):
            result = apply_enabled(
                self.paths,
                load(self.paths),
                events=self._event,
                automatic_restarts=preferences.automatic_app_restarts,
                force_reload=force_reload,
            )
        if config_warning:
            result["warnings"].insert(0, {"message": config_warning})
        restart_required = list(result.get("restartRequired") or [])
        notification_sent = _notify_restart_required(restart_required)
        theme_name = event_args[0] if event_args else ""
        subject = f"theme {theme_name}" if theme_name else "active theme"
        counts = result.get("counts") or {"applied": 0, "unchanged": 0, "skipped": 0, "failed": len(result["errors"])}
        summary = (f"processed {subject}: {counts['applied']} applied, {counts['unchanged']} unchanged, "
            f"{counts['skipped']} skipped, {counts['failed']} failed")
        payload = envelope("hook-run", not result["errors"], summary=summary,
            event=event, eventArgs=list(event_args), themeName=theme_name or None,
            restartPolicy=preferences.restart_policy,
            restartNotificationSent=notification_sent,
            forced=force_reload,
            **result)
        record_payload(self.paths, payload)
        return payload

    def run_theme(self) -> dict[str, object]:
        event_count = self._event_count
        finished_event_plugins = set(self._finished_event_plugins)
        self._step("Rendering active theme")
        self.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="thpm-hook-",
            suffix=".json",
            dir=self.paths.runtime_dir,
            delete=False,
        ) as report_file, tempfile.NamedTemporaryFile(
            prefix="thpm-events-",
            suffix=".jsonl",
            dir=self.paths.runtime_dir,
            delete=False,
        ) as event_file:
            report_path = Path(report_file.name)
            event_path = Path(event_file.name)
        environment = os.environ.copy()
        environment["THPM_HOOK_REPORT"] = str(report_path)
        environment["THPM_HOOK_EVENTS"] = str(event_path)
        environment["THPM_FORCE_RELOAD"] = "1"
        try:
            completed = run(
                "theme",
                "refresh",
                check=False,
                timeout=180,
                env=environment,
                event_path=event_path,
                event_handler=self._event,
            )
            try:
                hook_payload = json.loads(report_path.read_text())
            except (OSError, ValueError):
                hook_payload = None
        finally:
            report_path.unlink(missing_ok=True)
            event_path.unlink(missing_ok=True)

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
                progressReported=self._event_count > event_count,
            )

        results = hook_payload.get("results") or []
        result_plugins = {
            str(result.get("id"))
            for result in results
            if isinstance(result, dict) and result.get("id")
        }
        streamed_plugins = self._finished_event_plugins - finished_event_plugins
        progress_reported = (
            self._event_count > event_count and result_plugins <= streamed_plugins
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
            results=results,
            changed=hook_payload.get("changed") or [],
            actions=hook_payload.get("actions") or [],
            restartRequired=hook_payload.get("restartRequired") or [],
            restartPolicy=hook_payload.get("restartPolicy"),
            restartNotificationSent=bool(
                hook_payload.get("restartNotificationSent")
            ),
            warnings=hook_payload.get("warnings") or [],
            errors=errors,
            stdout=completed.stdout,
            progressReported=progress_reported,
        )

    def migrate(self) -> dict[str, object]:
        self._step("Inspecting legacy hooks")
        enabled_updates, files = inspect_legacy(self.paths)
        compat_required = needs_compat(self.paths, files)
        with mutation_lock(self.paths):
            self._step("Rendering migrated integration state")
            enabled = load(self.paths)
            _merge_migrated_enabled(enabled, enabled_updates)
            save(self.paths, enabled)
            changed = reconcile_templates(self.paths, enabled)
            self._step("Archiving legacy hooks")
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

    def update_apply(self, *, update_mode: str = "inline") -> dict[str, object]:
        self._step("Checking for an available release")
        result = apply_update(
            self.paths, progress=self.progress, mode=update_mode
        )
        status = str(result.get("status"))
        refresh_error = str(result.get("refreshError") or "")
        ui_refresh_error = str(result.get("uiRefreshError") or "")
        ok = (
            status in {"updated", "started", "current"}
            and not refresh_error
            and not ui_refresh_error
        )
        summary = {
            "updated": "THPM updated",
            "started": "package update terminal opened; completion is pending",
            "current": "THPM is current",
            "requires-interactive": "AUR updates require an interactive terminal",
        }.get(status, "THPM update not applied")
        if status == "updated" and not refresh_error and not ui_refresh_error:
            summary += "; integrations and control panel synchronized"
        if refresh_error:
            summary += "; update committed, but active theme refresh failed"
        if ui_refresh_error:
            summary += "; update committed, but control panel refresh failed"
        if status != "started" and result.get("refreshRequired"):
            summary += "; run thpm reconcile --refresh"
        if status != "started" and result.get("uiRefreshRequired"):
            summary += "; run thpm ui install"
        errors = []
        if refresh_error:
            errors.append({"message": refresh_error})
        if ui_refresh_error:
            errors.append({"message": ui_refresh_error})
        if not ok and not errors:
            errors.append({"message": str(result.get("error", status))})
        return envelope(
            "update-apply",
            ok,
            summary=summary,
            committed=status == "updated",
            pending=status == "started",
            result=result,
            errors=errors,
        )
