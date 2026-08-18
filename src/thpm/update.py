from __future__ import annotations

import fcntl
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Literal

from . import __version__
from .files import atomic_text
from .paths import Paths

REPOSITORY = "oldjobobo/thpm"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
CACHE_SECONDS = 86_400
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4_000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
DOWNLOAD_DEADLINE_SECONDS = 300
COMMAND_TIMEOUT_SECONDS = 30
RECONCILE_TIMEOUT_SECONDS = 240
PACKAGE_UPDATE_TIMEOUT_SECONDS = 3_600
UPDATE_CHECK_TIMEOUT_SECONDS = 15 + (3 * COMMAND_TIMEOUT_SECONDS)
HANDOFF_UPDATE_TIMEOUT_SECONDS = (
    UPDATE_CHECK_TIMEOUT_SECONDS
    + PACKAGE_UPDATE_TIMEOUT_SECONDS
    + RECONCILE_TIMEOUT_SECONDS
    + COMMAND_TIMEOUT_SECONDS
    + COMMAND_TIMEOUT_SECONDS
)
RUNTIME_STAGE_TIMEOUT_SECONDS = 600


def _version(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?", value)
    if not match:
        raise ValueError(f"invalid release version: {value}")
    major, minor, patch = (int(part) for part in match.group(1, 2, 3))
    candidate = match.group(4)
    return major, minor, patch, 0 if candidate else 1, int(candidate or 0)


def _read_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"thpm/{__version__}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def origin(paths: Paths) -> dict[str, str]:
    executable = shutil.which("thpm")
    if executable and shutil.which("pacman"):
        owner = subprocess.run(
            ["pacman", "-Qqo", str(Path(executable).resolve())],
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if owner.returncode == 0:
            package = owner.stdout.strip()
            if package in {"thpm", "thpm-git"}:
                installed = subprocess.run(
                    ["pacman", "-Q", package],
                    text=True,
                    capture_output=True,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                )
                installed_version = installed.stdout.strip().split(maxsplit=1)[1] if installed.returncode == 0 and len(installed.stdout.strip().split(maxsplit=1)) == 2 else __version__
                return {"origin": package, "package": package, "repository": REPOSITORY, "installedVersion": installed_version}
    if paths.install_metadata.is_file():
        try:
            data = tomllib.loads(paths.install_metadata.read_text())
            if data.get("origin") == "source":
                return {"origin": "source", "package": "", "repository": str(data.get("repository", REPOSITORY)),
                    "channel": str(data.get("channel", "stable")), "installedVersion": __version__}
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return {"origin": "unsupported", "package": "", "repository": REPOSITORY}


def _cached(paths: Paths) -> dict[str, object] | None:
    try:
        data = json.loads(paths.update_cache_file.read_text())
        if time.time() - float(data["checkedAtEpoch"]) <= CACHE_SECONDS:
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _save_cache(paths: Paths, payload: dict[str, object]) -> None:
    atomic_text(paths.update_cache_file, json.dumps(payload, separators=(",", ":")) + "\n")


def check(paths: Paths, force: bool = False) -> dict[str, object]:
    install = origin(paths)
    if not force and (cache := _cached(paths)) and all(cache.get(key) == install.get(key) for key in ("origin", "channel", "installedVersion")):
        return {**cache, "cached": True}
    if install["origin"] == "unsupported":
        return {"status": "unsupported", "origin": "unsupported", "currentVersion": __version__, "availableVersion": None, "cached": False}
    try:
        if install["origin"] == "source":
            channel = install.get("channel", "stable")
            response = _read_json(os.environ.get("THPM_UPDATE_API_URL", RELEASES_API_URL if channel == "rc" else API_URL))
            if channel == "rc":
                candidates = [item for item in response if isinstance(item, dict) and not item.get("draft")] if isinstance(response, list) else []
                valid: list[tuple[tuple[int, int, int, int, int], dict[str, object]]] = []
                for item in candidates:
                    try: valid.append((_version(str(item.get("tag_name", ""))), item))
                    except ValueError: continue
                if not valid: raise ValueError("no compatible releases found for the rc channel")
                release = max(valid, key=lambda item: item[0])[1]
            elif isinstance(response, dict):
                release = response
            else:
                raise ValueError("release API returned an invalid response")
            available = str(release.get("tag_name", "")).removeprefix("v")
            _version(available)
            assets = {str(item.get("name")): str(item.get("browser_download_url")) for item in release.get("assets", []) if isinstance(item, dict)}
            archive_name = f"thpm-{available}.tar.gz"
            checksum_name = archive_name + ".sha256"
            if archive_name not in assets or checksum_name not in assets:
                raise ValueError("release is missing the source archive or SHA-256 asset")
            status = "available" if _version(available) > _version(__version__) else "current"
            result: dict[str, object] = {"status": status, "origin": "source", "channel": channel, "installedVersion": __version__,
                "currentVersion": __version__, "availableVersion": available, "releaseUrl": str(release.get("html_url", "")),
                "archiveUrl": assets[archive_name], "checksumUrl": assets[checksum_name], "requiresInteractive": False}
        else:
            package = install["package"]
            rpc = _read_json(f"https://aur.archlinux.org/rpc/v5/info/{package}")
            results = rpc.get("results", [])
            available = str(results[0].get("Version", "")) if isinstance(results, list) and results else ""
            installed = str(install.get("installedVersion", __version__))
            status = "available" if available and _arch_version_is_newer(available, installed) else "current"
            result = {"status": status, "origin": install["origin"], "installedVersion": installed,
                "currentVersion": __version__, "availableVersion": available or None,
                "releaseUrl": f"https://aur.archlinux.org/packages/{package}", "requiresInteractive": True}
        result["checkedAtEpoch"] = int(time.time())
        result["checkedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["cached"] = False
        _save_cache(paths, result)
        return result
    except (OSError, ValueError, subprocess.SubprocessError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "error", "origin": install["origin"], "currentVersion": __version__, "availableVersion": None, "cached": False, "error": str(exc)}


@contextmanager
def _lock(paths: Paths) -> Iterator[None]:
    paths.update_lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.update_lock_file.open("w") as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("another THPM update is already running") from exc
        yield


def _arch_version_is_newer(available: str, installed: str) -> bool:
    completed = subprocess.run(
        ["vercmp", available, installed],
        text=True,
        capture_output=True,
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    return int(completed.stdout.strip()) > 0


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"thpm/{__version__}"})
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_DOWNLOAD_BYTES:
            raise ValueError("release download exceeds the size limit")
        total = 0
        while chunk := response.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError("release download exceeded the time limit")
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("release download exceeds the size limit")
            output.write(chunk)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        root = destination.resolve()
        members = bundle.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("release archive contains too many files")
        expanded = 0
        seen: set[str] = set()
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError("release archive contains an unsupported entry type")
            normalized = posixpath.normpath(member.name)
            if normalized in seen:
                raise ValueError("release archive contains duplicate paths")
            seen.add(normalized)
            expanded += member.size
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("release archive exceeds the expanded size limit")
            if member.mode & 0o6000:
                raise ValueError("release archive contains privileged file modes")
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError("release archive contains an unsafe path")
        bundle.extractall(destination)
    candidates = [path.parent for path in destination.rglob("VERSION") if (path.parent / "src/thpm").is_dir() and (path.parent / "assets").is_dir()]
    if len(candidates) != 1: raise ValueError("release archive has an invalid project layout")
    return candidates[0]


def _stage_runtime(source: Path, runtime: Path) -> None:
    source_lock = source / "requirements-source.lock"
    if not source_lock.is_file() or source_lock.is_symlink():
        raise RuntimeError(f"source dependency lock is missing or unsafe: {source_lock}")
    subprocess.run(
        [sys.executable, "-m", "venv", str(runtime)],
        check=True,
        timeout=RUNTIME_STAGE_TIMEOUT_SECONDS,
    )
    subprocess.run(
        [
            str(runtime / "bin/python"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--require-hashes",
            "--only-binary=:all:",
            "--requirement",
            str(source_lock),
        ],
        check=True,
        timeout=RUNTIME_STAGE_TIMEOUT_SECONDS,
    )
    purelib = subprocess.run(
        [str(runtime / "bin/python"), "-c", 'import sysconfig; print(sysconfig.get_path("purelib"))'],
        text=True,
        capture_output=True,
        check=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    ).stdout.strip()
    shutil.copytree(source / "src/thpm", Path(purelib) / "thpm")
    shutil.copytree(source / "assets", runtime / "share/thpm")
    shutil.copy2(source / "assets/bin/thpm", runtime / "bin/thpm")
    os.chmod(runtime / "bin/thpm", 0o755)
    subprocess.run(
        [str(runtime / "bin/thpm"), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    subprocess.run(
        [str(runtime / "bin/python"), "-c", "from thpm.tui import ThpmTui"],
        check=True,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def _remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _restore_directory_contents(source: Path, destination: Path) -> None:
    if destination.is_symlink() or not destination.is_dir():
        _remove_path(destination)
        destination.mkdir(parents=True)
    else:
        for child in destination.iterdir():
            _remove_path(child)
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)


def _backup_integrations(paths: Paths, destination: Path) -> dict[Path, Path | None]:
    # Snapshot complete managed surfaces so rollback also removes files that did
    # not exist before the update (for example templates added by a new release).
    targets = [
        paths.hook_file,
        paths.post_update_hook_file,
        paths.shell_plugin_dir,
        paths.menu_extension,
        paths.themed_dir,
    ]
    backups: dict[Path, Path | None] = {}
    for index, target in enumerate(targets):
        if not target.exists() and not target.is_symlink():
            backups[target] = None
            continue
        backup = destination / str(index)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            link_target = os.readlink(target)
            backup.symlink_to(link_target)
            try:
                referent = (
                    target.resolve(strict=True)
                    if target == paths.themed_dir
                    else None
                )
            except (FileNotFoundError, RuntimeError):
                referent = None
            if referent is not None and referent.is_dir():
                referent_backup = backup.with_name(f"{backup.name}.referent")
                backup.with_name(f"{backup.name}.referent-path").write_text(
                    str(referent)
                )
                shutil.copytree(referent, referent_backup, symlinks=True)
        elif target.is_dir():
            shutil.copytree(target, backup)
        else:
            shutil.copy2(target, backup)
        backups[target] = backup
    return backups


def _restore_integrations(backups: dict[Path, Path | None]) -> None:
    for target, backup in backups.items():
        _remove_path(target)
        if backup is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_symlink():
            link_target = os.readlink(backup)
            referent_backup = backup.with_name(f"{backup.name}.referent")
            referent_path_backup = backup.with_name(
                f"{backup.name}.referent-path"
            )
            if referent_backup.exists() and referent_path_backup.exists():
                referent = Path(referent_path_backup.read_text())
                referent.parent.mkdir(parents=True, exist_ok=True)
                _restore_directory_contents(referent_backup, referent)
            if not (
                target.is_symlink() and os.readlink(target) == link_target
            ):
                _remove_path(target)
                target.symlink_to(link_target)
        elif backup.is_dir():
            shutil.copytree(backup, target)
        else:
            shutil.copy2(backup, target)


def _source_runtime() -> Path:
    # Keep the venv path itself: resolving bin/python follows its symlink to the
    # system interpreter and loses the source runtime root.
    runtime = Path(sys.executable).absolute().parent.parent
    if runtime.name != "runtime": raise RuntimeError("source runtime could not be identified")
    return runtime


def _handoff_package_update(paths: Paths) -> dict[str, object]:
    launcher = shutil.which("omarchy-launch-floating-terminal-with-presentation")
    if launcher is None:
        return {
            "status": "requires-interactive",
            "command": "thpm update",
            "error": "a terminal is required to authorize the package update",
        }
    thpm = shutil.which("thpm") or "thpm"
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    fd, result_name = tempfile.mkstemp(
        prefix="thpm-update-result-", suffix=".json", dir=paths.runtime_dir
    )
    os.close(fd)
    result_file = Path(result_name)
    command = " ".join(
        [
            "env",
            f"THPM_UPDATE_RESULT_FILE={shlex.quote(str(result_file))}",
            shlex.quote(thpm),
            "update",
            "apply",
            "--inline",
        ]
    )
    deadline = time.monotonic() + HANDOFF_UPDATE_TIMEOUT_SECONDS
    keep_result_file = False
    try:
        try:
            launched = subprocess.run(
                [launcher, command],
                check=False,
                timeout=HANDOFF_UPDATE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            launched = None
        while True:
            try:
                serialized = result_file.read_text()
            except (OSError, UnicodeError) as exc:
                return {
                    "status": "error",
                    "error": f"terminal update result could not be read: {exc}",
                }
            if serialized:
                try:
                    payload = json.loads(serialized)
                except json.JSONDecodeError as exc:
                    return {
                        "status": "error",
                        "error": f"terminal update did not return a valid result: {exc}",
                    }
                break
            if launched is not None and launched.returncode != 0:
                return {
                    "status": "error",
                    "error": "terminal update could not be launched",
                }
            if time.monotonic() >= deadline:
                # The launcher does not expose the detached worker process, so
                # keep its reserved inode: a late worker may still atomically
                # replace it with the final result.
                keep_result_file = True
                return {
                    "status": "error",
                    "error": "terminal update timed out before returning a result",
                }
            time.sleep(0.1)
        if not isinstance(payload, dict):
            return {
                "status": "error",
                "error": "terminal update returned an invalid result",
            }
        result = payload.get("result")
        if isinstance(result, dict):
            return {**result, "terminalHandoff": True}
        return {
            "status": "error",
            "error": str(payload.get("summary") or "terminal update failed"),
        }
    finally:
        if not keep_result_file:
            result_file.unlink(missing_ok=True)


def apply(
    paths: Paths,
    progress: Callable[[str, str | None], None] | None = None,
    *,
    mode: Literal["deny", "inline", "handoff"] = "inline",
) -> dict[str, object]:
    def step(message: str, detail: str | None = None) -> None:
        if progress is not None:
            progress(message, detail)

    update = check(paths, force=True)
    if update["status"] != "available":
        return update
    set_total = getattr(progress, "set_total", None)
    if callable(set_total):
        set_total(3 if update["origin"] in {"thpm", "thpm-git"} else 9)
    if update["origin"] in {"thpm", "thpm-git"}:
        package = str(update["origin"])
        if mode == "deny":
            return {
                **update,
                "status": "requires-interactive",
                "command": "thpm update",
                "error": "rerun thpm update in a terminal",
            }
        if mode == "handoff":
            return {**update, **_handoff_package_update(paths)}
        if mode != "inline":
            raise ValueError(f"unsupported update mode: {mode}")
        if not sys.stdin.isatty():
            return {
                **update,
                "status": "requires-interactive",
                "command": "thpm update",
                "error": "inline package updates require a terminal",
            }
        yay = shutil.which("yay")
        if not yay: raise RuntimeError("yay is required to update an AUR installation")
        step("Upgrading AUR package", package)
        suspend = getattr(progress, "suspend", None)
        terminal = suspend() if callable(suspend) else nullcontext()
        with _lock(paths), terminal:
            subprocess.run(
                [yay, "-S", "--noconfirm", "--needed", package],
                check=True,
                timeout=PACKAGE_UPDATE_TIMEOUT_SECONDS,
            )
            thpm = shutil.which("thpm") or "thpm"
            refresh_error = ""
            step("Synchronizing integrations")
            try:
                subprocess.run(
                    [thpm, "reconcile", "--refresh"],
                    check=True,
                    timeout=RECONCILE_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                refresh_error = str(exc)
            ui_refresh_error = ""
            step("Refreshing control panel")
            try:
                subprocess.run(
                    [thpm, "ui", "install"],
                    check=True,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                ui_refresh_error = str(exc)
        refresh_required = bool(refresh_error)
        ui_refresh_required = bool(ui_refresh_error)
        return {
            **update,
            "status": "updated",
            "command": None,
            "packageCommitted": True,
            "restartShell": True,
            "refreshRequired": refresh_required,
            "refreshCommand": "thpm reconcile --refresh" if refresh_required else None,
            "refreshError": refresh_error or None,
            "uiRefreshRequired": ui_refresh_required,
            "uiRefreshCommand": "thpm ui install" if ui_refresh_required else None,
            "uiRefreshError": ui_refresh_error or None,
        }
    with _lock(paths), tempfile.TemporaryDirectory(prefix="thpm-update-") as temporary:
        temp = Path(temporary); archive = temp / "release.tar.gz"; checksum = temp / "release.sha256"
        step("Downloading release archive", str(update["availableVersion"]))
        _download(str(update["archiveUrl"]), archive)
        step("Downloading release checksum")
        _download(str(update["checksumUrl"]), checksum)
        step("Verifying release integrity")
        expected = checksum.read_text().split()[0].lower()
        actual = _file_sha256(archive)
        if expected != actual: raise RuntimeError("release checksum verification failed")
        source = _safe_extract(archive, temp / "source")
        if source.joinpath("VERSION").read_text().strip() != update["availableVersion"]: raise RuntimeError("release version does not match its archive")
        step("Staging isolated runtime")
        runtime = _source_runtime()
        staged = runtime.with_name(f"runtime.next-{os.getpid()}"); previous = runtime.with_name("runtime.previous")
        shutil.rmtree(staged, ignore_errors=True); _stage_runtime(source, staged); shutil.rmtree(previous, ignore_errors=True)
        integration_backups = _backup_integrations(paths, temp / "integration-backup")
        step("Activating new runtime")
        runtime.rename(previous)
        try:
            staged.rename(runtime)
            # Updates must not rerun legacy migration or rewrite persisted plugin
            # state. Reconcile only the managed hook/templates, then refresh QML.
            step("Synchronizing integrations")
            subprocess.run(
                [
                    str(runtime / "bin/thpm"),
                    "reconcile",
                    "--defer-upgrade-refresh",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=RECONCILE_TIMEOUT_SECONDS,
            )
            step("Refreshing control panel")
            subprocess.run(
                [str(runtime / "bin/thpm"), "ui", "install"],
                check=True,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except Exception:
            shutil.rmtree(runtime, ignore_errors=True); previous.rename(runtime); _restore_integrations(integration_backups); raise
        shutil.rmtree(previous, ignore_errors=True)
        paths.update_cache_file.unlink(missing_ok=True)
        step("Refreshing active theme")
        refresh_error = ""
        try:
            subprocess.run(
                [str(runtime / "bin/thpm"), "reconcile", "--refresh"],
                check=True,
                capture_output=True,
                text=True,
                timeout=RECONCILE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            refresh_error = str(exc)
        refresh_required = bool(refresh_error)
        return {
            **update,
            "status": "updated",
            "restartShell": True,
            "refreshRequired": refresh_required,
            "refreshCommand": "thpm reconcile --refresh" if refresh_required else None,
            "refreshError": refresh_error or None,
            "uiRefreshRequired": False,
            "uiRefreshCommand": None,
            "uiRefreshError": None,
        }
