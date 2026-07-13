"""Omarchy 4-native Theme Hook Plugin Manager."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

source_version = Path(__file__).resolve().parents[2] / "VERSION"
if source_version.is_file():
    __version__ = source_version.read_text().strip()
else:
    try:
        __version__ = version("thpm")
    except PackageNotFoundError:
        __version__ = "1.1.0"
