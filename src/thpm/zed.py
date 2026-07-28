from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from .files import atomic_copy, atomic_text
from .paths import Paths

THEME_NAME = "THPM Current"
MAX_THEME_BYTES = 1024 * 1024
SOURCE_NAMES = ("zed.json", "aether.zed.json")


class ZedThemeError(ValueError):
    """Raised when a Zed theme or settings file cannot be handled safely."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite number: {value}")


def source(paths: Paths) -> Path | None:
    return next(
        (paths.current_theme / name for name in SOURCE_NAMES if (paths.current_theme / name).is_file()),
        None,
    )


def target(paths: Paths) -> Path:
    return paths.config_home / "zed/themes/thpm-current.json"


def legacy_target(paths: Paths) -> Path:
    return paths.config_home / "zed/themes/omarchy.json"


def omazed_target(paths: Paths) -> Path:
    return paths.config_home / "zed/themes/omazed.json"


def _load_theme(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ZedThemeError(f"Zed theme source must be a regular file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ZedThemeError(f"could not inspect Zed theme source: {path}: {exc}") from exc
    if size > MAX_THEME_BYTES:
        raise ZedThemeError(f"Zed theme source exceeds {MAX_THEME_BYTES} bytes: {path}")
    try:
        raw = path.read_bytes().decode("utf-8", errors="strict")
        data = json.loads(raw, parse_constant=_reject_json_constant)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ZedThemeError(f"invalid Zed theme JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ZedThemeError(f"Zed theme root must be an object: {path}")
    themes = data.get("themes")
    if not isinstance(themes, list) or len(themes) != 1 or not isinstance(themes[0], dict):
        raise ZedThemeError(f"Zed theme must contain exactly one theme object: {path}")
    theme = themes[0]
    if theme.get("appearance") not in {"dark", "light"}:
        raise ZedThemeError(f"Zed theme appearance must be dark or light: {path}")
    if not isinstance(theme.get("style"), dict):
        raise ZedThemeError(f"Zed theme style must be an object: {path}")
    return data


def normalized(path: Path) -> tuple[str, str]:
    data = _load_theme(path)
    theme = data["themes"][0]
    assert isinstance(theme, dict)
    data["name"] = THEME_NAME
    theme["name"] = THEME_NAME
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", str(theme["appearance"])


def _skip_ignored(text: str, index: int) -> int:
    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
        elif text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ZedThemeError("unterminated block comment in Zed settings")
            index = end + 2
        else:
            break
    return index


def _string_end(text: str, index: int) -> int:
    if index >= len(text) or text[index] != '"':
        raise ZedThemeError("expected a JSON string in Zed settings")
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    raise ZedThemeError("unterminated string in Zed settings")


def _value_end(text: str, index: int) -> int:
    if index >= len(text):
        raise ZedThemeError("missing value in Zed settings")
    if text[index] == '"':
        return _string_end(text, index)
    if text[index] in "[{":
        stack = ["]" if text[index] == "[" else "}"]
        index += 1
        while index < len(text):
            if text[index] == '"':
                index = _string_end(text, index)
            elif text.startswith("//", index) or text.startswith("/*", index):
                index = _skip_ignored(text, index)
            elif text[index] in "[{":
                stack.append("]" if text[index] == "[" else "}")
                index += 1
            elif text[index] in "]}":
                if text[index] != stack[-1]:
                    raise ZedThemeError("mismatched container in Zed settings")
                stack.pop()
                index += 1
                if not stack:
                    return index
            else:
                index += 1
        raise ZedThemeError("unterminated container in Zed settings")
    end = index
    while end < len(text) and text[end] not in ",}\n\r":
        end += 1
    if not text[index:end].strip():
        raise ZedThemeError("missing value in Zed settings")
    return end


def _settings_layout(text: str) -> tuple[tuple[int, int] | None, int, int]:
    index = _skip_ignored(text, 0)
    if index >= len(text) or text[index] != "{":
        raise ZedThemeError("Zed settings must be a top-level object")
    opening = index
    theme_span: tuple[int, int] | None = None
    index += 1
    while True:
        index = _skip_ignored(text, index)
        if index >= len(text):
            raise ZedThemeError("unterminated Zed settings object")
        if text[index] == "}":
            trailing = _skip_ignored(text, index + 1)
            if trailing != len(text):
                raise ZedThemeError("unexpected content after Zed settings object")
            return theme_span, opening, index
        key_start = index
        key_end = _string_end(text, key_start)
        try:
            key = json.loads(text[key_start:key_end])
        except json.JSONDecodeError as exc:
            raise ZedThemeError(f"invalid key in Zed settings: {exc}") from exc
        index = _skip_ignored(text, key_end)
        if index >= len(text) or text[index] != ":":
            raise ZedThemeError("missing colon in Zed settings")
        value_start = _skip_ignored(text, index + 1)
        value_end = _value_end(text, value_start)
        if key == "theme":
            if theme_span is not None:
                raise ZedThemeError("duplicate theme setting in Zed settings")
            theme_span = (value_start, value_end)
        index = _skip_ignored(text, value_end)
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == "}":
            continue
        raise ZedThemeError("expected a comma or closing brace in Zed settings")


def _jsonc_value(raw: str) -> object:
    output: list[str] = []
    index = 0
    while index < len(raw):
        if raw[index] == '"':
            end = _string_end(raw, index)
            output.append(raw[index:end])
            index = end
        elif raw.startswith("//", index):
            newline = raw.find("\n", index + 2)
            index = len(raw) if newline < 0 else newline
        elif raw.startswith("/*", index):
            end = raw.find("*/", index + 2)
            if end < 0:
                raise ZedThemeError("unterminated block comment in Zed settings")
            index = end + 2
        else:
            output.append(raw[index])
            index += 1
    cleaned = "".join(output)
    without_trailing: list[str] = []
    index = 0
    while index < len(cleaned):
        if cleaned[index] == '"':
            end = _string_end(cleaned, index)
            without_trailing.append(cleaned[index:end])
            index = end
            continue
        if cleaned[index] == ",":
            lookahead = index + 1
            while lookahead < len(cleaned) and cleaned[lookahead].isspace():
                lookahead += 1
            if lookahead < len(cleaned) and cleaned[lookahead] in "}]":
                index += 1
                continue
        without_trailing.append(cleaned[index])
        index += 1
    return json.loads(
        "".join(without_trailing), parse_constant=_reject_json_constant
    )


def selected_theme(paths: Paths, appearance: str = "dark") -> str | None:
    settings = paths.config_home / "zed/settings.json"
    if not settings.is_file() or settings.is_symlink():
        return None
    try:
        text = settings.read_text(encoding="utf-8")
        span, _opening, _closing = _settings_layout(text)
        parsed = _jsonc_value(text)
        if not isinstance(parsed, dict):
            raise ZedThemeError("Zed settings must be a top-level object")
        if span is None:
            return None
        value = parsed.get("theme")
    except (OSError, UnicodeError, ValueError, ZedThemeError) as exc:
        raise ZedThemeError(f"could not inspect Zed settings at {settings}: {exc}") from exc
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        selected = value.get(appearance)
        return selected if isinstance(selected, str) else None
    raise ZedThemeError("Zed theme setting must be a string or light/dark object")


def _settings_update(paths: Paths) -> tuple[Path, str, str, int]:
    settings = paths.config_home / "zed/settings.json"
    if settings.is_symlink():
        raise ZedThemeError(f"refusing to edit symlinked Zed settings: {settings}")
    if settings.exists() and not settings.is_file():
        raise ZedThemeError(f"Zed settings path is not a regular file: {settings}")
    if settings.is_file():
        try:
            original = settings.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ZedThemeError(f"could not read Zed settings at {settings}: {exc}") from exc
        span, opening, closing = _settings_layout(original)
        parsed = _jsonc_value(original)
        if not isinstance(parsed, dict):
            raise ZedThemeError("Zed settings must be a top-level object")
        if span is not None:
            updated = original[: span[0]] + json.dumps(THEME_NAME) + original[span[1] :]
        else:
            next_value = _skip_ignored(original, opening + 1)
            comma = "" if next_value == closing else ","
            updated = original[: opening + 1] + f'\n  "theme": {json.dumps(THEME_NAME)}{comma}' + original[opening + 1 :]
        mode = settings.stat().st_mode & 0o777
    else:
        original = ""
        updated = json.dumps({"theme": THEME_NAME}, indent=2) + "\n"
        mode = 0o600
    return settings, original, updated, mode


def validate_settings_edit(paths: Paths) -> None:
    _settings_update(paths)


def configure_settings(paths: Paths) -> bool:
    settings, original, updated, mode = _settings_update(paths)
    if updated == original:
        return False
    backup = paths.zed_settings_backup_file
    if settings.is_file() and not backup.exists():
        atomic_copy(settings, backup, mode)
    atomic_text(settings, updated, mode)
    return True


def status(
    paths: Paths, which: Callable[[str], str | None] | None = None
) -> dict[str, object]:
    source_path = source(paths)
    target_path = target(paths)
    warnings: list[str] = []
    appearance = "dark"
    expected: str | None = None
    if source_path is not None:
        try:
            expected, appearance = normalized(source_path)
        except ZedThemeError as exc:
            warnings.append(str(exc))
    synchronized = False
    if expected is not None and target_path.is_file() and not target_path.is_symlink():
        try:
            synchronized = target_path.read_text(encoding="utf-8") == expected
        except (OSError, UnicodeError):
            synchronized = False
    try:
        selected = selected_theme(paths, appearance)
    except ZedThemeError as exc:
        selected = None
        warnings.append(str(exc))
    command_path = (which or shutil.which)("omazed")
    fallback_target = omazed_target(paths)
    if source_path is None:
        if command_path or fallback_target.is_file():
            warnings.append("no authored Zed asset; Omazed is available as a generated fallback—select Omazed in Zed")
        else:
            warnings.append("no authored Zed asset and Omazed is not available")
    else:
        if not synchronized:
            warnings.append("authored Zed theme is not synchronized; run thpm run")
        if selected != THEME_NAME:
            warnings.append(f'Zed selects {selected or "no theme"}; run thpm zed setup to select THPM Current')
    return {
        "source": str(source_path) if source_path else None,
        "sourceName": source_path.name if source_path else None,
        "target": str(target_path),
        "synchronized": synchronized,
        "selectedTheme": selected,
        "themeName": THEME_NAME,
        "omazed": {
            "command": command_path,
            "output": str(fallback_target),
            "outputExists": fallback_target.is_file(),
        },
        "warnings": warnings,
    }
