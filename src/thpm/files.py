from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def atomic_text(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".thpm-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def atomic_copy(source: Path, target: Path, mode: int = 0o644) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".thpm-", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, name)
        os.chmod(name, mode)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def remove_managed_block(text: str, start: str, end: str) -> str:
    if start not in text and end not in text:
        return text
    before, separator, rest = text.partition(start)
    if not separator or end not in rest:
        raise ValueError("incomplete THPM managed block")
    _, _, after = rest.partition(end)
    return (before.rstrip() + "\n" + after.lstrip()).strip() + "\n"
