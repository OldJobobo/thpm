from __future__ import annotations

import argparse
import json
import sys

from . import __version__, ui
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


def parser() -> argparse.ArgumentParser:
    root = ThpmArgumentParser(prog="thpm", description="Omarchy 4 theme integration manager")
    root.add_argument("--json", action="store_true", dest="global_json")
    root.add_argument("-v", "--verbose", action="store_true", dest="global_verbose", default=True)
    root.add_argument("-q", "--quiet", action="store_false", dest="global_verbose")
    root.add_argument("--version", action="version", version=f"thpm {__version__}")
    commands = root.add_subparsers(dest="command")
    for name in ("list", "status", "native-status", "reconcile", "run", "install", "uninstall", "migrate", "version", "tui"):
        sub = commands.add_parser(name); sub.add_argument("--json", action="store_true"); sub.add_argument("-v", "--verbose", action="store_true", default=True); sub.add_argument("-q", "--quiet", action="store_false", dest="verbose")
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
        sub = commands.add_parser(name); sub.add_argument("plugin"); sub.add_argument("--yes", action="store_true"); sub.add_argument("--json", action="store_true"); sub.add_argument("-v", "--verbose", action="store_true", default=True); sub.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    doctor = commands.add_parser("doctor"); doctor.add_argument("plugin", nargs="?"); doctor.add_argument("--json", action="store_true"); doctor.add_argument("-v", "--verbose", action="store_true", default=True); doctor.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    hook = commands.add_parser("hook-run"); hook.add_argument("event"); hook.add_argument("event_args", nargs="*"); hook.add_argument("--json", action="store_true"); hook.add_argument("-v", "--verbose", action="store_true", default=True); hook.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    plugin = commands.add_parser("plugin"); plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    for name in ("enable", "disable"):
        sub = plugin_sub.add_parser(name); sub.add_argument("plugin"); sub.add_argument("--yes", action="store_true"); sub.add_argument("--json", action="store_true"); sub.add_argument("-v", "--verbose", action="store_true", default=True); sub.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    ui_cmd = commands.add_parser("ui"); ui_sub = ui_cmd.add_subparsers(dest="ui_command", required=True)
    for name in ("state", "install", "remove", "status", "open"):
        sub = ui_sub.add_parser(name); sub.add_argument("--json", action="store_true"); sub.add_argument("-v", "--verbose", action="store_true", default=True); sub.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    surface = ui_sub.add_parser("surface"); surface.add_argument("surface", nargs="?", choices=("gui", "tui", "toggle")); surface.add_argument("--json", action="store_true"); surface.add_argument("-v", "--verbose", action="store_true", default=True); surface.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    zed = commands.add_parser("zed", help="inspect or configure the authored Zed theme override"); zed_sub = zed.add_subparsers(dest="zed_command", required=True)
    zed_status = zed_sub.add_parser("status", help="show authored-theme and Omazed fallback diagnostics"); zed_status.add_argument("--json", action="store_true"); zed_status.add_argument("-v", "--verbose", action="store_true", default=True); zed_status.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    zed_setup = zed_sub.add_parser("setup", help="select THPM Current with a one-time settings backup"); zed_setup.add_argument("--yes", action="store_true"); zed_setup.add_argument("--json", action="store_true"); zed_setup.add_argument("-v", "--verbose", action="store_true", default=True); zed_setup.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    update = commands.add_parser("update"); update.add_argument("--json", action="store_true"); update.add_argument("-v", "--verbose", action="store_true", default=True); update.add_argument("-q", "--quiet", action="store_false", dest="verbose")
    update_sub = update.add_subparsers(dest="update_command")
    check = update_sub.add_parser("check"); check.add_argument("--force", action="store_true"); check.add_argument("--json", action="store_true", default=argparse.SUPPRESS); check.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS); check.add_argument("-q", "--quiet", action="store_false", dest="verbose", default=argparse.SUPPRESS)
    status = update_sub.add_parser("status"); status.add_argument("--json", action="store_true", default=argparse.SUPPRESS); status.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS); status.add_argument("-q", "--quiet", action="store_false", dest="verbose", default=argparse.SUPPRESS)
    apply = update_sub.add_parser("apply"); apply.add_argument("--json", action="store_true", default=argparse.SUPPRESS); apply.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS); apply.add_argument("-q", "--quiet", action="store_false", dest="verbose", default=argparse.SUPPRESS)
    return root


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
    if command == "doctor": return service.doctor(args.plugin)
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
    if command == "zed":
        return service.zed_status() if args.zed_command == "status" else _zed_setup(service, args, json_mode, activity)
    if command == "update":
        if args.update_command in {None, "apply"}: return service.update_apply(interactive=not json_mode)
        return service.update_check(args.update_command == "check" and args.force)
    if command == "ui":
        if args.ui_command == "state": return service.state()
        if args.ui_command == "install": return envelope("ui-install", summary="QML manager installed", result=ui.install(paths), errors=[])
        if args.ui_command == "remove": return envelope("ui-remove", summary="QML manager removed", result=ui.remove(paths), errors=[])
        if args.ui_command == "status": return envelope("ui-status", summary="QML manager status", result=ui.status(paths), errors=[])
        if args.ui_command == "surface": return service.ui_surface(args.surface)
        from .omarchy import run
        completed = run("shell", "shell", "summon", "io.github.oldjobobo.thpm", "{}", check=False)
        detail = completed.stderr.strip() or completed.stdout.strip()
        return envelope(
            "ui-open",
            completed.returncode == 0,
            summary=(
                "QML manager opened"
                if completed.returncode == 0
                else "unable to open QML manager"
            ),
            errors=[]
            if completed.returncode == 0
            else [{"message": detail or "Omarchy Shell rejected the request"}],
        )
    raise ValueError(command)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    argument_parser = parser()
    _json_parse_errors(argument_parser, "--json" in raw_args)
    args = argument_parser.parse_args(raw_args)
    paths = Paths.discover()
    command = args.command or "list"
    json_mode = args.global_json or getattr(args, "json", False)
    verbose = args.global_verbose and getattr(args, "verbose", True)
    activity_name = None if json_mode else operation_name(command, args)
    activity = Activity(activity_name, verbose=verbose) if activity_name else None
    service = Service(paths=paths, progress=reporter(activity))
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
    if json_mode:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        render(payload, verbose=verbose)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
