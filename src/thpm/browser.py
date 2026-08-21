from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

ZEN_LABEL = "Zen Browser"
ZEN_CLASSES = frozenset({"zen"})
ZEN_EXECUTABLES = frozenset({"zen", "zen-bin", "zen-browser"})
ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
LOCK_PID = re.compile(r":\+(\d+)$")
SHUTDOWN_TIMEOUT = 20.0
STARTUP_TIMEOUT = 20.0
POLL_INTERVAL = 0.2


@dataclass(frozen=True)
class ZenProcess:
    pid: int
    start_time: int
    executable: Path
    command: tuple[str, ...]


@dataclass(frozen=True)
class ZenRestartPlan:
    process: ZenProcess
    profile: Path
    addresses: tuple[str, ...]
    hyprctl: str
    systemd_run: str
    uwsm_app: str


@dataclass
class ZenRestartResult:
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    restart_required: list[str] = field(default_factory=list)


class ZenRestartError(RuntimeError):
    def __init__(self, message: str, *, actions: list[str] | None = None):
        super().__init__(message)
        self.actions = actions or []
        self.warnings = [
            "Zen may have partially closed; reopen recently closed windows if needed"
        ]
        self.restart_required = [ZEN_LABEL]


def _lock_owner(profile: Path) -> int | None:
    lock = profile / "lock"
    if not lock.is_symlink():
        return None
    try:
        target = os.readlink(lock)
    except OSError:
        return None
    matched = LOCK_PID.search(target)
    return int(matched.group(1)) if matched else None


def _process(pid: int, proc_root: Path = Path("/proc")) -> ZenProcess | None:
    process_dir = proc_root / str(pid)
    try:
        if process_dir.stat().st_uid != os.getuid():
            return None
        executable = (process_dir / "exe").resolve(strict=True)
        command = tuple(
            part.decode("utf-8", errors="surrogateescape")
            for part in (process_dir / "cmdline").read_bytes().split(b"\0")
            if part
        )
        stat_fields = (process_dir / "stat").read_text().rsplit(") ", 1)[1].split()
        start_time = int(stat_fields[19])
    except (OSError, ValueError, IndexError):
        return None
    if executable.name not in ZEN_EXECUTABLES or not os.access(executable, os.X_OK):
        return None
    if not command or "-contentproc" in command:
        return None
    return ZenProcess(pid, start_time, executable, command)


def _profile_command_is_safe(process: ZenProcess, profile: Path) -> bool:
    arguments = process.command[1:]
    return not arguments or arguments == ("--profile", str(profile))


def _clients(hyprctl: str) -> list[dict[str, object]]:
    try:
        completed = subprocess.run(
            [hyprctl, "-j", "clients"],
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not inspect Hyprland windows: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or "Hyprland window inspection failed")
    try:
        clients = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError("Hyprland returned invalid window data") from exc
    if not isinstance(clients, list) or not all(
        isinstance(client, dict) for client in clients
    ):
        raise RuntimeError("Hyprland returned invalid window data")
    return clients


def _zen_windows(clients: list[dict[str, object]]) -> list[tuple[int, str]]:
    windows: list[tuple[int, str]] = []
    for client in clients:
        if client.get("class") not in ZEN_CLASSES and client.get(
            "initialClass"
        ) not in ZEN_CLASSES:
            continue
        pid = client.get("pid")
        address = client.get("address")
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or not isinstance(address, str)
            or not ADDRESS.fullmatch(address)
        ):
            raise RuntimeError("Zen window identity is invalid")
        windows.append((pid, address))
    return windows


def _other_active_profile_pids(base: Path, profile: Path) -> set[int]:
    active: set[int] = set()
    try:
        candidates = list(base.iterdir())
    except OSError:
        return active
    for candidate in candidates:
        if candidate == profile or not candidate.is_dir():
            continue
        pid = _lock_owner(candidate)
        if pid is not None and _process(pid) is not None:
            active.add(pid)
    return active


def _discover(base: Path, profile: Path) -> tuple[str, ZenRestartPlan | None, str]:
    hyprctl = shutil.which("hyprctl")
    if not hyprctl or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "ambiguous", None, "Hyprland is unavailable for a safe Zen restart"
    try:
        windows = _zen_windows(_clients(hyprctl))
    except RuntimeError as exc:
        return "ambiguous", None, str(exc)

    pid = _lock_owner(profile)
    if pid is None:
        if windows:
            return "ambiguous", None, "Zen is running without a verifiable profile lock"
        return "closed", None, ""
    process = _process(pid)
    if process is None:
        return "ambiguous", None, "Zen profile ownership could not be verified"
    if not _profile_command_is_safe(process, profile):
        return "ambiguous", None, "Zen was launched with unsupported arguments"
    if _other_active_profile_pids(base, profile) - {pid}:
        return "ambiguous", None, "multiple Zen profiles are active"
    if not windows:
        return "ambiguous", None, "Zen has no verifiable Hyprland window"
    if any(window_pid != pid for window_pid, _address in windows):
        return "ambiguous", None, "Zen windows belong to multiple processes"

    systemd_run = shutil.which("systemd-run")
    uwsm_app = shutil.which("uwsm-app")
    if not systemd_run or not uwsm_app:
        return "ambiguous", None, "Omarchy's detached application launcher is unavailable"
    addresses = tuple(address for _window_pid, address in windows)
    return (
        "running",
        ZenRestartPlan(
            process,
            profile,
            addresses,
            hyprctl,
            systemd_run,
            uwsm_app,
        ),
        "",
    )


def _same_plan(expected: ZenRestartPlan, current: ZenRestartPlan | None) -> bool:
    return bool(
        current
        and current.process.pid == expected.process.pid
        and current.process.start_time == expected.process.start_time
        and current.process.executable == expected.process.executable
        and current.profile == expected.profile
        and current.addresses == expected.addresses
    )


def _close_windows(plan: ZenRestartPlan) -> None:
    selectors = ",".join(f'"address:{address}"' for address in plan.addresses)
    expected = ",".join(f'["{address}"]=true' for address in plan.addresses)
    script = (
        f"local selectors = {{{selectors}}}; local expected = {{{expected}}}; "
        "local targets = {}; "
        "for _, selector in ipairs(selectors) do "
        "local window = hl.get_window(selector); "
        f"if not window or window.pid ~= {plan.process.pid} or "
        "(window.class ~= 'zen' and window.initial_class ~= 'zen') then "
        "error('Zen window changed before restart') end; "
        "targets[#targets + 1] = window; end; "
        "local count = 0; for _, window in ipairs(hl.get_windows()) do "
        "if window.class == 'zen' or window.initial_class == 'zen' then "
        f"if window.pid ~= {plan.process.pid} or not expected[window.address] then "
        "error('Zen window set changed before restart') end; "
        "count = count + 1; end; end; "
        "if count ~= #targets then error('Zen window set changed before restart') end; "
        "for _, window in ipairs(targets) do "
        "hl.dispatch(hl.dsp.window.close({window=window})); end; return true"
    )
    try:
        completed = subprocess.run(
            [plan.hyprctl, "eval", script],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ZenRestartError(f"could not close Zen safely: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ZenRestartError(detail or "could not close Zen safely")


def _process_exited(pid: int, proc_root: Path = Path("/proc")) -> bool:
    try:
        (proc_root / str(pid)).stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _shut_down(plan: ZenRestartPlan) -> bool:
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT
    while time.monotonic() < deadline:
        lock_released = _lock_owner(plan.profile) != plan.process.pid
        process_exited = _process_exited(plan.process.pid)
        try:
            original_windows_gone = not any(
                address in plan.addresses
                for _pid, address in _zen_windows(_clients(plan.hyprctl))
            )
        except RuntimeError:
            original_windows_gone = False
        if lock_released and process_exited and original_windows_gone:
            return True
        time.sleep(POLL_INTERVAL)
    return False


def _launch(plan: ZenRestartPlan) -> None:
    unit = f"thpm-zen-restart-{os.getpid()}-{time.monotonic_ns()}"
    command = [
        plan.systemd_run,
        "--user",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "--property=StandardOutput=null",
        "--property=StandardError=null",
        "--",
        plan.uwsm_app,
        "--",
        str(plan.process.executable),
        "--profile",
        str(plan.profile),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ZenRestartError(
            f"Zen closed but could not be relaunched: {exc}",
            actions=["Zen Browser closed"],
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ZenRestartError(
            detail or "Zen closed but could not be relaunched",
            actions=["Zen Browser closed"],
        )


def _started(
    base: Path, profile: Path, previous_pid: int, expected_windows: int
) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        state, plan, _warning = _discover(base, profile)
        if (
            state == "running"
            and plan
            and plan.process.pid != previous_pid
            and len(plan.addresses) == expected_windows
        ):
            return True
        time.sleep(POLL_INTERVAL)
    return False


def restart_zen(base: Path, profile: Path, *, automatic: bool) -> ZenRestartResult:
    state, plan, warning = _discover(base, profile)
    if state == "closed":
        return ZenRestartResult()
    if state != "running" or plan is None:
        return ZenRestartResult(warnings=[warning], restart_required=[ZEN_LABEL])
    if not automatic:
        return ZenRestartResult(restart_required=[ZEN_LABEL])

    current_state, current, current_warning = _discover(base, profile)
    if current_state != "running" or not _same_plan(plan, current):
        return ZenRestartResult(
            warnings=[current_warning or "Zen changed during restart validation"],
            restart_required=[ZEN_LABEL],
        )

    _close_windows(plan)
    actions = [f"Zen Browser close requested for {len(plan.addresses)} window(s)"]
    if not _shut_down(plan):
        raise ZenRestartError(
            "Zen did not finish closing; it was not relaunched",
            actions=actions,
        )
    _launch(plan)
    if not _started(base, profile, plan.process.pid, len(plan.addresses)):
        raise ZenRestartError(
            "Zen relaunch or window restoration could not be verified; it may still be starting",
            actions=[*actions, "Zen Browser relaunch requested"],
        )
    actions.append("Zen Browser relaunched")
    return ZenRestartResult(actions=actions)
