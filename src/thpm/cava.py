from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .files import atomic_text
from .paths import Paths

MINIMUM_VERSION = (0, 10, 6)
_SELECTOR_STATE_VERSION = 1
_SECTION_RE = re.compile(r"^[ \t]*\[([^]\r\n]+)\][ \t]*(?:[;#].*)?(?:\r?\n)?$")
_THEME_PREFIX_RE = re.compile(r"^(?P<prefix>[ \t]*theme[ \t]*=[ \t]*)", re.IGNORECASE)
_THEME_LIKE_RE = re.compile(r"^[ \t]*theme(?:[ \t=]|$)", re.IGNORECASE)
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_PIDFD_OPEN = getattr(os, "pidfd_open", None)
_PIDFD_SIGNAL = getattr(signal, "pidfd_send_signal", None)


class CavaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Selector:
    value: str | None
    line: int | None
    color_start: int | None
    color_end: int | None
    original_line: str | None = None
    value_start: int | None = None
    value_end: int | None = None


@dataclass(frozen=True)
class CavaProcess:
    pid: int
    config_path: str | None
    config_home: str | None
    confidence: str
    custom_config: bool
    start_time: str | None = None

    def json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosticCheck:
    id: str
    status: str
    summary: str
    evidence: dict[str, object] = field(default_factory=dict)
    repair: dict[str, object] | None = None

    def json(self) -> dict[str, object]:
        payload = asdict(self)
        if self.repair is None:
            payload.pop("repair")
        return payload


def selector_state_path(paths: Paths) -> Path:
    return paths.managed_asset_state_dir / "cava-selection.json"


def default_config_path(paths: Paths) -> Path:
    return paths.config_home / "cava/config"


def theme_target(paths: Paths) -> Path:
    return paths.config_home / "cava/themes/thpm"


def theme_source(paths: Paths) -> Path | None:
    for name in ("cava_theme", "thpm-cava.ini"):
        candidate = paths.current_theme / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _selector_value(line: str) -> tuple[str, int, int]:
    content = line.rstrip("\r\n")
    prefix = _THEME_PREFIX_RE.match(content)
    if prefix is None:
        raise CavaError("Cava [color] section contains a malformed theme selector")
    position = prefix.end()
    if position >= len(content):
        raise CavaError("Cava theme selector is empty")
    if content[position] in "'\"":
        quote = content[position]
        end = content.find(quote, position + 1)
        if end < 0:
            raise CavaError("Cava theme selector has an unterminated quote")
        value = content[position + 1 : end]
        value_start, value_end = position + 1, end
        remainder = content[end + 1 :]
    else:
        token = re.match(r"[^\s#;='\"]+", content[position:])
        if token is None:
            raise CavaError("Cava theme selector is malformed")
        value = token.group(0)
        value_start, value_end = position, position + len(value)
        remainder = content[value_end:]
    if not value:
        raise CavaError("Cava theme selector is empty")
    stripped = remainder.lstrip(" \t")
    if stripped and not stripped.startswith(("#", ";")):
        raise CavaError("Cava theme selector contains unexpected trailing content")
    return value, value_start, value_end


def parse_selector(text: str) -> Selector:
    lines = text.splitlines(keepends=True)
    sections: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        match = _SECTION_RE.match(line)
        if stripped.startswith("[") and match is None:
            raise CavaError("Cava config contains a malformed section header")
        if match:
            sections.append((index, match.group(1).strip().lower()))
    colors = [index for index, name in sections if name == "color"]
    if len(colors) > 1:
        raise CavaError("Cava config contains duplicate [color] sections")
    if not colors:
        return Selector(None, None, None, None)
    start = colors[0]
    following = [index for index, _name in sections if index > start]
    end = min(following) if following else len(lines)
    matches: list[tuple[int, str, int, int]] = []
    for index in range(start + 1, end):
        if _THEME_LIKE_RE.match(lines[index]):
            value, value_start, value_end = _selector_value(lines[index])
            matches.append((index, value, value_start, value_end))
    if len(matches) > 1:
        raise CavaError("Cava [color] section contains duplicate theme selectors")
    if not matches:
        return Selector(None, None, start, end)
    index, value, value_start, value_end = matches[0]
    return Selector(
        value,
        index,
        start,
        end,
        lines[index],
        value_start,
        value_end,
    )


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def set_selector(text: str, value: str = "thpm") -> tuple[str, dict[str, object]]:
    selector = parse_selector(text)
    lines = text.splitlines(keepends=True)
    state: dict[str, object] = {
        "version": _SELECTOR_STATE_VERSION,
        "installedValue": value,
        "selectorExisted": selector.line is not None,
        "previousLine": selector.original_line or "",
        "createdColorSection": selector.color_start is None,
        "insertedLine": "",
        "predecessorBefore": "",
        "predecessorAfter": "",
        "createdBlock": "",
    }
    if selector.line is not None:
        assert selector.value_start is not None and selector.value_end is not None
        line = lines[selector.line]
        lines[selector.line] = (
            line[: selector.value_start] + value + line[selector.value_end :]
        )
    elif selector.color_start is not None:
        ending = _newline(text)
        insertion = selector.color_end if selector.color_end is not None else len(lines)
        if insertion and lines[insertion - 1] and not lines[insertion - 1].endswith(("\n", "\r")):
            state["predecessorBefore"] = lines[insertion - 1]
            lines[insertion - 1] += ending
            state["predecessorAfter"] = lines[insertion - 1]
        inserted = f"theme = '{value}'{ending}"
        state["insertedLine"] = inserted
        lines.insert(insertion, inserted)
    else:
        ending = _newline(text)
        prefix = ""
        if text and not text.endswith(("\n", "\r")):
            prefix += ending
        if text and any(line.strip() for line in lines):
            prefix += ending
        created = prefix + f"[color]{ending}theme = '{value}'{ending}"
        state["createdBlock"] = created
        return text + created, state
    return "".join(lines), state


def restore_selector_text(text: str, state: dict[str, object]) -> tuple[str, bool]:
    state = validate_selector_state(state, require_paths=False)
    selector = parse_selector(text)
    installed = str(state["installedValue"])
    if selector.value != installed or selector.line is None:
        return text, False
    if bool(state["selectorExisted"]):
        lines = text.splitlines(keepends=True)
        lines[selector.line] = str(state["previousLine"])
        return "".join(lines), True
    created_block = str(state.get("createdBlock", ""))
    if bool(state["createdColorSection"]) and created_block and text.endswith(created_block):
        return text[: -len(created_block)], True
    lines = text.splitlines(keepends=True)
    selector_index = selector.line
    del lines[selector_index]
    predecessor_before = str(state.get("predecessorBefore", ""))
    predecessor_after = str(state.get("predecessorAfter", ""))
    if (
        predecessor_before
        and selector_index > 0
        and lines[selector_index - 1] == predecessor_after
    ):
        lines[selector_index - 1] = predecessor_before
    # If THPM created [color] but the user later added content there, preserve the
    # section and that content; only the THPM selector line is removed.
    return "".join(lines), True


def safe_config_target(paths: Paths, config: Path | None = None) -> Path:
    config = config or default_config_path(paths)
    if config.is_symlink():
        try:
            target = config.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise CavaError(f"Cava config symlink cannot be resolved: {config}") from exc
    else:
        target = config
    if target.exists():
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CavaError(f"Cava config target is not a regular file: {target}")
        if metadata.st_uid != os.getuid():
            raise CavaError(f"Cava config target is not owned by the current user: {target}")
    try:
        target.absolute().resolve().relative_to(paths.home.resolve())
    except ValueError as exc:
        raise CavaError(f"Cava config target resolves outside the home directory: {target}") from exc
    return target


def _valid_mode(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0o777


def _valid_digest(value: object, *, empty: bool = False) -> bool:
    return bool(
        (empty and value == "")
        or (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )
    )


def validate_selector_state(
    value: object, *, require_paths: bool = True
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CavaError("Cava selector restoration state must be a JSON object")
    required_types: dict[str, type] = {
        "version": int,
        "installedValue": str,
        "selectorExisted": bool,
        "previousLine": str,
        "createdColorSection": bool,
        "insertedLine": str,
        "predecessorBefore": str,
        "predecessorAfter": str,
        "createdBlock": str,
    }
    if require_paths:
        required_types.update({"configPath": str, "resolvedPath": str, "mode": int})
    for key, expected in required_types.items():
        item = value.get(key)
        if not isinstance(item, expected) or (
            expected is int and isinstance(item, bool)
        ):
            raise CavaError(f"Cava selector restoration state has invalid {key}")
    if value["version"] != _SELECTOR_STATE_VERSION:
        raise CavaError("Cava selector restoration state has an unsupported version")
    installed = str(value["installedValue"])
    if not installed:
        raise CavaError("Cava selector restoration state has an empty installed value")
    if re.fullmatch(r"[^\s#;='\"]+", installed) is None:
        raise CavaError("Cava selector restoration state has an invalid installed value")

    selector_existed = bool(value["selectorExisted"])
    created_section = bool(value["createdColorSection"])
    previous_line = str(value["previousLine"])
    inserted_line = str(value["insertedLine"])
    predecessor_before = str(value["predecessorBefore"])
    predecessor_after = str(value["predecessorAfter"])
    created_block = str(value["createdBlock"])
    if selector_existed:
        if not previous_line or len(previous_line.splitlines(keepends=True)) != 1:
            raise CavaError("Cava selector restoration state has an invalid previous selector")
        try:
            previous_value, _start, _end = _selector_value(previous_line)
        except CavaError as exc:
            raise CavaError(
                "Cava selector restoration state has an invalid previous selector"
            ) from exc
        if previous_value == installed:
            raise CavaError(
                "Cava selector restoration state does not record a previous user selection"
            )
        if created_section or any(
            (inserted_line, predecessor_before, predecessor_after, created_block)
        ):
            raise CavaError("Cava selector restoration state has inconsistent selector fields")
    else:
        if previous_line:
            raise CavaError("Cava selector restoration state has an unexpected previous selector")
        if created_section:
            valid_blocks = {
                prefix + f"[color]{ending}theme = '{installed}'{ending}"
                for ending in ("\n", "\r\n")
                for prefix in ("", ending, ending + ending)
            }
            if (
                created_block not in valid_blocks
                or inserted_line
                or predecessor_before
                or predecessor_after
            ):
                raise CavaError("Cava selector restoration state has invalid created-section fields")
        else:
            if created_block or not inserted_line:
                raise CavaError("Cava selector restoration state has invalid inserted-selector fields")
            valid_inserted = {
                f"theme = '{installed}'\n",
                f"theme = '{installed}'\r\n",
            }
            if inserted_line not in valid_inserted:
                raise CavaError("Cava selector restoration state has invalid inserted selector")
            if bool(predecessor_before) != bool(predecessor_after):
                raise CavaError("Cava selector restoration state has incomplete predecessor fields")
            if predecessor_before:
                ending = "\r\n" if inserted_line.endswith("\r\n") else "\n"
                if (
                    len(predecessor_before.splitlines(keepends=True)) != 1
                    or predecessor_before.endswith(("\r", "\n"))
                    or predecessor_after != predecessor_before + ending
                ):
                    raise CavaError("Cava selector restoration state has invalid predecessor fields")
    if require_paths:
        if not value["configPath"] or not value["resolvedPath"]:
            raise CavaError("Cava selector restoration state has an empty path")
        if not _valid_mode(value["mode"]):
            raise CavaError("Cava selector restoration state has an invalid mode")
    return dict(value)


def read_selector_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise CavaError(f"Cava selector restoration state is not a regular file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CavaError(f"Cava selector restoration state is invalid: {path}") from exc
    return validate_selector_state(raw)


def configure_selector(paths: Paths, config: Path | None = None) -> list[str]:
    config = config or default_config_path(paths)
    target = safe_config_target(paths, config)
    original = target.read_text(encoding="utf-8") if target.is_file() else ""
    current_selector = parse_selector(original)
    updated, selector_state = set_selector(original)
    state_file = selector_state_path(paths)
    existing_state = read_selector_state(state_file)
    if existing_state is not None and str(existing_state["resolvedPath"]) != str(target):
        raise CavaError("Cava config symlink target changed after THPM recorded its selector")
    if (
        existing_state is not None
        and current_selector.value != str(existing_state["installedValue"])
    ):
        # The user selected a new theme after THPM's previous takeover. Treat that
        # value as renewed user ownership before selecting THPM again.
        existing_state = None
    if existing_state is None:
        selector_state["configPath"] = str(config)
        selector_state["resolvedPath"] = str(target)
        selector_state["mode"] = (
            target.stat().st_mode & 0o777 if target.exists() else 0o644
        )
        selector_state = validate_selector_state(selector_state)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_text(
            state_file,
            json.dumps(selector_state, separators=(",", ":")) + "\n",
        )
    changed: list[str] = []
    if updated != original:
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
        atomic_text(target, updated, mode)
        changed.append(str(config))
    return changed


def restore_selector(paths: Paths) -> tuple[list[str], list[str]]:
    state_file = selector_state_path(paths)
    if not state_file.exists():
        config = default_config_path(paths)
        try:
            target = safe_config_target(paths, config)
            if not target.is_file():
                return [], []
            selector = parse_selector(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, CavaError) as exc:
            return [], [
                (
                    "could not verify Cava theme selection without restoration state: "
                    f"{exc}"
                )
            ]
        if selector.value == "thpm":
            return [], [
                (
                    "Cava selector restoration state is missing while the configuration "
                    "still selects THPM's theme"
                )
            ]
        return [], []
    try:
        state = read_selector_state(state_file)
        if state is None:
            return [], []
        config = Path(str(state["configPath"]))
        target = safe_config_target(paths, config)
        if str(state["resolvedPath"]) != str(target):
            raise CavaError("Cava config symlink target changed after THPM recorded its selector")
        current = target.read_text(encoding="utf-8")
        restored, changed = restore_selector_text(current, state)
    except (OSError, UnicodeError, ValueError, CavaError) as exc:
        return [], [f"could not restore Cava theme selection: {exc}"]
    if not changed:
        state_file.unlink(missing_ok=True)
        return [], ["Cava theme selection changed outside THPM; preserved the user's selection"]
    mode = target.stat().st_mode & 0o777
    atomic_text(target, restored, mode)
    state_file.unlink(missing_ok=True)
    return [str(config)], []


def parse_version(output: str) -> tuple[int, int, int] | None:
    matches = _VERSION_RE.findall(output)
    if not matches:
        return None
    return tuple(int(part) for part in matches[-1])  # type: ignore[return-value]


def installed_version(
    command: str = "cava",
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, int, int] | None:
    try:
        completed = run(
            [command, "-v"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version((completed.stdout or "") + "\n" + (completed.stderr or ""))


def _proc_start_time(pid_dir: Path) -> str | None:
    try:
        raw = (pid_dir / "stat").read_text(encoding="utf-8")
        rest = raw[raw.rfind(")") + 2 :].split()
        return rest[19]
    except (OSError, IndexError):
        return None


def discover_processes(paths: Paths, proc_root: Path = Path("/proc")) -> list[CavaProcess]:
    processes: list[CavaProcess] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes
    for pid_dir in entries:
        if not pid_dir.name.isdigit():
            continue
        try:
            if pid_dir.stat().st_uid != os.getuid():
                continue
            executable = (pid_dir / "exe").resolve(strict=True)
            if executable.name != "cava":
                continue
            argv = [part.decode(errors="replace") for part in (pid_dir / "cmdline").read_bytes().split(b"\0") if part]
        except OSError:
            continue
        custom: str | None = None
        for index, argument in enumerate(argv[1:], start=1):
            if argument == "-p" and index + 1 < len(argv):
                custom = argv[index + 1]
                break
            if argument.startswith("-p") and len(argument) > 2:
                custom = argument[2:]
                break
        environment: dict[str, str] = {}
        environment_read = True
        try:
            for item in (pid_dir / "environ").read_bytes().split(b"\0"):
                if b"=" not in item:
                    continue
                key, value = item.split(b"=", 1)
                decoded = key.decode(errors="ignore")
                if decoded in {"HOME", "XDG_CONFIG_HOME"}:
                    environment[decoded] = value.decode(errors="replace")
        except OSError:
            environment_read = False
        home = environment.get("HOME", str(paths.home))
        if "XDG_CONFIG_HOME" in environment:
            config_home = Path(environment["XDG_CONFIG_HOME"]) / "cava"
        else:
            config_home = Path(home) / ".config/cava"
        confidence = "confirmed" if environment_read else "inferred"
        if custom is None:
            config_path = config_home / "config"
        else:
            candidate = Path(custom)
            if candidate.is_absolute():
                config_path = candidate
            else:
                try:
                    cwd = (pid_dir / "cwd").resolve(strict=True)
                    config_path = cwd / candidate
                except OSError:
                    config_path = None
                    confidence = "unknown"
        processes.append(
            CavaProcess(
                int(pid_dir.name),
                str(config_path) if config_path is not None else None,
                str(config_home),
                confidence,
                custom is not None,
                _proc_start_time(pid_dir),
            )
        )
    return sorted(processes, key=lambda item: item.pid)


def _digest(path: Path) -> str | None:
    try:
        return (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file() and not path.is_symlink()
            else None
        )
    except OSError:
        return None


def valid_managed_asset_state(
    state_path: Path, backup_path: Path, target: Path
) -> bool:
    if not state_path.is_file() or state_path.is_symlink():
        return False
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(saved, dict) or not isinstance(saved.get("existed"), bool):
        return False
    if not _valid_digest(saved.get("managedSha256")) or not _valid_mode(
        saved.get("managedMode")
    ):
        return False
    if "pendingSha256" in saved and not _valid_digest(saved["pendingSha256"]):
        return False
    if saved["existed"]:
        if saved.get("priorType") == "file":
            if not _valid_digest(saved.get("priorSha256")) or not _valid_mode(
                saved.get("priorMode")
            ):
                return False
            if _digest(backup_path) != saved.get("priorSha256"):
                return False
        elif saved.get("priorType") == "symlink":
            if not isinstance(saved.get("linkTarget"), str) or not saved["linkTarget"]:
                return False
        else:
            return False
    target_digest = _digest(target)
    target_mode = target.stat().st_mode & 0o777 if target_digest is not None else -1
    return bool(
        target_digest == saved.get("managedSha256")
        and target_mode == saved.get("managedMode")
    )


def diagnose(
    paths: Paths,
    *,
    command_path: str | None,
    version: tuple[int, int, int] | None = None,
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    checks: list[DiagnosticCheck] = []
    if command_path is None:
        checks.append(DiagnosticCheck("cava.binary", "error", "Cava is not installed"))
    else:
        checks.append(DiagnosticCheck("cava.binary", "pass", "Cava executable found", {"path": command_path}))
    detected = version if version is not None else (installed_version(command_path) if command_path else None)
    if detected is None:
        checks.append(DiagnosticCheck("cava.version", "unknown", "Unable to determine the Cava version"))
    elif detected < MINIMUM_VERSION:
        checks.append(DiagnosticCheck("cava.version", "error", "Cava 0.10.6 or newer is required for theme files", {"version": ".".join(map(str, detected))}))
    else:
        checks.append(DiagnosticCheck("cava.version", "pass", "Cava supports theme files", {"version": ".".join(map(str, detected))}))

    config = default_config_path(paths)
    try:
        target = safe_config_target(paths, config)
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        selector = parse_selector(text)
        checks.append(DiagnosticCheck("cava.config", "pass" if target.is_file() else "warning", "Cava default config found" if target.is_file() else "Cava default config does not exist yet", {"path": str(config), "resolvedPath": str(target)}))
        if selector.value == "thpm":
            checks.append(DiagnosticCheck("cava.selector", "pass", "Cava selects THPM's theme", {"selectedTheme": "thpm", "configPath": str(config)}))
        else:
            selected = selector.value or "none"
            checks.append(DiagnosticCheck("cava.selector", "error", f"Cava selects '{selected}', not THPM's generated theme", {"selectedTheme": selected, "expectedTheme": "thpm", "configPath": str(config)}, {"available": True, "id": "cava.select-theme", "requiresConfirmation": True, "command": "thpm doctor cava --fix"}))
    except (OSError, UnicodeError, CavaError) as exc:
        checks.append(DiagnosticCheck("cava.config", "error", str(exc)))
        selector = Selector(None, None, None, None)

    source = theme_source(paths)
    target_theme = theme_target(paths)
    if source is None:
        checks.append(DiagnosticCheck("cava.source", "error", "No rendered Cava theme source is available", {"candidates": [str(paths.current_theme / "cava_theme"), str(paths.current_theme / "thpm-cava.ini")]}, {"available": True, "id": "cava.render-theme", "requiresConfirmation": False, "command": "thpm reconcile --refresh"}))
    elif source.name == "thpm-cava.ini" and "{{" in source.read_text(encoding="utf-8", errors="replace"):
        checks.append(DiagnosticCheck("cava.source", "error", "Rendered Cava fallback contains unresolved placeholders", {"path": str(source)}))
    else:
        checks.append(DiagnosticCheck("cava.source", "pass", "Cava theme source is available", {"path": str(source), "sha256": _digest(source)}))
    source_digest = _digest(source) if source else None
    target_digest = _digest(target_theme)
    if target_digest is None:
        checks.append(DiagnosticCheck("cava.target", "error", "THPM's Cava theme is not installed", {"path": str(target_theme)}, {"available": True, "id": "cava.install-theme", "requiresConfirmation": True, "command": "thpm doctor cava --fix"}))
    elif source_digest and source_digest == target_digest:
        checks.append(DiagnosticCheck("cava.target", "pass", "Installed Cava theme matches the active source", {"path": str(target_theme), "sha256": target_digest}))
    else:
        checks.append(DiagnosticCheck("cava.target", "error", "Installed Cava theme is stale or unmanaged", {"path": str(target_theme), "sourceSha256": source_digest, "targetSha256": target_digest}, {"available": True, "id": "cava.install-theme", "requiresConfirmation": True, "command": "thpm doctor cava --fix"}))

    managed_state = paths.managed_asset_state_dir / "generated-cava.json"
    managed_backup = paths.managed_asset_state_dir / "generated-cava.backup"
    if valid_managed_asset_state(managed_state, managed_backup, target_theme):
        checks.append(
            DiagnosticCheck(
                "cava.ownership",
                "pass",
                "Cava theme restoration state matches the installed target",
                {"statePath": str(managed_state)},
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "cava.ownership",
                "error",
                "Cava theme restoration state is missing, invalid, or stale",
                {"statePath": str(managed_state)},
                {
                    "available": True,
                    "id": "cava.rebuild-state",
                    "requiresConfirmation": True,
                    "command": "thpm doctor cava --fix",
                },
            )
        )

    processes = discover_processes(paths, proc_root)
    unknown = [item.pid for item in processes if item.confidence != "confirmed"]
    if not processes:
        checks.append(DiagnosticCheck("cava.processes", "pass", "Cava is not running; it will load the theme on next start", {"running": 0}))
    elif unknown:
        checks.append(DiagnosticCheck("cava.processes", "warning", "Some running Cava instances cannot be matched safely to a config", {"running": len(processes), "unknownPids": unknown}))
    else:
        checks.append(DiagnosticCheck("cava.processes", "pass", "Running Cava configuration paths were identified", {"running": len(processes)}))
    unmatched: list[dict[str, object]] = []
    for process in processes:
        if process.confidence != "confirmed" or process.config_path is None or process.config_home is None:
            continue
        try:
            running_selector = parse_selector(Path(process.config_path).read_text(encoding="utf-8")).value
            running_target = Path(process.config_home) / "themes/thpm"
            consumes_target = running_target.resolve() == target_theme.resolve()
        except (OSError, UnicodeError, CavaError):
            running_selector = None
            consumes_target = False
        if running_selector != "thpm" or not consumes_target:
            unmatched.append(
                {
                    "pid": process.pid,
                    "configPath": process.config_path,
                    "selectedTheme": running_selector or "unknown",
                    "usesManagedThemeDirectory": consumes_target,
                }
            )
    if unmatched:
        checks.append(DiagnosticCheck("cava.runtime-selection", "error", "Running Cava instances do not consume THPM's managed theme", {"instances": unmatched}))
    elif processes and not unknown:
        checks.append(DiagnosticCheck("cava.runtime-selection", "pass", "All confirmed running Cava instances consume THPM's managed theme", {"running": len(processes)}))
    elif processes:
        checks.append(DiagnosticCheck("cava.runtime-selection", "unknown", "Running Cava theme selection could not be fully verified", {"running": len(processes)}))
    else:
        checks.append(DiagnosticCheck("cava.runtime-selection", "skipped", "No running Cava instance needs runtime verification"))
    return {
        "health": "broken" if any(item.status == "error" for item in checks) else ("degraded" if any(item.status in {"warning", "unknown"} for item in checks) else "healthy"),
        "checks": [item.json() for item in checks],
        "processes": [item.json() for item in processes],
        "repairAvailable": any(item.repair and item.repair.get("available") for item in checks),
    }


def _uses_managed_theme(paths: Paths, process: CavaProcess) -> bool:
    if (
        process.confidence != "confirmed"
        or process.config_path is None
        or process.config_home is None
    ):
        return False
    try:
        selected = parse_selector(
            Path(process.config_path).read_text(encoding="utf-8")
        ).value
        process_target = Path(process.config_home) / "themes/thpm"
        return bool(
            selected == "thpm"
            and process_target.resolve() == theme_target(paths).resolve()
        )
    except (OSError, UnicodeError, CavaError):
        return False


def running_cava_requires_restart(
    paths: Paths, *, proc_root: Path = Path("/proc")
) -> bool:
    return bool(discover_processes(paths, proc_root))


def _signal_process(
    process: CavaProcess,
    *,
    proc_root: Path,
    kill: Callable[[int, int], None],
    pidfd_open: Callable[[int], int] | None,
    pidfd_signal: Callable[[int, int], None] | None,
) -> None:
    # Keep injected/fake-process tests on their explicit kill seam. Production
    # opens a pidfd first, then revalidates the discovered identity before using
    # that descriptor so replacement between discovery and acquisition is safe.
    if kill is os.kill and pidfd_open is not None and pidfd_signal is not None:
        descriptor = pidfd_open(process.pid)
        try:
            if process.start_time is None or _proc_start_time(
                proc_root / str(process.pid)
            ) != process.start_time:
                raise ProcessLookupError("process identity changed")
            pidfd_signal(descriptor, signal.SIGUSR1)
        finally:
            os.close(descriptor)
    else:
        if process.start_time is None or _proc_start_time(
            proc_root / str(process.pid)
        ) != process.start_time:
            raise ProcessLookupError("process identity changed")
        kill(process.pid, signal.SIGUSR1)


def reload_matching_processes(
    paths: Paths,
    *,
    proc_root: Path = Path("/proc"),
    kill: Callable[[int, int], None] = os.kill,
    pidfd_open: Callable[[int], int] | None = _PIDFD_OPEN,
    pidfd_signal: Callable[[int, int], None] | None = _PIDFD_SIGNAL,
) -> tuple[list[str], list[str], list[str]]:
    actions: list[str] = []
    warnings: list[str] = []
    processes = discover_processes(paths, proc_root)
    if not processes:
        return actions, [], warnings
    for process in processes:
        if not _uses_managed_theme(paths, process):
            detail = (
                "has an unknown config"
                if process.confidence != "confirmed"
                else "does not use THPM's theme"
            )
            warnings.append(
                f"Cava PID {process.pid} {detail}; it was not signalled"
            )
            continue
        try:
            _signal_process(
                process,
                proc_root=proc_root,
                kill=kill,
                pidfd_open=pidfd_open,
                pidfd_signal=pidfd_signal,
            )
        except (OSError, ProcessLookupError, PermissionError) as exc:
            warnings.append(
                f"Cava PID {process.pid} could not be reloaded ({exc}); restart it"
            )
            continue
        actions.append(f"sent SIGUSR1 to Cava PID {process.pid}")
    restart_required = ["Cava"] if len(actions) < len(processes) else []
    return actions, restart_required, warnings
