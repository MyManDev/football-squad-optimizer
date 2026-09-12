"""Create a file exactly once, atomically, and say which of two things happened.

Several artifacts in this repository are records: a measurement, a manifest, a retained
handoff. A record is written once and never replaced in place, so the writer has to be
crash-safe and safe under concurrent writers. The bytes are completed and fsynced in a
sibling temporary file and published with a no-overwrite hard link; the temporary is
removed on every path. A losing writer compares its own bytes with the winner's and
reports a replay when they agree, and refuses when they do not.

"Create once" means exactly what ``projection_retention`` and the live ledger mean by it:
an occupant holding the same bytes is a success (``"replay"``), an occupant holding
different bytes is an error, and nothing on disk is ever overwritten.
"""

import contextlib
import json
import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path

from squadopt.data._long_paths import addressable
from squadopt.data.errors import AtomicWriteError, ConflictingBytesError

WRITTEN = "written"
REPLAY = "replay"


def write_bytes_once(
    payload: bytes,
    destination: Path,
    *,
    parse: Callable[[bytes], object] | None = None,
) -> str:
    """Publish ``payload`` at ``destination`` exactly once.

    Returns ``"written"`` when this call created the file and ``"replay"`` when the file
    already held the same bytes. ``parse`` widens what counts as the same: when given, an
    occupant whose bytes differ is read through it and compared with the parsed payload,
    so a caller can declare that, say, only a wall-clock stamp may differ. Whatever
    ``parse`` raises propagates untouched; a caller that wants a friendlier error wraps it.

    Raises ``ConflictingBytesError`` when the occupant is a different document and
    ``AtomicWriteError`` when the occupant cannot be read or the link cannot be made.
    Every path-based call goes through ``addressable`` so a destination past Windows'
    MAX_PATH is still reachable (the temporary beside it is longer than the target).
    """

    Path(addressable(destination.parent)).mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    try:
        with Path(addressable(temporary)).open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(addressable(temporary), addressable(destination))
            return WRITTEN
        except FileExistsError:
            try:
                existing_bytes = Path(addressable(destination)).read_bytes()
            except OSError as error:
                raise AtomicWriteError(
                    f"{destination} is occupied by something that cannot be read: {error}"
                ) from error
            if existing_bytes == payload:
                return REPLAY
            if parse is not None and parse(existing_bytes) == parse(payload):
                return REPLAY
            raise ConflictingBytesError(
                f"{destination} already exists with different content; a record is never "
                "overwritten in place. Choose another name or remove it deliberately."
            ) from None
        except OSError as error:
            raise AtomicWriteError(f"{destination} could not be published: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            Path(addressable(temporary)).unlink()


def document_bytes(document: Mapping[str, object]) -> bytes:
    """The one serialization a record document is written in.

    Sorted keys, two-space indent, a trailing newline, and no NaN: the same bytes for the
    same mapping on every machine, so a digest or a byte comparison identifies the document
    and not the process that wrote it.
    """

    return (json.dumps(dict(document), indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def write_document_once(
    document: Mapping[str, object],
    destination: Path,
    *,
    replay_identity: Callable[[Mapping[str, object]], object] | None = None,
) -> str:
    """Publish one JSON document under the create-once rule.

    ``replay_identity`` names the part of a document two writes of the same record must
    agree on; a caller whose document carries a wall-clock stamp passes a function that
    drops it, so a rerun replays instead of conflicting. Without it, only identical
    documents replay. An occupant that is not readable JSON is an ``AtomicWriteError``.
    """

    def parse(raw: bytes) -> object:
        try:
            loaded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AtomicWriteError(
                f"{destination} already exists but is not readable JSON."
            ) from error
        return loaded if replay_identity is None else replay_identity(loaded)

    return write_bytes_once(document_bytes(document), destination, parse=parse)


__all__: tuple[str, ...] = (
    "REPLAY",
    "WRITTEN",
    "document_bytes",
    "write_bytes_once",
    "write_document_once",
)
