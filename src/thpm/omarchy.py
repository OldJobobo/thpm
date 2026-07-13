from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

REQUIRED_ROUTES = {"omarchy hook", "omarchy hook install", "omarchy theme refresh", "omarchy shell", "omarchy plugin", "omarchy menu"}


@dataclass(frozen=True)
class Capabilities:
    available: bool
    routes: frozenset[str]
    missing: tuple[str, ...]


def run(*args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["omarchy", *args], text=True, capture_output=True, check=check, timeout=timeout)


def capabilities() -> Capabilities:
    if not shutil.which("omarchy"):
        return Capabilities(False, frozenset(), tuple(sorted(REQUIRED_ROUTES)))
    try:
        payload = json.loads(run("commands", "--json").stdout)
        routes = frozenset(item["route"] for item in payload.get("commands", []) if "route" in item)
    except (OSError, ValueError, subprocess.SubprocessError):
        return Capabilities(False, frozenset(), tuple(sorted(REQUIRED_ROUTES)))
    missing = tuple(sorted(REQUIRED_ROUTES - routes))
    return Capabilities(not missing, routes, missing)


def shell_running() -> bool:
    try:
        return run("shell", "shell", "ping", check=False, timeout=3).returncode == 0
    except subprocess.SubprocessError:
        return False
