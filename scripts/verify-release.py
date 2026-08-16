#!/usr/bin/env python3
"""Verify THPM release metadata, source artifacts, and AUR finalization."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:rc[1-9][0-9]*)?$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseCheckError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _version(repo: Path) -> str:
    version = (repo / "VERSION").read_text().strip()
    if not VERSION_RE.fullmatch(version):
        raise ReleaseCheckError(f"VERSION is not a supported release version: {version!r}")
    return version


def _python_fallback(source: str) -> str | None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


def _assignment(source: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}=([^\n]+)$", source)
    if not match:
        raise ReleaseCheckError(f"missing {name} assignment")
    return match.group(1).strip().strip("'\"")


def _single_array_assignment(source: str, name: str) -> str:
    assignments = re.findall(
        rf"(?m)^{re.escape(name)}(?:_[A-Za-z0-9_]+)?\+?=", source
    )
    if len(assignments) != 1:
        raise ReleaseCheckError(
            f"{name} must have one assignment and no appended or architecture-specific values"
        )
    match = re.search(
        rf"(?m)^{re.escape(name)}=\(\s*(['\"])([^'\"]+)\1\s*\)$", source
    )
    if not match:
        raise ReleaseCheckError(f"{name} must contain exactly one quoted value")
    return match.group(2)


def _srcinfo_values(source: str, name: str) -> list[str]:
    prefix = f"{name} = "
    return [
        line.strip()[len(prefix) :]
        for line in source.splitlines()
        if line.strip().startswith(prefix)
    ]


def _expect_equal(label: str, actual: str | None, expected: str) -> None:
    if actual != expected:
        raise ReleaseCheckError(f"{label} is {actual!r}; expected {expected!r}")


def _expect_values(label: str, actual: list[str], expected: list[str]) -> None:
    if actual != expected:
        raise ReleaseCheckError(f"{label} is {actual!r}; expected {expected!r}")


def check_metadata(repo: Path, *, require_clean: bool = False, require_tag: bool = False) -> str:
    version = _version(repo)
    head_version = _git(repo, "show", "HEAD:VERSION").strip()
    _expect_equal("committed VERSION", head_version, version)
    if require_clean and _git(repo, "status", "--porcelain"):
        raise ReleaseCheckError("release metadata requires a clean working tree")
    if require_tag:
        tag = _git(repo, "describe", "--tags", "--exact-match", "HEAD")
        _expect_equal("release tag", tag, f"v{version}")

    fallback = _python_fallback((repo / "src/thpm/__init__.py").read_text())
    _expect_equal("Python fallback version", fallback, version)
    manifest = json.loads((repo / "assets/qml/manifest.json").read_text())
    _expect_equal("QML manifest version", manifest.get("version"), version)

    panel_versions = set(
        re.findall(r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[1-9][0-9]*)?", (repo / "assets/qml/Panel.qml.in").read_text())
    )
    if panel_versions != {version}:
        raise ReleaseCheckError(f"QML panel fallback versions are {sorted(panel_versions)!r}; expected only {version!r}")
    vencord = (repo / "assets/templates/thpm-vencord-system24.theme.css.tpl").read_text()
    if f"@version {version}" not in vencord:
        raise ReleaseCheckError("Vencord template version does not match VERSION")
    release_note = (repo / "releasenote.md").read_text()
    if f"THPM {version} is now available" not in release_note or f"/tag/v{version}" not in release_note:
        raise ReleaseCheckError("release note version or tag link does not match VERSION")

    stable = (repo / "packaging/aur/thpm/PKGBUILD").read_text()
    stable_srcinfo = (repo / "packaging/aur/thpm/.SRCINFO").read_text()
    stable_pkgrel = _assignment(stable, "pkgrel")
    stable_source = (
        "$pkgname-$pkgver.tar.gz::$url/releases/download/"
        "v$pkgver/$pkgname-$pkgver.tar.gz"
    )
    rendered_source = (
        f"thpm-{version}.tar.gz::https://github.com/oldjobobo/thpm/"
        f"releases/download/v{version}/thpm-{version}.tar.gz"
    )
    stable_digest = _single_array_assignment(stable, "sha256sums")
    if not DIGEST_RE.fullmatch(stable_digest):
        raise ReleaseCheckError("stable PKGBUILD must contain one SHA-256 checksum")
    _expect_equal("stable PKGBUILD pkgver", _assignment(stable, "pkgver"), version)
    _expect_equal("stable PKGBUILD source", _single_array_assignment(stable, "source"), stable_source)
    _expect_equal("stable .SRCINFO pkgver", _srcinfo_values(stable_srcinfo, "pkgver")[0], version)
    _expect_equal("stable .SRCINFO pkgrel", _srcinfo_values(stable_srcinfo, "pkgrel")[0], stable_pkgrel)
    _expect_values("stable .SRCINFO source", _srcinfo_values(stable_srcinfo, "source"), [rendered_source])
    _expect_values(
        "stable .SRCINFO checksums",
        _srcinfo_values(stable_srcinfo, "sha256sums"),
        [stable_digest],
    )

    vcs = (repo / "packaging/aur/thpm-git/PKGBUILD").read_text()
    vcs_srcinfo = (repo / "packaging/aur/thpm-git/.SRCINFO").read_text()
    vcs_pkgrel = _assignment(vcs, "pkgrel")
    vcs_source = "git+https://github.com/oldjobobo/thpm.git"
    vcs_version = _assignment(vcs, "pkgver").split(".r", 1)[0]
    vcs_info_version = _srcinfo_values(vcs_srcinfo, "pkgver")[0].split(".r", 1)[0]
    _expect_equal("VCS PKGBUILD release base", vcs_version, version)
    _expect_equal("VCS PKGBUILD source", _single_array_assignment(vcs, "source"), vcs_source)
    _expect_equal("VCS PKGBUILD checksum", _single_array_assignment(vcs, "sha256sums"), "SKIP")
    _expect_equal("VCS .SRCINFO release base", vcs_info_version, version)
    _expect_equal("VCS .SRCINFO pkgrel", _srcinfo_values(vcs_srcinfo, "pkgrel")[0], vcs_pkgrel)
    _expect_values("VCS .SRCINFO source", _srcinfo_values(vcs_srcinfo, "source"), [vcs_source])
    _expect_values("VCS .SRCINFO checksums", _srcinfo_values(vcs_srcinfo, "sha256sums"), ["SKIP"])
    return version


def _checksum(archive: Path, checksum_file: Path) -> str:
    lines = checksum_file.read_text().splitlines()
    if len(lines) != 1:
        raise ReleaseCheckError("checksum file must contain exactly one line")
    match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", lines[0])
    if not match:
        raise ReleaseCheckError("checksum file is not canonical sha256sum output")
    digest, filename = match.groups()
    _expect_equal("checksum filename", filename, archive.name)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    _expect_equal("archive SHA-256", actual, digest)
    return digest


def _git_tree(repo: Path, ref: str) -> dict[str, tuple[str, str]]:
    output = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-rz", ref],
        check=True,
        capture_output=True,
    ).stdout
    tree: dict[str, tuple[str, str]] = {}
    for entry in output.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", 1)
        mode, object_type, _object_id = metadata.decode().split(" ", 2)
        path = encoded_path.decode()
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ReleaseCheckError(
                f"{ref} contains an unsupported Git entry: {mode} {object_type} {path}"
            )
        tree[path] = (mode, object_type)
    return tree


def check_artifact(
    repo: Path, archive: Path, checksum_file: Path, *, ref: str
) -> tuple[str, str]:
    version = _version(repo)
    expected_name = f"thpm-{version}.tar.gz"
    _expect_equal("archive filename", archive.name, expected_name)
    _expect_equal("checksum filename", checksum_file.name, f"{expected_name}.sha256")
    digest = _checksum(archive, checksum_file)
    root = f"thpm-{version}"

    expected_tree = _git_tree(repo, ref)
    expected_files = set(expected_tree)
    expected_dirs = {""}
    for filename in expected_files:
        path = PurePosixPath(filename)
        expected_dirs.update(str(parent) for parent in path.parents if str(parent) != ".")

    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        archived_files: set[str] = set()
        seen_paths: set[str] = set()
        for member in members:
            path = PurePosixPath(member.name)
            normalized = str(path)
            if normalized in seen_paths:
                raise ReleaseCheckError(f"archive contains a duplicate path: {member.name}")
            seen_paths.add(normalized)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != root
            ):
                raise ReleaseCheckError(
                    f"archive contains an unsafe or unexpected path: {member.name}"
                )
            relative = str(PurePosixPath(*path.parts[1:])) if len(path.parts) > 1 else ""
            if member.isdir():
                if relative not in expected_dirs:
                    raise ReleaseCheckError(
                        f"archive contains an unexpected directory: {member.name}"
                    )
                if member.mode & 0o7777 != 0o775:
                    raise ReleaseCheckError(
                        f"archive directory mode is not canonical: {member.name}"
                    )
                continue
            if not (member.isfile() or member.issym()):
                raise ReleaseCheckError(
                    f"archive contains an unsupported entry type: {member.name}"
                )
            archived_files.add(relative)
        if archived_files != expected_files:
            missing = sorted(expected_files - archived_files)
            extra = sorted(archived_files - expected_files)
            raise ReleaseCheckError(
                f"archive tree differs from {ref}: missing={missing!r}, extra={extra!r}"
            )

        for path in sorted(expected_files):
            member = bundle.getmember(f"{root}/{path}")
            mode, _object_type = expected_tree[path]
            if mode == "120000":
                if not member.issym():
                    raise ReleaseCheckError(f"archive type differs from {ref}: {path}")
                if member.mode & 0o7777 != 0o777:
                    raise ReleaseCheckError(f"archive mode differs from {ref}: {path}")
                actual = member.linkname.encode()
            else:
                if not member.isfile():
                    raise ReleaseCheckError(f"archive type differs from {ref}: {path}")
                expected_mode = 0o775 if mode == "100755" else 0o664
                if member.mode & 0o7777 != expected_mode:
                    raise ReleaseCheckError(f"archive mode differs from {ref}: {path}")
                stream = bundle.extractfile(member)
                actual = stream.read() if stream is not None else b""
            expected = subprocess.run(
                ["git", "-C", str(repo), "show", f"{ref}:{path}"],
                check=True,
                capture_output=True,
            ).stdout
            if actual != expected:
                raise ReleaseCheckError(f"archive content differs from {ref}: {path}")

        archive_version = bundle.extractfile(f"{root}/VERSION")
        if archive_version is None:
            raise ReleaseCheckError("archive does not contain VERSION")
        _expect_equal("archive VERSION", archive_version.read().decode().strip(), version)
        init_file = bundle.extractfile(f"{root}/src/thpm/__init__.py")
        manifest_file = bundle.extractfile(f"{root}/assets/qml/manifest.json")
        if init_file is None or manifest_file is None:
            raise ReleaseCheckError("archive is missing runtime version metadata")
        _expect_equal("archive Python fallback", _python_fallback(init_file.read().decode()), version)
        _expect_equal("archive QML manifest", json.loads(manifest_file.read())["version"], version)
    return version, digest


def _check_srcinfo(package_dir: Path) -> None:
    try:
        generated = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=package_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.rstrip()
    except FileNotFoundError as exc:
        raise ReleaseCheckError("makepkg is required to validate .SRCINFO") from exc
    stored = (package_dir / ".SRCINFO").read_text().rstrip()
    if generated != stored:
        raise ReleaseCheckError(f"{package_dir.name}/.SRCINFO is not generated from its PKGBUILD")


def check_packaging(repo: Path, archive: Path, checksum_file: Path) -> str:
    version, digest = check_artifact(
        repo, archive, checksum_file, ref=f"v{_version(repo)}"
    )
    stable_dir = repo / "packaging/aur/thpm"
    stable = (stable_dir / "PKGBUILD").read_text()
    stable_info = (stable_dir / ".SRCINFO").read_text()
    stable_pkgrel = _assignment(stable, "pkgrel")
    stable_source = (
        "$pkgname-$pkgver.tar.gz::$url/releases/download/"
        "v$pkgver/$pkgname-$pkgver.tar.gz"
    )
    expected_source = (
        f"thpm-{version}.tar.gz::https://github.com/oldjobobo/thpm/"
        f"releases/download/v{version}/thpm-{version}.tar.gz"
    )
    _expect_equal("stable PKGBUILD pkgver", _assignment(stable, "pkgver"), version)
    _expect_equal(
        "stable PKGBUILD source", _single_array_assignment(stable, "source"), stable_source
    )
    _expect_equal(
        "stable PKGBUILD sha256sums",
        _single_array_assignment(stable, "sha256sums"),
        digest,
    )
    _expect_equal("stable .SRCINFO pkgver", _srcinfo_values(stable_info, "pkgver")[0], version)
    _expect_equal("stable .SRCINFO pkgrel", _srcinfo_values(stable_info, "pkgrel")[0], stable_pkgrel)
    _expect_values("stable .SRCINFO source", _srcinfo_values(stable_info, "source"), [expected_source])
    _expect_values("stable .SRCINFO checksums", _srcinfo_values(stable_info, "sha256sums"), [digest])

    description = _git(
        repo, "-c", "core.abbrev=7", "describe", "--long", "--tags", f"v{version}"
    )
    expected_vcs_version = (
        description.removeprefix("v").replace("-", ".r", 1).replace("-", ".", 1)
    )
    vcs_dir = repo / "packaging/aur/thpm-git"
    vcs = (vcs_dir / "PKGBUILD").read_text()
    vcs_info = (vcs_dir / ".SRCINFO").read_text()
    vcs_pkgrel = _assignment(vcs, "pkgrel")
    vcs_source = "git+https://github.com/oldjobobo/thpm.git"
    _expect_equal("VCS PKGBUILD pkgver", _assignment(vcs, "pkgver"), expected_vcs_version)
    _expect_equal("VCS PKGBUILD source", _single_array_assignment(vcs, "source"), vcs_source)
    _expect_equal("VCS .SRCINFO pkgver", _srcinfo_values(vcs_info, "pkgver")[0], expected_vcs_version)
    _expect_equal("VCS .SRCINFO pkgrel", _srcinfo_values(vcs_info, "pkgrel")[0], vcs_pkgrel)
    _expect_values("VCS .SRCINFO source", _srcinfo_values(vcs_info, "source"), [vcs_source])
    _expect_equal(
        "VCS PKGBUILD sha256sums",
        _single_array_assignment(vcs, "sha256sums"),
        "SKIP",
    )
    _expect_values("VCS .SRCINFO checksums", _srcinfo_values(vcs_info, "sha256sums"), ["SKIP"])
    _check_srcinfo(stable_dir)
    _check_srcinfo(vcs_dir)
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    metadata = subparsers.add_parser("metadata")
    metadata.add_argument("--require-clean", action="store_true")
    metadata.add_argument("--require-tag", action="store_true")
    artifact = subparsers.add_parser("artifact")
    artifact.add_argument("archive", type=Path)
    artifact.add_argument("checksum", type=Path)
    artifact.add_argument("--ref", default="HEAD")
    packaging = subparsers.add_parser("packaging")
    packaging.add_argument("archive", type=Path)
    packaging.add_argument("checksum", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        if args.command == "metadata":
            version = check_metadata(repo, require_clean=args.require_clean, require_tag=args.require_tag)
            print(f"Release metadata is consistent for {version}.")
        elif args.command == "artifact":
            version, digest = check_artifact(repo, args.archive, args.checksum, ref=args.ref)
            print(f"Release artifact is consistent for {version}: {digest}")
        else:
            version = check_packaging(repo, args.archive, args.checksum)
            print(f"Release packaging is consistent for {version}.")
    except (
        OSError,
        ValueError,
        IndexError,
        KeyError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        ReleaseCheckError,
    ) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
