from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, ui
from .files import atomic_text
from .paths import Paths
from .presentation import Activity, operation_name, render, reporter
from .service import Service, envelope


class ThpmArgumentParser(argparse.ArgumentParser):
    json_errors = False

    def error(self, message: str) -> None:
        if self.json_errors:
            payload = envelope(
                "parse",
                False,
                summary="invalid command",
                errors=[{"message": message}],
            )
            self._print_message(
                json.dumps(payload, separators=(",", ":")) + "\n", sys.stdout
            )
            self.exit(2)
        super().error(message)


def _json_parse_errors(root: argparse.ArgumentParser, enabled: bool) -> None:
    root.json_errors = enabled
    for action in root._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _json_parse_errors(child, enabled)


def _output_options(command: argparse.ArgumentParser, *, nested: bool = False) -> None:
    default = argparse.SUPPRESS if nested else False
    command.add_argument("--json", action="store_true", default=default)
    command.add_argument("-v", "--verbose", action="store_true", default=default)
    command.add_argument("-q", "--quiet", action="store_true", default=default)


def parser() -> argparse.ArgumentParser:
    root = ThpmArgumentParser(
        prog="thpm", description="Omarchy 4 theme integration manager"
    )
    root.add_argument("--json", action="store_true", dest="global_json")
    root.add_argument(
        "-v", "--verbose", action="store_true", dest="global_verbose"
    )
    root.add_argument("-q", "--quiet", action="store_true", dest="global_quiet")
    root.add_argument("--version", action="version", version=f"thpm {__version__}")
    commands = root.add_subparsers(dest="command")

    for name in (
        "list",
        "status",
        "native-status",
        "reconcile",
        "run",
        "install",
        "uninstall",
        "migrate",
        "version",
        "tui",
    ):
        sub = commands.add_parser(name)
        _output_options(sub)
        if name == "reconcile":
            sub.add_argument("--refresh", action="store_true")
            sub.add_argument(
                "--defer-upgrade-refresh",
                action="store_true",
                help=argparse.SUPPRESS,
            )
        if name == "install":
            sub.add_argument("--no-ui", action="store_true")
            sub.add_argument("--check", action="store_true", dest="install_check")

    for name in ("enable", "disable"):
        sub = commands.add_parser(name)
        sub.add_argument("plugin")
        sub.add_argument("--yes", action="store_true")
        _output_options(sub)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("plugin", nargs="?")
    doctor.add_argument("--fix", action="store_true", help="repair one diagnosed integration")
    doctor.add_argument("--yes", action="store_true", help="confirm the repair non-interactively")
    _output_options(doctor)

    report = commands.add_parser(
        "report", help="create a privacy-preserving support report"
    )
    report.add_argument("plugin", nargs="?")
    report.add_argument("--output", type=Path)
    _output_options(report)

    hook = commands.add_parser("hook-run")
    hook.add_argument("event")
    hook.add_argument("event_args", nargs="*")
    _output_options(hook)

    plugin = commands.add_parser("plugin")
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    for name in ("enable", "disable"):
        sub = plugin_sub.add_parser(name)
        sub.add_argument("plugin")
        sub.add_argument("--yes", action="store_true")
        _output_options(sub)

    ui_cmd = commands.add_parser("ui")
    ui_sub = ui_cmd.add_subparsers(dest="ui_command", required=True)
    for name in ("state", "install", "sync", "remove", "status", "open"):
        sub = ui_sub.add_parser(name)
        _output_options(sub)
    surface = ui_sub.add_parser("surface")
    surface.add_argument(
        "surface", nargs="?", choices=("gui", "tui", "toggle")
    )
    _output_options(surface)

    config = commands.add_parser(
        "config", help="inspect or change user preferences"
    )
    _output_options(config)
    config_sub = config.add_subparsers(dest="config_command")
    restart_policy = config_sub.add_parser(
        "restart-policy",
        help="choose automatic restarts or notify-only behavior",
    )
    restart_policy.add_argument(
        "policy", nargs="?", choices=("automatic", "notify", "toggle")
    )
    _output_options(restart_policy, nested=True)

    zed = commands.add_parser(
        "zed", help="inspect or configure the authored Zed theme override"
    )
    zed_sub = zed.add_subparsers(dest="zed_command", required=True)
    zed_status = zed_sub.add_parser(
        "status", help="show authored-theme and Omazed fallback diagnostics"
    )
    _output_options(zed_status)
    zed_setup = zed_sub.add_parser(
        "setup", help="select THPM Current with a one-time settings backup"
    )
    zed_setup.add_argument("--yes", action="store_true")
    _output_options(zed_setup)

    update = commands.add_parser("update")
    _output_options(update)
    update_sub = update.add_subparsers(dest="update_command")
    check = update_sub.add_parser("check")
    check.add_argument("--force", action="store_true")
    _output_options(check, nested=True)
    _output_options(update_sub.add_parser("status"), nested=True)
    update_apply = update_sub.add_parser("apply")
    update_apply.add_argument(
        "--terminal",
        action="store_true",
        help="open a terminal when package-manager authorization is required",
    )
    update_apply.add_argument("--inline", action="store_true", help=argparse.SUPPRESS)
    _output_options(update_apply, nested=True)
    return root


def _hook_event_writer(command: str) -> Callable[[dict[str, object]], None] | None:
    event_file = os.environ.get("THPM_HOOK_EVENTS")
    if command != "hook-run" or not event_file:
        return None
    path = Path(event_file)

    def emit(event: dict[str, object]) -> None:
        try:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, separators=(",", ":")) + "\n")
        except OSError:
            pass

    return emit


def _human(payload: dict[str, object]) -> None:
    print(payload.get("summary", ""))
    if payload.get("plugins"):
        for item in payload["plugins"]:
            marker = "on" if item["enabled"] else "off"
            print(f"{marker:>3}  {item['id']:<22} {item['ownership']}")
    for result in payload.get("results", []):
        detail = result.get("message", "")
        print(f"{result['status']:>9}  {result['id']:<22} {detail}")
    for warning in payload.get("warnings", []):
        owner = f"{warning.get('plugin')}: " if warning.get("plugin") else ""
        print(f"warning: {owner}{warning['message']}", file=sys.stderr)
    for error in payload.get("errors", []):
        owner = f"{error.get('plugin')}: " if error.get("plugin") else ""
        print(f"error: {owner}{error['message']}", file=sys.stderr)


def _confirm(message: str, activity: Activity | None = None) -> bool:
    try:
        if activity is not None:
            with activity.suspend():
                answer = input(message)
        else:
            answer = input(message)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def _set_enabled(
    service: Service,
    args: argparse.Namespace,
    value: bool,
    json_mode: bool,
    activity: Activity | None = None,
) -> dict[str, object]:
    payload = service.set_enabled(args.plugin, value, confirmed=bool(args.yes))
    if (
        payload.get("confirmationRequired")
        and not json_mode
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        if _confirm(
            f"Enable {args.plugin}? This integration changes application configuration. [y/N] ",
            activity,
        ):
            payload = service.set_enabled(args.plugin, value, confirmed=True)
    return payload


def _zed_setup(
    service: Service,
    args: argparse.Namespace,
    json_mode: bool,
    activity: Activity | None = None,
) -> dict[str, object]:
    payload = service.zed_setup(confirmed=bool(args.yes))
    if (
        payload.get("confirmationRequired")
        and not json_mode
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        if _confirm(
            "Configure Zed to use THPM Current and back up its settings? [y/N] ",
            activity,
        ):
            payload = service.zed_setup(confirmed=True)
    return payload


def _doctor(
    service: Service,
    args: argparse.Namespace,
    json_mode: bool,
    activity: Activity | None,
) -> dict[str, object]:
    payload = service.doctor(
        args.plugin,
        fix=bool(args.fix),
        confirmed=bool(args.yes),
    )
    if (
        payload.get("confirmationRequired")
        and not json_mode
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and _confirm(
            "Repair Cava's managed theme selection and output? [y/N] ",
            activity,
        )
    ):
        payload = service.doctor(args.plugin, fix=True, confirmed=True)
    return payload


def _execute(
    service: Service,
    paths: Paths,
    command: str,
    args: argparse.Namespace,
    json_mode: bool,
    activity: Activity | None = None,
) -> dict[str, object] | None:
    if command in {"list", "status", "native-status"}: return service.state()
    if command == "version": return envelope("version", summary=f"thpm {__version__}", version=__version__, errors=[])
    if command == "enable": return _set_enabled(service, args, True, json_mode, activity)
    if command == "disable": return _set_enabled(service, args, False, json_mode, activity)
    if command == "plugin": return _set_enabled(service, args, args.plugin_command == "enable", json_mode, activity)
    if command == "doctor": return _doctor(service, args, json_mode, activity)
    if command == "report":
        output = args.output.expanduser() if args.output else None
        return service.support_report(args.plugin, output=output)
    if command == "reconcile": return service.reconcile(args.refresh, defer_upgrade_refresh=args.defer_upgrade_refresh)
    if command == "run": return service.run_theme()
    if command == "install": return service.install_check() if args.install_check else service.install(not args.no_ui)
    if command == "uninstall": return service.uninstall()
    if command == "migrate": return service.migrate()
    if command == "tui":
        if json_mode:
            return envelope(
                "tui",
                False,
                summary="the interactive TUI cannot run with --json",
                errors=[{"message": "remove --json to open the TUI"}],
            )
        from .tui import run_tui
        run_tui(service=service, paths=paths)
        return None
    if command == "hook-run": return service.hook_run(args.event, args.event_args)
    if command == "config":
        if args.config_command == "restart-policy":
            return service.restart_policy(args.policy)
        return service.preferences()
    if command == "zed":
        return service.zed_status() if args.zed_command == "status" else _zed_setup(service, args, json_mode, activity)
    if command == "update":
        if args.update_command in {None, "apply"}:
            if bool(getattr(args, "terminal", False)):
                update_mode = "handoff"
            elif bool(getattr(args, "inline", False)) and not json_mode:
                update_mode = "inline"
            elif not json_mode:
                update_mode = "inline" if sys.stdin.isatty() else "handoff"
            else:
                update_mode = "deny"
            return service.update_apply(update_mode=update_mode)
        return service.update_check(args.update_command == "check" and args.force)
    if command == "ui":
        if args.ui_command == "state": return service.state()
        if args.ui_command == "install": return envelope("ui-install", summary="QML manager installed", result=ui.install(paths), errors=[])
        if args.ui_command == "sync":
            result = ui.sync(paths)
            return envelope(
                "ui-sync",
                summary="QML manager synchronized" if not result.get("skipped") else "QML manager is not installed",
                result=result,
                errors=[],
            )
        if args.ui_command == "remove": return envelope("ui-remove", summary="QML manager removed", result=ui.remove(paths), errors=[])
        if args.ui_command == "status": return envelope("ui-status", summary="QML manager status", result=ui.status(paths), errors=[])
        if args.ui_command == "surface": return service.ui_surface(args.surface)
        result = ui.open_manager(paths, fallback=not json_mode)
        degraded = result.get("surface") == "recovery-tui"
        return envelope(
            "ui-open",
            summary=(
                "Recovery interface opened because the graphical manager was unavailable"
                if degraded
                else "QML manager opened"
            ),
            result=result,
            errors=[],
        )
    raise ValueError(command)


def _write_update_handoff_result(
    paths: Paths, payload: dict[str, object]
) -> None:
    requested = os.environ.get("THPM_UPDATE_RESULT_FILE")
    if not requested:
        return
    target = Path(requested)
    try:
        parent = target.parent.resolve()
        runtime_dir = paths.runtime_dir.resolve()
    except OSError:
        return
    if (
        parent != runtime_dir
        or not target.name.startswith("thpm-update-result-")
        or target.suffix != ".json"
    ):
        return
    atomic_text(target, json.dumps(payload, separators=(",", ":")) + "\n", 0o600)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    argument_parser = parser()
    _json_parse_errors(argument_parser, "--json" in raw_args)
    args = argument_parser.parse_args(raw_args)
    paths = Paths.discover()
    command = args.command or "list"
    json_mode = args.global_json or getattr(args, "json", False)
    quiet = bool(args.global_quiet or getattr(args, "quiet", False))
    verbose = bool(
        (args.global_verbose or getattr(args, "verbose", False)) and not quiet
    )
    activity_name = None if json_mode else operation_name(command, args)
    activity = (
        Activity(activity_name, verbose=verbose, quiet=quiet)
        if activity_name
        else None
    )
    service = Service(
        paths=paths,
        progress=reporter(activity),
        events=_hook_event_writer(command),
    )
    started_ns = time.monotonic_ns()
    try:
        if activity is not None:
            with activity:
                payload = _execute(service, paths, command, args, json_mode, activity)
                activity.finish(payload is None or bool(payload.get("ok")))
        else:
            payload = _execute(service, paths, command, args, json_mode)
        if payload is None:
            return 0
    except RuntimeError as exc:
        payload = envelope(command, False, summary=str(exc), busy="already running" in str(exc), errors=[{"message": str(exc)}])
    except Exception as exc:
        payload = envelope(command, False, summary=str(exc), errors=[{"message": str(exc)}])
    payload.setdefault(
        "durationMs", max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
    )
    if command == "update":
        _write_update_handoff_result(paths, payload)
    if json_mode:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        render(payload, verbose=verbose)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
