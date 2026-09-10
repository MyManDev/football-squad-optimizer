"""Reach filesystem paths that Windows' MAX_PATH would otherwise put out of range."""

from __future__ import annotations

import os
from pathlib import Path


def addressable(path: Path) -> str:
    r"""Render a path so a path-based call can reach it however long it is.

    Measured on the owner's machine (Windows 11, LongPathsEnabled=0, Python 3.13): every
    path-based call - os.link, os.rename, os.replace, open() and os.stat alike - fails with
    FileNotFoundError/WinError 3 once the absolute path reaches 260 characters, and all of
    them succeed at 259. Nothing here is specific to hard links; what differs between calls
    is only the length of the name each one writes. A retained handoff name is
    "<sha256>.json", 69 characters, 53 more than the ".retain-XXXXXXXX" temporary created
    beside it, so a deep pytest basetemp puts the temporary under the cap (221 characters)
    and the target over it (274) - which is why creating the temporary succeeded and only
    publishing it failed. The extended-length prefix lifts the cap for the call it is
    passed to; it changes nothing else, so error semantics are unchanged (os.link still
    raises FileExistsError on an existing target at 274 and 300 characters, measured).

    POSIX has no such cap and needs no prefix, so the returned string is the path itself.
    """

    if os.name != "nt":
        return str(path)
    resolved = os.path.abspath(path)
    if resolved.startswith(("\\\\?\\", "\\\\.\\")):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


__all__: tuple[str, ...] = ("addressable",)
