"""Detect the host command centre and its filesystem conventions.

THPM is built around Omarchy 4. Omakub (Omabuntu) exposes the same theme-hook
and command-centre interfaces under the ``omakub`` prefix, with a few different
path layouts and without the Omarchy Shell/QML plugin system. Detection is
side-effect free so it can be used both by path properties and by the command
wrapper.
"""
from __future__ import annotations

import os
import shutil

OMAKUB = "omakub"
OMARCHY = "omarchy"

HOST_ENV = "THPM_HOST"


def host() -> str:
    """Return the detected host name: ``omarchy`` or ``omakub``.

    ``THPM_HOST`` overrides detection. It is useful for tests and for systems
    that carry both command centres; valid values are ``omarchy`` and
    ``omakub``. Otherwise the presence of the ``omakub`` command decides,
    because real Omarchy 4 installations do not ship it.
    """
    override = os.environ.get(HOST_ENV, "").strip().lower()
    if override in {OMAKUB, OMARCHY}:
        return override
    if shutil.which(OMAKUB):
        return OMAKUB
    return OMARCHY


def is_omakub() -> bool:
    return host() == OMAKUB


def command() -> str:
    """Name of the host command-centre binary to invoke."""
    return host()


def gui_supported() -> bool:
    """Whether the Omarchy Shell/QML control panel exists on this host."""
    return host() == OMARCHY
