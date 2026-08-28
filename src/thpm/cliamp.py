from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .files import atomic_text
from .paths import Paths

_STATE_VERSION = 1
_THEME = "omarchy"
_THEME_LIKE_RE = re.compile(r"^[ \t]*theme(?:[ \t=]|$)", re.IGNORECASE)
_THEME_RE = re.compile(
    r"^(?P<prefix>[ \t]*theme[ \t]*=[ \t]*)(?P<quote>['\"])(?P<value>[^'\"\r\n]*)(?P=quote)(?P<suffix>[ \t]*(?:[#;].*)?)(?P<ending>\r?\n)?$",
    re.IGNORECASE,
)
_SECTION_RE = re.compile(r"^[ \t]*\[")


class CliampError(RuntimeError):
    pass


@dataclass(frozen=True)
class Selector:
    value: str | None
    line: int | None
    original_line: str | None = None
    value_start: int | None = None
    value_end: int | None = None


def config_path(paths: Paths) -> Path:
    return paths.config_home / "cliamp/config.toml"


def selector_state_path(paths: Paths) -> Path:
    return paths.managed_asset_state_dir / "cliamp-selection.json"


def selected_theme(paths: Paths) -> str | None:
    target = _safe_config_target(paths)
    if not target.exists():
        return None
    return parse_selector(target.read_text(encoding="utf-8")).value


def parse_selector(text: str) -> Selector:
    matches: list[tuple[int, re.Match[str], str]] = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        if _SECTION_RE.match(line):
            break
        if line.lstrip().startswith(("#", ";")) or not _THEME_LIKE_RE.match(line):
            continue
        match = _THEME_RE.match(line)
        if match is None:
            raise CliampError("cliamp config contains a malformed top-level theme selector")
        matches.append((index, match, line))
    if len(matches) > 1:
        raise CliampError("cliamp config contains duplicate top-level theme selectors")
    if not matches:
        return Selector(None, None)
    index, match, line = matches[0]
    return Selector(
        match.group("value"),
        index,
        line,
        match.start("value"),
        match.end("value"),
    )


def _safe_config_target(paths: Paths) -> Path:
    config = config_path(paths)
    if config.is_symlink():
        try:
            target = config.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise CliampError(f"cliamp config symlink cannot be resolved: {config}") from exc
    else:
        target = config
    if target.exists():
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CliampError(f"cliamp config target is not a regular file: {target}")
        if metadata.st_uid != os.getuid():
            raise CliampError(f"cliamp config target is not owned by the current user: {target}")
    try:
        target.absolute().resolve().relative_to(paths.home.resolve())
    except ValueError as exc:
        raise CliampError(f"cliamp config target resolves outside the home directory: {target}") from exc
    return target


def _read_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise CliampError(f"cliamp selector restoration state is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliampError(f"invalid cliamp selector restoration state: {path}") from exc
    if not isinstance(value, dict) or value.get("version") != _STATE_VERSION:
        raise CliampError(f"invalid cliamp selector restoration state: {path}")
    required = {
        "installedValue": str,
        "selectorExisted": bool,
        "previousLine": str,
        "insertedLine": str,
        "configExisted": bool,
        "resolvedPath": str,
        "mode": int,
    }
    for key, expected in required.items():
        item = value.get(key)
        if not isinstance(item, expected) or (expected is int and isinstance(item, bool)):
            raise CliampError(f"invalid cliamp selector restoration state: {path}")
    if value["installedValue"] != _THEME:
        raise CliampError(f"invalid cliamp selector restoration state: {path}")
    return value


def select_override(paths: Paths) -> tuple[list[str], list[str]]:
    state_path = selector_state_path(paths)
    state = _read_state(state_path)
    target = _safe_config_target(paths)
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    selector = parse_selector(text)
    if state is not None:
        if selector.value != _THEME:
            return [], ["preserved user-selected cliamp theme"]
        return [], []
    if selector.value == _THEME:
        return [], []

    lines = text.splitlines(keepends=True)
    config_existed = target.exists()
    mode = target.stat().st_mode & 0o777 if config_existed else 0o644
    if selector.line is not None:
        assert selector.value_start is not None and selector.value_end is not None
        line = lines[selector.line]
        lines[selector.line] = line[: selector.value_start] + _THEME + line[selector.value_end :]
        inserted = ""
        previous = selector.original_line or ""
    else:
        ending = "\r\n" if "\r\n" in text else "\n"
        inserted = f'theme = "{_THEME}"{ending}'
        lines.insert(0, inserted)
        previous = ""
    saved: dict[str, object] = {
        "version": _STATE_VERSION,
        "installedValue": _THEME,
        "selectorExisted": selector.line is not None,
        "previousLine": previous,
        "insertedLine": inserted,
        "configExisted": config_existed,
        "resolvedPath": str(target),
        "mode": mode,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(state_path, json.dumps(saved, separators=(",", ":")) + "\n")
    try:
        atomic_text(target, "".join(lines), mode=mode)
    except Exception:
        state_path.unlink(missing_ok=True)
        raise
    return [str(config_path(paths))], []


def restore_selection(paths: Paths) -> tuple[list[str], list[str]]:
    state_path = selector_state_path(paths)
    state = _read_state(state_path)
    if state is None:
        return [], []
    target = Path(str(state["resolvedPath"]))
    try:
        target.resolve().relative_to(paths.home.resolve())
    except ValueError:
        return [], [f"could not restore cliamp theme selection because state is invalid: {state_path}"]
    if not target.is_file() or target.is_symlink():
        return [], [f"could not restore cliamp theme selection because config is unavailable: {target}"]
    text = target.read_text(encoding="utf-8")
    selector = parse_selector(text)
    if selector.value != _THEME or selector.line is None:
        state_path.unlink(missing_ok=True)
        return [], ["preserved user-selected cliamp theme"]

    lines = text.splitlines(keepends=True)
    if bool(state["selectorExisted"]):
        previous = str(state["previousLine"])
        previous_match = _THEME_RE.match(previous)
        if previous_match is None:
            raise CliampError(f"invalid cliamp selector restoration state: {state_path}")
        expected = (
            previous[: previous_match.start("value")]
            + _THEME
            + previous[previous_match.end("value") :]
        )
        if lines[selector.line] != expected:
            return [], ["preserved user-modified cliamp theme selector"]
        lines[selector.line] = previous
    else:
        expected = str(state["insertedLine"])
        if lines[selector.line] != expected:
            return [], ["preserved user-modified cliamp theme selector"]
        del lines[selector.line]
    restored = "".join(lines)
    if not bool(state["configExisted"]) and not restored:
        target.unlink()
    else:
        mode = state["mode"]
        assert isinstance(mode, int) and not isinstance(mode, bool)
        atomic_text(target, restored, mode=mode)
    state_path.unlink(missing_ok=True)
    return [str(config_path(paths))], []
