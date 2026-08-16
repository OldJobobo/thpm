from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

_STAGE_TOTALS = {
    "reconcile": 4,
    "enable": 3,
    "disable": 3,
    "migrate": 3,
    "uninstall": 4,
    "zed-setup": 3,
}

_LABELS = {
    "install": "Installing THPM",
    "reconcile": "Synchronizing integrations",
    "run": "Refreshing active theme",
    "update": "Updating THPM",
    "enable": "Enabling integration",
    "disable": "Disabling integration",
    "migrate": "Migrating configuration",
    "uninstall": "Removing THPM integrations",
    "zed-setup": "Configuring Zed",
}

_STATUS_STYLES = {
    "applied": "bold green",
    "unchanged": "cyan",
    "skipped": "yellow",
    "failed": "bold red",
}


class Activity:
    """TTY-aware progress surface used by synchronous service operations."""

    def __init__(
        self,
        operation: str,
        *,
        verbose: bool = False,
        quiet: bool = False,
        console: Console | None = None,
    ):
        self.operation = operation
        self.verbose = verbose
        self.quiet = quiet
        self.console = console or Console(
            stderr=True, no_color=bool(os.environ.get("NO_COLOR"))
        )
        self.enabled = (
            not quiet
            and self.console.is_terminal
            and os.environ.get("TERM") != "dumb"
        )
        self._progress: Progress | None = None
        self._task: int | None = None
        self._steps = 0
        self._last_message = _LABELS.get(operation, operation.replace("-", " ").title())
        self._successful: bool | None = None

    def __enter__(self) -> Activity:
        if self.enabled:
            self._progress = Progress(
                SpinnerColumn(style="bold magenta"),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(
                    bar_width=28,
                    style="grey35",
                    complete_style="magenta",
                    finished_style="green",
                ),
                MofNCompleteColumn(),
                console=self.console,
                transient=True,
                refresh_per_second=12,
            )
            self._progress.start()
            self._task = self._progress.add_task(
                self._last_message, total=_STAGE_TOTALS.get(self.operation)
            )
        elif not self.quiet:
            self.console.print(f"[cyan]→[/] {self._last_message}")
        return self

    def __call__(self, message: str, detail: str | None = None) -> None:
        self.step(message, detail)

    def step(self, message: str, detail: str | None = None) -> None:
        self._last_message = message
        self._steps += 1
        if self._progress is not None and self._task is not None:
            task = self._progress.tasks[self._task]
            total = int(task.total) if task.total is not None else None
            completed = (
                min(max(self._steps - 1, 0), max(total - 1, 0))
                if total is not None
                else self._steps - 1
            )
            if self.verbose:
                suffix = f" [dim]{detail}[/]" if detail else ""
                self._progress.console.print(f"  [cyan]→[/] {message}{suffix}")
            self._progress.update(
                self._task, description=message, completed=completed
            )
            self._progress.refresh()
        elif not self.quiet:
            suffix = f" [dim]{detail}[/]" if detail else ""
            self.console.print(f"  [cyan]→[/] {message}{suffix}")

    def set_total(self, total: int) -> None:
        """Adjust the stage count once an operation selects its execution path."""
        if total < 1:
            raise ValueError("progress total must be positive")
        if self._progress is not None and self._task is not None:
            completed = min(max(self._steps - 1, 0), max(total - 1, 0))
            self._progress.update(self._task, total=total, completed=completed)
            self._progress.refresh()

    def event(self, event: dict[str, object]) -> None:
        """Render structured hook events without coupling adapters to Rich."""
        event_type = str(event.get("type", ""))
        total = int(event.get("total", 0) or 0)
        current = int(event.get("current", 0) or 0)
        plugin = str(event.get("plugin", ""))

        if event_type == "integrations_started":
            message = (
                f"Applying {total} integration{'s' if total != 1 else ''}"
                if total
                else "No enabled integrations to apply"
            )
            self._last_message = message
            if self._progress is not None and self._task is not None:
                self._progress.update(
                    self._task,
                    description=message,
                    total=total,
                    completed=0,
                )
                self._progress.refresh()
            elif not self.quiet:
                self.console.print(f"  [cyan]→[/] {message}")
            return

        if event_type == "integration_started":
            message = f"Applying integrations {current}/{total} — {plugin}"
            self._last_message = message
            if self._progress is not None and self._task is not None:
                self._progress.update(
                    self._task,
                    description=message,
                    total=max(total, 1),
                    completed=max(current - 1, 0),
                )
                self._progress.refresh()
            elif not self.quiet:
                self.console.print(
                    f"  [cyan]→[/] [{current}/{total}] [bold]{plugin}[/]"
                )
            return

        if event_type == "integration_finished":
            status = str(event.get("status", ""))
            message = str(event.get("message", ""))
            self._last_message = f"{plugin}: {status}"
            connector = "└─" if current == total else "├─"
            icon = {
                "applied": "✓",
                "unchanged": "•",
                "skipped": "!",
                "failed": "✗",
            }.get(status, "•")
            style = _STATUS_STYLES.get(status, "white")
            detail = f" [dim]— {message}[/]" if self.verbose and message else ""
            outcome = (
                f"  [dim]{connector}[/] [{style}]{icon}[/] "
                f"[bold]{plugin:<20}[/] [{style}]{status}[/]{detail}"
            )
            if self._progress is not None and self._task is not None:
                self._progress.update(
                    self._task,
                    description=self._last_message,
                    total=max(total, 1),
                    completed=current,
                )
                self._progress.console.print(outcome)
                self._progress.refresh()
            elif not self.quiet:
                self.console.print(outcome)

    @contextmanager
    def suspend(self) -> Iterator[None]:
        """Yield terminal ownership without a Rich live display obscuring prompts."""
        active = self._progress is not None and self._task is not None
        if active:
            self._progress.stop()
        try:
            yield
        finally:
            if active:
                self._progress.start()

    def finish(self, successful: bool) -> None:
        self._successful = successful

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self._progress is not None and self._task is not None:
            if _type is None and self._successful is not False:
                task = self._progress.tasks[self._task]
                total = task.total if task.total is not None else 1
                self._progress.update(
                    self._task,
                    total=total,
                    completed=total,
                    description=self._last_message,
                )
                self._progress.refresh()
            self._progress.stop()


def operation_name(command: str, args: Any) -> str | None:
    if command == "plugin":
        return str(args.plugin_command)
    if command == "hook-run" and getattr(args, "event", None) == "theme-set":
        return "run"
    if command == "install" and getattr(args, "install_check", False):
        return None
    if command in {"enable", "disable", "install", "uninstall", "migrate", "reconcile", "run"}:
        return command
    if command == "zed" and getattr(args, "zed_command", None) == "setup":
        return "zed-setup"
    if command == "update" and getattr(args, "update_command", None) not in {"check", "status"}:
        return "update"
    return None


def _owner_prefix(item: dict[str, Any]) -> str:
    owner = item.get("plugin")
    return f"{owner}: " if owner else ""


def _print_details(console: Console, payload: dict[str, Any], *, verbose: bool) -> None:
    result = payload.get("result")
    if isinstance(result, dict):
        current = result.get("currentVersion") or result.get("installedVersion")
        available = result.get("availableVersion")
        origin = result.get("origin")
        if current or available or origin:
            details = []
            if current:
                details.append(f"installed [bold]{current}[/]")
            if available:
                details.append(f"available [bold magenta]{available}[/]")
            if origin:
                details.append(f"source [cyan]{origin}[/]")
            console.print("  " + "  •  ".join(details))
        command = result.get("command") or result.get("refreshCommand")
        if command:
            console.print(f"  [yellow]Next:[/] [bold]{command}[/]")
        if payload.get("operation") in {"zed-status", "zed-setup"}:
            omazed = result.get("omazed") if isinstance(result.get("omazed"), dict) else {}
            rows = (
                ("Source", result.get("source") or "none"),
                ("Target", result.get("target") or "unknown"),
                ("Synchronized", "yes" if result.get("synchronized") else "no"),
                ("Selected", result.get("selectedTheme") or "none"),
                ("Omazed", "available" if omazed.get("command") or omazed.get("outputExists") else "unavailable"),
            )
            table = Table(show_header=False, box=None, pad_edge=False)
            table.add_column("Field", style="bold cyan")
            table.add_column("Value")
            for label, value in rows:
                table.add_row(label, str(value))
            console.print(table)

    results = payload.get("results")
    if (
        verbose
        and not payload.get("progressReported")
        and isinstance(results, list)
        and results
    ):
        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Status", width=10)
        table.add_column("Integration", style="bold")
        table.add_column("Detail")
        for item in results:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", ""))
            table.add_row(Text(status, style=_STATUS_STYLES.get(status, "white")), str(item.get("id", "")), str(item.get("message", "")))
        console.print(table)

    plugins = payload.get("plugins")
    if isinstance(plugins, list) and plugins and payload.get("operation") in {"ui-state", "doctor"}:
        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("", width=2)
        table.add_column("Integration", style="bold")
        table.add_column("Status")
        table.add_column("Owner", style="dim")
        for item in plugins:
            if not isinstance(item, dict):
                continue
            enabled = bool(item.get("enabled"))
            table.add_row(
                Text("●" if enabled else "○", style="green" if enabled else "grey50"),
                str(item.get("id", "")),
                str(item.get("supportStatus", "")),
                str(item.get("ownership", "")),
            )
        console.print(table)

    checks = payload.get("checks")
    if isinstance(checks, list) and checks and payload.get("operation") == "doctor":
        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Status", width=8)
        table.add_column("Check", style="bold")
        table.add_column("Detail")
        check_styles = {
            "pass": "green",
            "warning": "yellow",
            "error": "bold red",
            "unknown": "yellow",
            "skipped": "dim",
        }
        for check in checks:
            if not isinstance(check, dict):
                continue
            status = str(check.get("status", "unknown"))
            table.add_row(
                Text(status, style=check_styles.get(status, "white")),
                str(check.get("id", "")),
                str(check.get("summary", "")),
            )
        console.print(table)
        repair_plan = payload.get("repairPlan")
        repair_available = isinstance(repair_plan, list) and bool(repair_plan)
        if not repair_available:
            repair_available = any(
                isinstance(check, dict)
                and isinstance(check.get("repair"), dict)
                and bool(check["repair"].get("available"))
                for check in checks
            )
        if repair_available:
            console.print("[yellow]Repair available:[/] [bold]thpm doctor cava --fix[/]")

    if payload.get("operation") == "report" and payload.get("reportPath"):
        console.print(
            f"[green]Report:[/] [bold]{payload['reportPath']}[/]", highlight=False
        )
        console.print(
            "[cyan]Next:[/] Share this JSON file with the THPM maintainer."
        )

    restart_required = payload.get("restartRequired")
    if isinstance(restart_required, list) and restart_required:
        names = ", ".join(str(app) for app in restart_required)
        console.print(f"[yellow]↻[/] [bold]Restart needed:[/] {names}")

    for warning in payload.get("warnings", []):
        if isinstance(warning, dict):
            console.print(f"[yellow]⚠[/] {_owner_prefix(warning)}{warning.get('message', '')}")
    for error in payload.get("errors", []):
        if isinstance(error, dict):
            console.print(f"[bold red]✗[/] {_owner_prefix(error)}{error.get('message', '')}")

    if not verbose:
        return
    changed = payload.get("changed")
    if isinstance(changed, list) and changed:
        console.print("\n[bold cyan]Changed files[/]")
        for path in changed:
            console.print(f"  [green]+[/] {path}", highlight=False)
    stdout = payload.get("stdout")
    if isinstance(stdout, str) and stdout.strip():
        console.print("\n[bold cyan]Command output[/]")
        console.print(stdout.rstrip(), style="dim", highlight=False)


def render(payload: dict[str, Any], *, verbose: bool = False, console: Console | None = None) -> None:
    console = console or Console(no_color=bool(os.environ.get("NO_COLOR")))
    ok = bool(payload.get("ok"))
    summary = str(payload.get("summary", "Done"))
    icon = "✓" if ok else "✗"
    style = "green" if ok else "red"
    console.print(f"[{style} bold]{icon}[/] [bold]{summary}[/]")
    _print_details(console, payload, verbose=verbose)


def reporter(activity: Activity | None) -> Callable[[str, str | None], None] | None:
    return activity
