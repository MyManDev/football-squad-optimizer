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
from pathlib import Path

from squadopt.data.atomic import replace_retrying
from squadopt.platform.advice_observability import AdviceLog

DAMAGED_ENTRY_EVENT = "advice_damaged_entry_quarantined"


def is_damaged(raw: bytes) -> bool:
    """True when ``raw`` is not a JSON document at all (empty, truncated, zero-filled)."""

    try:
        json.loads(raw)
    except ValueError:  # includes JSONDecodeError and UnicodeDecodeError
        return True
    return False


def quarantine(path: Path, damaged: bytes, *, component: str) -> None:
    """Move ``damaged``, just read from ``path``, to a sibling name and log it.

    The address is free afterwards, whichever caller moved it: a caller that finds the file
    already gone lost the race to another reader and has nothing left to do. The moved
    file is compared with what was read, because a writer may have published a whole entry
    between that read and the move; such an entry is linked back and nothing is logged.
    """

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    aside = path.with_name(f"{path.name}.damaged-{stamp}-{secrets.token_hex(4)}")
    try:
        replace_retrying(path, aside)
    except FileNotFoundError:
        return
    if aside.read_bytes() != damaged:
        with contextlib.suppress(FileExistsError):
            os.link(aside, path)
        aside.unlink()
        return
    AdviceLog(component).event(
        DAMAGED_ENTRY_EVENT,
        source=path.name,
        moved_to=aside.name,
        size=len(damaged),
        sha256=hashlib.sha256(damaged).hexdigest(),
    )
