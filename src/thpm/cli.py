from __future__ import annotations

import argparse
import json
import sys

from . import __version__, ui
from .paths import Paths
from .service import Service, envelope


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="thpm", description="Omarchy 4 theme integration manager")
    root.add_argument("--json", action="store_true", dest="global_json")
    root.add_argument("--version", action="version", version=f"thpm {__version__}")
    commands = root.add_subparsers(dest="command")
    for name in ("list", "status", "native-status", "reconcile", "run", "install", "uninstall", "migrate", "version"):
        sub = commands.add_parser(name); sub.add_argument("--json", action="store_true")
        if name == "reconcile": sub.add_argument("--refresh", action="store_true")
        if name == "install": sub.add_argument("--no-ui", action="store_true")
    for name in ("enable", "disable"):
        sub = commands.add_parser(name); sub.add_argument("plugin"); sub.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor"); doctor.add_argument("plugin", nargs="?"); doctor.add_argument("--json", action="store_true")
    hook = commands.add_parser("hook-run"); hook.add_argument("event"); hook.add_argument("event_args", nargs="*"); hook.add_argument("--json", action="store_true")
    plugin = commands.add_parser("plugin"); plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    for name in ("enable", "disable"):
        sub = plugin_sub.add_parser(name); sub.add_argument("plugin"); sub.add_argument("--json", action="store_true")
    ui_cmd = commands.add_parser("ui"); ui_sub = ui_cmd.add_subparsers(dest="ui_command", required=True)
    for name in ("state", "install", "remove", "status", "open"):
        sub = ui_sub.add_parser(name); sub.add_argument("--json", action="store_true")
    update = commands.add_parser("update"); update_sub = update.add_subparsers(dest="update_command", required=True)
    check = update_sub.add_parser("check"); check.add_argument("--force", action="store_true"); check.add_argument("--json", action="store_true")
    status = update_sub.add_parser("status"); status.add_argument("--json", action="store_true")
    apply = update_sub.add_parser("apply"); apply.add_argument("--json", action="store_true")
    return root


def _human(payload: dict[str, object]) -> None:
    print(payload.get("summary", ""))
    if payload.get("plugins"):
        for item in payload["plugins"]:
            marker = "on" if item["enabled"] else "off"
            print(f"{marker:>3}  {item['id']:<22} {item['ownership']}")
    for error in payload.get("errors", []): print(f"error: {error['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    service, paths = Service(), Paths.discover()
    command = args.command or "list"
    try:
        if command in {"list", "status", "native-status"}: payload = service.state()
        elif command == "version": payload = envelope("version", summary=f"thpm {__version__}", version=__version__, errors=[])
        elif command == "enable": payload = service.set_enabled(args.plugin, True)
        elif command == "disable": payload = service.set_enabled(args.plugin, False)
        elif command == "plugin": payload = service.set_enabled(args.plugin, args.plugin_command == "enable")
        elif command == "doctor": payload = service.doctor(args.plugin)
        elif command == "reconcile": payload = service.reconcile(args.refresh)
        elif command == "run": payload = service.run_theme()
        elif command == "install": payload = service.install(not args.no_ui)
        elif command == "uninstall": payload = service.uninstall()
        elif command == "migrate": payload = service.migrate()
        elif command == "hook-run": payload = service.hook_run(args.event_args[0] if args.event_args else "")
        elif command == "update":
            payload = service.update_apply() if args.update_command == "apply" else service.update_check(args.update_command == "check" and args.force)
        elif command == "ui":
            if args.ui_command == "state": payload = service.state()
            elif args.ui_command == "install": payload = envelope("ui-install", summary="QML manager installed", result=ui.install(paths), errors=[])
            elif args.ui_command == "remove": payload = envelope("ui-remove", summary="QML manager removed", result=ui.remove(paths), errors=[])
            elif args.ui_command == "status": payload = envelope("ui-status", summary="QML manager status", result=ui.status(paths), errors=[])
            else:
                from .omarchy import run
                completed = run("shell", "shell", "summon", "io.github.oldjobobo.thpm", "{}", check=False)
                payload = envelope("ui-open", completed.returncode == 0, summary="QML manager opened" if completed.returncode == 0 else "unable to open QML manager", errors=[])
        else: raise ValueError(command)
    except RuntimeError as exc:
        payload = envelope(command, False, summary=str(exc), busy="already running" in str(exc), errors=[{"message": str(exc)}])
    except Exception as exc:
        payload = envelope(command, False, summary=str(exc), errors=[{"message": str(exc)}])
    json_mode = args.global_json or getattr(args, "json", False)
    if json_mode:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        _human(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
