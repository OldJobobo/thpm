"""Omarchy 4-native Theme Hook Plugin Manager."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("thpm")
except PackageNotFoundError:
    __version__ = "1.0.0rc4"
