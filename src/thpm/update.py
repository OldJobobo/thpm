from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import __version__
from .files import atomic_text
from .paths import Paths

REPOSITORY = "oldjobobo/thpm"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CACHE_SECONDS = 86_400


def _version(value: str) -> tuple[int, int, int]:
    text = value.removeprefix("v")
    parts = text.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _read_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"thpm/{__version__}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def origin(paths: Paths) -> dict[str, str]:
    executable = shutil.which("thpm")
    if executable and shutil.which("pacman"):
        owner = subprocess.run(["pacman", "-Qqo", str(Path(executable).resolve())], text=True, capture_output=True)
        if owner.returncode == 0:
            package = owner.stdout.strip()
            if package in {"thpm", "thpm-git"}:
                installed = subprocess.run(["pacman", "-Q", package], text=True, capture_output=True)
                installed_version = installed.stdout.strip().split(maxsplit=1)[1] if installed.returncode == 0 and len(installed.stdout.strip().split(maxsplit=1)) == 2 else __version__
                return {"origin": package, "package": package, "repository": REPOSITORY, "installedVersion": installed_version}
    if paths.install_metadata.is_file():
        try:
            data = tomllib.loads(paths.install_metadata.read_text())
            if data.get("origin") == "source":
                return {"origin": "source", "package": "", "repository": str(data.get("repository", REPOSITORY))}
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
    if not force and (cache := _cached(paths)) and cache.get("origin") == install["origin"]:
        return {**cache, "cached": True}
    if install["origin"] == "unsupported":
        return {"status": "unsupported", "origin": "unsupported", "currentVersion": __version__, "availableVersion": None, "cached": False}
    try:
        if install["origin"] == "source":
            release = _read_json(os.environ.get("THPM_UPDATE_API_URL", API_URL))
            available = str(release.get("tag_name", "")).removeprefix("v")
            _version(available)
            assets = {str(item.get("name")): str(item.get("browser_download_url")) for item in release.get("assets", []) if isinstance(item, dict)}
            archive_name = f"thpm-{available}.tar.gz"
            checksum_name = archive_name + ".sha256"
            if archive_name not in assets or checksum_name not in assets:
                raise ValueError("release is missing the source archive or SHA-256 asset")
            status = "available" if _version(available) > _version(__version__) else "current"
            result: dict[str, object] = {"status": status, "origin": "source", "currentVersion": __version__, "availableVersion": available,
                "releaseUrl": str(release.get("html_url", "")), "archiveUrl": assets[archive_name], "checksumUrl": assets[checksum_name], "requiresInteractive": False}
        else:
            package = install["package"]
            rpc = _read_json(f"https://aur.archlinux.org/rpc/v5/info/{package}")
            results = rpc.get("results", [])
            available = str(results[0].get("Version", "")) if isinstance(results, list) and results else ""
            status = "available" if available and available != install.get("installedVersion", __version__) else "current"
            result = {"status": status, "origin": install["origin"], "currentVersion": __version__, "availableVersion": available or None,
                "releaseUrl": f"https://aur.archlinux.org/packages/{package}", "requiresInteractive": True}
        result["checkedAtEpoch"] = int(time.time())
        result["checkedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["cached"] = False
        _save_cache(paths, result)
        return result
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "error", "origin": install["origin"], "currentVersion": __version__, "availableVersion": None, "cached": False, "error": str(exc)}


@contextmanager
def _lock(paths: Paths) -> Iterator[None]:
    paths.update_lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.update_lock_file.open("w") as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("another THPM update is already running") from exc
        yield


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"thpm/{__version__}"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _safe_extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        root = destination.resolve()
        for member in bundle.getmembers():
            if member.issym() or member.islnk():
                raise ValueError("release archive contains a link")
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError("release archive contains an unsafe path")
        bundle.extractall(destination)
    candidates = [path.parent for path in destination.rglob("VERSION") if (path.parent / "src/thpm").is_dir() and (path.parent / "assets").is_dir()]
    if len(candidates) != 1: raise ValueError("release archive has an invalid project layout")
    return candidates[0]


def _stage_runtime(source: Path, runtime: Path) -> None:
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(runtime)], check=True)
    purelib = subprocess.run([str(runtime / "bin/python"), "-c", 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True, capture_output=True, check=True).stdout.strip()
    shutil.copytree(source / "src/thpm", Path(purelib) / "thpm")
    shutil.copytree(source / "assets", runtime / "share/thpm")
    shutil.copy2(source / "assets/bin/thpm", runtime / "bin/thpm")
    os.chmod(runtime / "bin/thpm", 0o755)
    subprocess.run([str(runtime / "bin/thpm"), "--version"], check=True, capture_output=True, text=True)


def _backup_integrations(paths: Paths, destination: Path) -> dict[Path, Path | None]:
    targets = [paths.hook_file, paths.shell_plugin_dir, paths.menu_extension, *paths.themed_dir.glob("thpm-*")]
    backups: dict[Path, Path | None] = {}
    for index, target in enumerate(targets):
        if not target.exists():
            backups[target] = None
            continue
        backup = destination / str(index)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.is_dir(): shutil.copytree(target, backup)
        else: shutil.copy2(target, backup)
        backups[target] = backup
    return backups


def _restore_integrations(backups: dict[Path, Path | None]) -> None:
    for target, backup in backups.items():
        if target.is_dir(): shutil.rmtree(target, ignore_errors=True)
        else: target.unlink(missing_ok=True)
        if backup is None: continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_dir(): shutil.copytree(backup, target)
        else: shutil.copy2(backup, target)


def apply(paths: Paths) -> dict[str, object]:
    update = check(paths, force=True)
    if update["status"] != "available":
        return update
    if update["origin"] in {"thpm", "thpm-git"}:
        package = str(update["origin"])
        command = f"yay -S {package}"
        launcher = shutil.which("omarchy-launch-floating-terminal-with-presentation")
        if not launcher: raise RuntimeError("Omarchy's floating terminal launcher is unavailable")
        subprocess.Popen([launcher, command], start_new_session=True)
        return {**update, "status": "started", "command": command}
    with _lock(paths), tempfile.TemporaryDirectory(prefix="thpm-update-") as temporary:
        temp = Path(temporary); archive = temp / "release.tar.gz"; checksum = temp / "release.sha256"
        _download(str(update["archiveUrl"]), archive); _download(str(update["checksumUrl"]), checksum)
        expected = checksum.read_text().split()[0].lower()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if expected != actual: raise RuntimeError("release checksum verification failed")
        source = _safe_extract(archive, temp / "source")
        if source.joinpath("VERSION").read_text().strip() != update["availableVersion"]: raise RuntimeError("release version does not match its archive")
        runtime = Path(sys.executable).resolve().parent.parent
        if runtime.name != "runtime": raise RuntimeError("source runtime could not be identified")
        staged = runtime.with_name(f"runtime.next-{os.getpid()}"); previous = runtime.with_name("runtime.previous")
        shutil.rmtree(staged, ignore_errors=True); _stage_runtime(source, staged); shutil.rmtree(previous, ignore_errors=True)
        integration_backups = _backup_integrations(paths, temp / "integration-backup")
        runtime.rename(previous)
        try:
            staged.rename(runtime)
            subprocess.run([str(runtime / "bin/thpm"), "install", "--no-ui"], check=True, capture_output=True, text=True)
            subprocess.run([str(runtime / "bin/thpm"), "ui", "install"], check=True, capture_output=True, text=True)
        except Exception:
            shutil.rmtree(runtime, ignore_errors=True); previous.rename(runtime); _restore_integrations(integration_backups); raise
        shutil.rmtree(previous, ignore_errors=True)
        paths.update_cache_file.unlink(missing_ok=True)
        return {**update, "status": "updated", "restartShell": True}
