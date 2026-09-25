"""Bytes at a create-once address that do not parse: moved aside, not answered from.

The advice cache and the job-spec store publish by hard-linking a finished temporary file
onto the final name, so while the machine stays up that name only ever holds whole bytes.
Until both stores fsynced the temporary first, a power loss or an OS crash could leave the
name pointing at bytes that never reached the disk. Those bytes are neither an answer nor a
request, and under the create-once rule they held the address for good: the cache answered
500 and the spec store 409 until someone deleted the file by hand. So they are moved to a
sibling name, kept for inspection, logged with their digest, and the next writer writes the
address again.

Only bytes that are not JSON at all count as damage. What a crash leaves of a JSON object
(nothing, a prefix of it, or blocks of zeros) does not parse; a document that parses but is
wrong is a writer's defect, and the stores keep refusing it exactly as before.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeVar

from squadopt.data.atomic import replace_retrying
from squadopt.platform.advice_observability import AdviceLog

DAMAGED_ENTRY_EVENT = "advice_damaged_entry_quarantined"

SETTLE_ATTEMPTS: Final = 8
"""How many times a file operation refused with ``PermissionError`` is attempted in all."""
SETTLE_INITIAL_SECONDS: Final = 0.002
"""The first pause before a retry; it doubles, so eight attempts span 0.25 s of waiting."""

PUBLISH_ATTEMPTS: Final = 5
"""How many times a store links its entry when the one that refused the link is gone before
it can be read: a caller that read damage at the key before it was written again moved the
whole entry aside, and links it back a moment later."""

_T = TypeVar("_T")


def is_damaged(raw: bytes) -> bool:
    """True when ``raw`` is not a JSON document at all (empty, truncated, zero-filled)."""

    try:
        json.loads(raw)
    except ValueError:  # includes JSONDecodeError and UnicodeDecodeError
        return True
    return False


def _settled(operation: Callable[[], _T]) -> _T:
    """``operation()``, retried for a moment while Windows refuses it with ``PermissionError``.

    Windows refuses a read of a file while another caller's rename of the same file is in
    flight, and the same read succeeds a moment later. Linking the file back and removing
    its sibling name are retried the same way. The last refusal is raised as it is:
    something that holds the file for longer is not a rename.
    """

    delay = SETTLE_INITIAL_SECONDS
    for _attempt in range(SETTLE_ATTEMPTS - 1):
        try:
            return operation()
        except PermissionError:
            time.sleep(delay)
            delay *= 2
    return operation()


def read_entry(path: Path) -> bytes | None:
    """The bytes at ``path``, or ``None`` when nothing is there.

    A read refused while another caller moves the same file aside is retried; once the move
    lands, the name holds nothing or whatever a writer published since.
    """

    try:
        return _settled(path.read_bytes)
    except FileNotFoundError:
        return None


def quarantine(path: Path, damaged: bytes, *, component: str) -> None:
    """Move ``damaged``, just read from ``path``, to a sibling name and log it.

    Several callers can read the same damage and move it at once. Where a rename moves the
    file by name, every caller after the first finds it gone and stops. Windows renames
    through an open handle, so two callers that opened the file before either moved it
    both succeed, and the file ends under the name of the rename that landed last. Each
    caller therefore reads back what is under its own sibling name: if nothing is, a later
    move took the file and that caller finishes the job. Only the caller holding the file
    compares it with what was read, because a writer may have published a whole entry
    between that read and the move. Such an entry is linked back (for that moment the key
    reads as a miss) and nothing is logged; damage is logged by the caller holding it.
    """

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    aside = path.with_name(f"{path.name}.damaged-{stamp}-{secrets.token_hex(4)}")
    try:
        replace_retrying(path, aside)
    except FileNotFoundError:
        return
    moved = read_entry(aside)
    if moved is None:
        return
    if moved != damaged:
        try:
            _settled(lambda: os.link(aside, path))
        except FileExistsError:
            pass  # a writer published the same key again meanwhile
        except FileNotFoundError:
            return  # a later move took the file from this name; that caller links it back
        with contextlib.suppress(FileNotFoundError):
            _settled(aside.unlink)
        return
    AdviceLog(component).event(
        DAMAGED_ENTRY_EVENT,
        source=path.name,
        moved_to=aside.name,
        size=len(damaged),
        sha256=hashlib.sha256(damaged).hexdigest(),
    )
