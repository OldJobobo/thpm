from __future__ import annotations

import hashlib
import json
import platform
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .audit import recent_entries, sanitize, utc_now
from .cava import installed_version as cava_version
from .cava import selector_state_path, theme_source, theme_target
from .files import atomic_text
from .paths import Paths
from .update import origin

REPORT_SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 256 * 1024
MAX_REPORT_OPERATIONS = 50


def _serialized(report: Mapping[str, Any]) -> str:
    return json.dumps(dict(report), indent=2, ensure_ascii=False) + "\n"


def _report_size(report: Mapping[str, Any]) -> int:
    return len(_serialized(report).encode("utf-8"))


def _digest(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def file_metadata(path: Path, home: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path), "exists": path.exists() or path.is_symlink()}
    try:
        metadata = path.lstat()
    except OSError:
        return sanitize(payload, home)
    payload.update(
        type=("symlink" if path.is_symlink() else "file" if path.is_file() else "other"),
        mode=metadata.st_mode & 0o777,
        size=metadata.st_size,
        mtimeNs=metadata.st_mtime_ns,
        sha256=_digest(path),
    )
    if path.is_symlink():
        try:
            payload["resolvedPath"] = str(path.resolve(strict=True))
        except OSError:
            payload["resolvedPath"] = "unresolved"
    return sanitize(payload, home)


def _theme_name(paths: Paths) -> str:
    try:
        value = paths.current_theme_name.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    try:
        return paths.current_theme.resolve(strict=True).name
    except OSError:
        return "unknown"


def _application(plugin: str | None) -> dict[str, Any]:
    if plugin == "cava":
        version = cava_version()
        return {
            "id": "cava",
            "version": ".".join(map(str, version)) if version else "unknown",
        }
    return {"id": plugin or "all", "version": "not-collected"}


def _plugin_files(paths: Paths, plugin: str | None) -> list[dict[str, Any]]:
    if plugin != "cava":
        return []
    source = theme_source(paths)
    candidates = [
        paths.config_home / "cava/config",
        theme_target(paths),
        selector_state_path(paths),
        paths.managed_asset_state_dir / "generated-cava.json",
    ]
    if source is not None:
        candidates.insert(1, source)
    return [file_metadata(path, paths.home) for path in candidates]


def build_report(
    paths: Paths,
    *,
    plugin: str | None,
    plugin_view: Mapping[str, Any] | None,
    doctor: Mapping[str, Any],
    now: Callable[[], datetime] = utc_now,
    id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    install_origin: Mapping[str, Any] | None = None,
    max_operations: int = MAX_REPORT_OPERATIONS,
) -> dict[str, Any]:
    generated = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    diagnostics = doctor.get("diagnostics", {})
    checks = doctor.get("checks", [])
    report: dict[str, Any] = {
        "reportSchemaVersion": REPORT_SCHEMA_VERSION,
        "generatedAt": generated,
        "reportId": id_factory(),
        "scope": plugin or "all",
        "thpm": {
            "version": __version__,
            "install": dict(install_origin or origin(paths)),
        },
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "architecture": platform.machine(),
        },
        "application": _application(plugin),
        "activeTheme": _theme_name(paths),
        "plugin": dict(plugin_view) if plugin_view else None,
        "doctor": {
            "ok": bool(doctor.get("ok")),
            "summary": doctor.get("summary", ""),
            "checks": checks,
            "diagnostics": diagnostics,
        },
        "files": _plugin_files(paths, plugin),
        "recentOperations": recent_entries(
            paths, plugin=plugin, limit=min(max_operations, MAX_REPORT_OPERATIONS)
        ),
        "privacy": {
            "omitted": [
                "hostname and machine identifiers",
                "raw process environment",
                "configuration and theme file contents",
                "unrelated process arguments",
                "unbounded stdout and stderr",
            ],
            "redacted": [
                "token/password/secret-like keys and values, including authorization headers",
                "URL userinfo, query strings, and fragments",
                "home directory paths normalized to ~ wherever they appear",
            ],
            "limits": {
                "maxBytes": MAX_REPORT_BYTES,
                "maxRecentOperations": min(max_operations, MAX_REPORT_OPERATIONS),
            },
            "truncated": False,
        },
    }
    sanitized = sanitize(report, paths.home)

    def trim_list(container: dict[str, Any], name: str) -> None:
        items = container.get(name)
        while _report_size(sanitized) > MAX_REPORT_BYTES and isinstance(items, list) and items:
            items.pop()
            sanitized["privacy"]["truncated"] = True

    # Trim the least essential, potentially repeated sections first. Size checks
    # use the exact pretty serialization that write_report writes.
    trim_list(sanitized, "recentOperations")
    if _report_size(sanitized) > MAX_REPORT_BYTES:
        sanitized["doctor"]["diagnostics"] = {
            "omitted": "diagnostics exceeded report size bound"
        }
        sanitized["privacy"]["truncated"] = True
    trim_list(sanitized["doctor"], "checks")
    trim_list(sanitized, "files")
    if _report_size(sanitized) > MAX_REPORT_BYTES:
        sanitized["plugin"] = {"omitted": "plugin detail exceeded report size bound"}
        sanitized["privacy"]["truncated"] = True
    if _report_size(sanitized) > MAX_REPORT_BYTES:
        sanitized["thpm"]["install"] = {
            "omitted": "installation detail exceeded report size bound"
        }
        sanitized["privacy"]["truncated"] = True
    if _report_size(sanitized) > MAX_REPORT_BYTES:
        # Sanitization already bounds scalar values, so reaching this fallback
        # requires unexpectedly expansive schema data. Preserve the schema and
        # generation identity while making the omission explicit.
        privacy = sanitized["privacy"]
        privacy["truncated"] = True
        sanitized = {
            "reportSchemaVersion": REPORT_SCHEMA_VERSION,
            "generatedAt": generated,
            "reportId": sanitized["reportId"],
            "scope": sanitized["scope"],
            "thpm": {"version": __version__, "install": {"omitted": "size bound"}},
            "runtime": sanitized["runtime"],
            "application": sanitized["application"],
            "activeTheme": sanitized["activeTheme"],
            "plugin": {"omitted": "size bound"},
            "doctor": {
                "ok": bool(doctor.get("ok")),
                "summary": "details omitted to satisfy report size bound",
                "checks": [],
                "diagnostics": {},
            },
            "files": [],
            "recentOperations": [],
            "privacy": privacy,
        }
    if _report_size(sanitized) > MAX_REPORT_BYTES:
        raise ValueError("support report metadata exceeds its size bound")
    return sanitized


def write_report(
    paths: Paths,
    report: Mapping[str, Any],
    *,
    output: Path | None = None,
) -> Path:
    if output is None:
        scope = re_safe(str(report.get("scope", "all")))
        timestamp = str(report.get("generatedAt", "report")).replace(":", "").replace("-", "")
        output = paths.report_dir / f"thpm-{scope}-{timestamp}.json"
    payload = _serialized(report)
    if len(payload.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("support report exceeds its size bound")
    atomic_text(output, payload, 0o600)
    return output


def re_safe(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "-" for character in value)[:64] or "all"
