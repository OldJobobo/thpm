from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

_STAGE_TOTALS = {
    "install": 6,
    "reconcile": 4,
    "run": 2,
    "update": 8,
    "enable": 3,
    "disable": 3,
    "migrate": 4,
    "uninstall": 4,
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
}

_STATUS_STYLES = {
    "applied": "bold green",
    "unchanged": "cyan",
    "skipped": "yellow",
    "failed": "bold red",
}


class Activity:
    """TTY-aware progress surface used by synchronous service operations."""

    def __init__(self, operation: str, *, verbose: bool = False, console: Console | None = None):
        self.operation = operation
        self.verbose = verbose
        self.console = console or Console(no_color=bool(os.environ.get("NO_COLOR")))
        self.enabled = self.console.is_terminal and os.environ.get("TERM") != "dumb"
        self._progress: Progress | None = None
        self._task: int | None = None
        self._steps = 0
        self._last_message = _LABELS.get(operation, operation.replace("-", " ").title())

    def __enter__(self) -> Activity:
        if self.enabled:
            self._progress = Progress(
                SpinnerColumn(style="bold magenta"),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=28, style="grey35", complete_style="magenta", finished_style="green"),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=self.console,
                transient=True,
                refresh_per_second=12,
            )
            self._progress.start()
            self._task = self._progress.add_task(self._last_message, total=_STAGE_TOTALS.get(self.operation, 4))
        elif self.verbose:
            self.console.print(f"[cyan]→[/] {self._last_message}")
        return self

    def __call__(self, message: str, detail: str | None = None) -> None:
        self.step(message, detail)

    def step(self, message: str, detail: str | None = None) -> None:
        self._last_message = message
        self._steps += 1
        if self._progress is not None and self._task is not None:
            total = int(self._progress.tasks[self._task].total or self._steps + 1)
            completed = min(max(self._steps - 1, 0), max(total - 1, 0))
            self._progress.update(self._task, description=message, completed=completed)
            self._progress.refresh()
        elif self.verbose:
            suffix = f" [dim]{detail}[/]" if detail else ""
            self.console.print(f"  [cyan]•[/] {message}{suffix}")

    def set_total(self, total: int) -> None:
        """Adjust the stage count once an operation selects its execution path."""
        if total < 1:
            raise ValueError("progress total must be positive")
        if self._progress is not None and self._task is not None:
            completed = min(max(self._steps - 1, 0), max(total - 1, 0))
            self._progress.update(self._task, total=total, completed=completed)
            self._progress.refresh()

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

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self._progress is not None and self._task is not None:
            task = self._progress.tasks[self._task]
            self._progress.update(self._task, completed=task.total, description=self._last_message)
            self._progress.refresh()
            self._progress.stop()


def operation_name(command: str, args: Any) -> str | None:
    if command == "plugin":
        return str(args.plugin_command)
    if command in {"enable", "disable", "install", "uninstall", "migrate", "reconcile", "run"}:
        return command
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

    results = payload.get("results")
    if isinstance(results, list) and results:
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
        table.add_column("Owner", style="dim")
        for item in plugins:
            if not isinstance(item, dict):
                continue
            enabled = bool(item.get("enabled"))
            table.add_row(Text("●" if enabled else "○", style="green" if enabled else "grey50"), str(item.get("id", "")), str(item.get("ownership", "")))
        console.print(table)

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
    console.print(Panel.fit(f"[{style} bold]{icon}[/] [bold]{summary}[/]", border_style=style, padding=(0, 1)))
    _print_details(console, payload, verbose=verbose)


def reporter(activity: Activity | None) -> Callable[[str, str | None], None] | None:
    return activity
