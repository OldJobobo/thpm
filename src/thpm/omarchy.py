from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_ROUTES = {"omarchy hook", "omarchy hook install", "omarchy theme refresh", "omarchy shell", "omarchy plugin", "omarchy menu"}


@dataclass(frozen=True)
class Capabilities:
    available: bool
    routes: frozenset[str]
    missing: tuple[str, ...]


def _read_events(
    path: Path,
    offset: int,
    pending: str,
    handler: Callable[[dict[str, Any]], None],
    *,
    final: bool = False,
) -> tuple[int, str]:
    try:
        with path.open(encoding="utf-8") as stream:
            stream.seek(offset)
            pending += stream.read()
            offset = stream.tell()
    except OSError:
        return offset, pending

    lines = pending.split("\n")
    pending = lines.pop()
    if final and pending.strip():
        lines.append(pending)
        pending = ""
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            try:
                handler(event)
            except Exception:
                # Progress is best-effort; the final hook report stays authoritative.
                continue
    return offset, pending


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        if process.poll() is None:
            process.wait()
        return

    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)

    try:
        # The group can outlive its leader when a hook descendant ignores TERM.
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()


def run(
    *args: str,
    check: bool = True,
    timeout: int = 30,
    env: Mapping[str, str] | None = None,
    event_path: Path | None = None,
    event_handler: Callable[[dict[str, Any]], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["omarchy", *args]
    if event_path is None or event_handler is None:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=check,
            timeout=timeout,
            env=env,
        )

    offset = 0
    pending = ""
    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                offset, pending = _read_events(
                    event_path, offset, pending, event_handler
                )
                if time.monotonic() - started >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(0.05)
            offset, pending = _read_events(
                event_path, offset, pending, event_handler, final=True
            )
        finally:
            _terminate_process_group(process)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()

    completed = subprocess.CompletedProcess(
        command, process.returncode, stdout, stderr
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=stdout,
            stderr=stderr,
        )
    return completed


def capabilities() -> Capabilities:
    if not shutil.which("omarchy"):
        return Capabilities(False, frozenset(), tuple(sorted(REQUIRED_ROUTES)))
    try:
        payload = json.loads(run("commands", "--json").stdout)
        routes = frozenset(
            item["route"] for item in payload.get("commands", []) if "route" in item
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return Capabilities(False, frozenset(), tuple(sorted(REQUIRED_ROUTES)))

    # Omarchy's command inventory may omit a command-group route while listing
    # its actionable children (for example, `omarchy plugin add` without an
    # `omarchy plugin` record). A group is available when either representation
    # is present.
    missing = tuple(
        sorted(
            required
            for required in REQUIRED_ROUTES
            if required not in routes
            and not any(route.startswith(required + " ") for route in routes)
        )
    )
    return Capabilities(not missing, routes, missing)


def shell_running() -> bool:
    try:
        return run("shell", "shell", "ping", check=False, timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
