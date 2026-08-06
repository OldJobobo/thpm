from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .paths import Paths

JOURNAL_SCHEMA_VERSION = 1
MAX_JOURNAL_BYTES = 1024 * 1024
MAX_ROTATIONS = 4
MAX_STRING = 512
MAX_LIST = 32
MAX_RECENT_ENTRIES = 100
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_SECRET_KEY = re.compile(
    r"(?:token|password|passwd|secret|api[_-]?key|authorization|cookie)",
    re.IGNORECASE,
)
_SECRET_HEADER = re.compile(
    r"(?i)((?:authorization|cookie)\s*[:=]\s*)([^\r\n,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)(\bbearer\s+)([^\s,;]+)")
_SECRET_VALUE = re.compile(
    r"(?i)(token|password|passwd|secret|api[_-]?key)(\s*[:=]\s*)([^\s,;]+)"
)
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_path(value: str, home: Path) -> str:
    home_text = str(home)
    if not home_text or home_text == os.sep:
        return value
    # Diagnostic strings often contain a path after a human-readable prefix.
    # Normalize every complete home prefix, not only strings that begin with it.
    value = value.replace(home_text + os.sep, "~" + os.sep)
    return re.sub(
        re.escape(home_text) + r"(?=$|[\s,;:)\]}])",
        "~",
        value,
    )


def _strip_url(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parts = urlsplit(raw)
            # Never retain URL userinfo: it can contain plaintext credentials.
            netloc = parts.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parts.scheme, netloc, parts.path, "", "")) + trailing
        except ValueError:
            return "[redacted-url]" + trailing

    return _URL.sub(replace, value)


def sanitize(value: Any, home: Path, *, key: str = "", depth: int = 0) -> Any:
    if _SECRET_KEY.search(key):
        return "[redacted]"
    if depth > 8:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        value = normalize_path(_strip_url(value), home)
        value = _SECRET_HEADER.sub(r"\1[redacted]", value)
        value = _BEARER_VALUE.sub(r"\1[redacted]", value)
        value = _SECRET_VALUE.sub(r"\1\2[redacted]", value)
        if len(value) > MAX_STRING:
            return value[: MAX_STRING - 12] + "…[truncated]"
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (item_key, item_value) in enumerate(value.items()):
            if index >= MAX_LIST:
                result["_truncated"] = True
                break
            name = str(item_key)[:128]
            result[name] = sanitize(item_value, home, key=name, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [sanitize(item, home, depth=depth + 1) for item in items[:MAX_LIST]]
        if len(items) > MAX_LIST:
            result.append("[truncated]")
        return result
    return sanitize(str(value), home, key=key, depth=depth + 1)


def _reason_code(operation: str, status: str, message: str) -> str:
    if operation.startswith("cava") or "Cava" in message:
        if "select" in message.lower():
            return "cava.selector-mismatch"
        if "prerequisite" in message.lower() or "0.10.6" in message:
            return "cava.prerequisite-missing"
        if status == "failed":
            return "cava.failed"
    return f"integration.{status}" if status else "operation.completed"


def _action_id(action: str) -> str:
    lowered = action.lower()
    if _URL.search(lowered):
        return "command.remote-url"
    if "sigusr1" in lowered and "cava" in lowered:
        return "cava.reload.sigusr1"
    if "updated mtime" in lowered and "omarchy-system" in lowered:
        return "pi.reload.mtime"
    if lowered.startswith("spicetify refresh"):
        return "spotify.refresh"
    if lowered.startswith("spicetify restart"):
        return "spotify.restart"
    if lowered.startswith("swaync-client"):
        return "swaync.reload-css"
    slug = re.sub(r"[^a-z0-9]+", ".", lowered).strip(".")
    return f"command.{slug[:96]}" if slug else "command.unknown"


def _matching_errors(
    source: Mapping[str, Any], payload: Mapping[str, Any], plugin: str | None
) -> list[Any]:
    own = source.get("errors")
    if isinstance(own, list):
        return own
    global_errors = payload.get("errors", [])
    if not isinstance(global_errors, list):
        return []
    matching = [
        item
        for item in global_errors
        if isinstance(item, Mapping) and item.get("plugin") == plugin
    ]
    if matching:
        return matching
    # Unscoped envelopes have no per-plugin attribution to preserve.
    if plugin is None:
        return global_errors
    return []


def entries_from_payload(
    paths: Paths,
    payload: Mapping[str, Any],
    *,
    plugin: str | None = None,
    run_id: str | None = None,
    now: Callable[[], datetime] = utc_now,
) -> list[dict[str, Any]]:
    operation = str(payload.get("operation", "unknown"))
    run_id = run_id or str(uuid.uuid4())
    timestamp = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    results = payload.get("results")
    sources: Iterable[Mapping[str, Any]]
    if isinstance(results, list) and results:
        sources = [item for item in results if isinstance(item, Mapping)]
    else:
        sources = [payload]
    entries: list[dict[str, Any]] = []
    for source in sources:
        source_plugin = str(source.get("id") or plugin or "") or None
        status = str(source.get("status") or ("applied" if payload.get("ok") else "failed"))
        message = str(source.get("message") or payload.get("summary") or "")
        errors = _matching_errors(source, payload, source_plugin)
        detail = ""
        if errors:
            first = errors[0]
            detail = str(first.get("message", "")) if isinstance(first, Mapping) else str(first)
        actions = source.get("actions", payload.get("actions", []))
        action_ids = [_action_id(str(item)) for item in actions] if isinstance(actions, list) else []
        entry = {
            "journalSchemaVersion": JOURNAL_SCHEMA_VERSION,
            "timestamp": timestamp,
            "runId": run_id,
            "thpmVersion": __version__,
            "operation": operation,
            "plugin": source_plugin,
            "status": status,
            "reasonCode": str(source.get("reasonCode") or _reason_code(operation, status, message)),
            "durationMs": max(0, int(source.get("durationMs", payload.get("durationMs", 0)) or 0)),
            "changed": source.get("changed", payload.get("changed", [])),
            "actions": action_ids,
            "warnings": source.get("warnings", payload.get("warnings", [])),
            "restartRequired": source.get("restartRequired", payload.get("restartRequired", [])),
            "failureDetail": detail if status == "failed" else "",
        }
        entries.append(sanitize(entry, paths.home))
    return entries


def _open_regular(path: Path, flags: int, mode: int = 0o600) -> int:
    descriptor = os.open(path, flags | _NOFOLLOW, mode)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(f"not a regular file: {path}")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _regular_or_absent(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"not a regular file: {path}")
    return True


@contextmanager
def _journal_lock(paths: Paths, *, shared: bool = False):
    paths.audit_lock_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor = _open_regular(
        paths.audit_lock_file, os.O_CREAT | os.O_RDWR, 0o600
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _rotation_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def _rotate(path: Path, *, rotations: int) -> None:
    if rotations <= 0:
        if _regular_or_absent(path):
            path.unlink()
        return
    candidates = [path, *(_rotation_path(path, index) for index in range(1, rotations + 1))]
    for candidate in candidates:
        if _regular_or_absent(candidate):
            os.chmod(candidate, 0o600, follow_symlinks=False)
    _rotation_path(path, rotations).unlink(missing_ok=True)
    for index in range(rotations - 1, 0, -1):
        source = _rotation_path(path, index)
        if source.exists():
            os.replace(source, _rotation_path(path, index + 1))
    if path.exists():
        os.replace(path, _rotation_path(path, 1))


def _bounded_line(entry: Mapping[str, Any], home: Path, max_bytes: int) -> bytes:
    line = (
        json.dumps(sanitize(dict(entry), home), separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    if len(line) <= max_bytes:
        return line
    fallback: dict[str, Any] = {
        "journalSchemaVersion": JOURNAL_SCHEMA_VERSION,
        "timestamp": entry.get("timestamp", ""),
        "runId": entry.get("runId", ""),
        "plugin": entry.get("plugin"),
        "status": "truncated",
        "reasonCode": "journal.entry-too-large",
    }
    line = (json.dumps(sanitize(fallback, home), separators=(",", ":")) + "\n").encode()
    if len(line) <= max_bytes:
        return line
    minimal = {"journalSchemaVersion": JOURNAL_SCHEMA_VERSION, "status": "truncated"}
    line = (json.dumps(minimal, separators=(",", ":")) + "\n").encode()
    if len(line) > max_bytes:
        raise ValueError("journal size bound is too small for a valid record")
    return line


def _append_line(path: Path, line: bytes) -> None:
    descriptor = _open_regular(
        path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600
    )
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(line)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("unable to append the THPM operation journal")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)


def append_entries(
    paths: Paths,
    entries: Iterable[Mapping[str, Any]],
    *,
    max_bytes: int = MAX_JOURNAL_BYTES,
    rotations: int = MAX_ROTATIONS,
) -> None:
    if max_bytes <= 0 or rotations < 0:
        raise ValueError("journal bounds must be positive")
    lines = [_bounded_line(entry, paths.home, max_bytes) for entry in entries]
    if not lines:
        return
    paths.operation_log.parent.mkdir(parents=True, exist_ok=True)
    with _journal_lock(paths):
        # Reject hostile active or rotated paths before moving or opening any of them.
        for candidate in [
            paths.operation_log,
            *(_rotation_path(paths.operation_log, index) for index in range(1, rotations + 1)),
        ]:
            _regular_or_absent(candidate)
        for line in lines:
            size = paths.operation_log.stat().st_size if paths.operation_log.exists() else 0
            if size + len(line) > max_bytes:
                _rotate(paths.operation_log, rotations=rotations)
            _append_line(paths.operation_log, line)


def record_payload(
    paths: Paths,
    payload: Mapping[str, Any],
    *,
    plugin: str | None = None,
    run_id: str | None = None,
) -> bool:
    try:
        append_entries(paths, entries_from_payload(paths, payload, plugin=plugin, run_id=run_id))
    except Exception:  # noqa: BLE001 - observability must never break an operation
        return False
    return True


def _read_lines(path: Path) -> list[str]:
    if not _regular_or_absent(path):
        return []
    descriptor = _open_regular(path, os.O_RDONLY)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return stream.read().splitlines()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def recent_entries(paths: Paths, *, plugin: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(limit, 0), MAX_RECENT_ENTRIES)
    files = [paths.operation_log]
    files.extend(_rotation_path(paths.operation_log, index) for index in range(1, MAX_ROTATIONS + 1))
    entries: list[dict[str, Any]] = []
    try:
        with _journal_lock(paths, shared=True):
            for path in files:
                try:
                    lines = _read_lines(path)
                except (OSError, UnicodeError):
                    continue
                for line in lines:
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if (
                        not isinstance(entry, dict)
                        or entry.get("journalSchemaVersion") != JOURNAL_SCHEMA_VERSION
                    ):
                        continue
                    if plugin and entry.get("plugin") != plugin:
                        continue
                    entries.append(sanitize(entry, paths.home))
    except OSError:
        return []
    entries.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return entries[:limit]
