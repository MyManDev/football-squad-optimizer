"""Retain exact handoff bytes by capture before publishing the legacy gameweek alias."""

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from squadopt.live import InSeasonProjection, read_projection_handoff, write_projection_handoff
from squadopt.platform._long_paths import addressable


class ProjectionRetentionError(ValueError):
    """A handoff cannot be safely preserved before replacement."""


def _safe(path: Path) -> None:
    for candidate in (path.absolute(), *path.absolute().parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise ProjectionRetentionError(
                f"Cannot publish through a symlink/reparse: {candidate}."
            )


def retained_handoff_path(root: Path, snapshot_id: str, content_sha256: str) -> Path:
    """Address exact bytes, including diagnostics excluded from the projection fingerprint."""

    if not re.fullmatch(r"[a-z0-9][A-Za-z0-9_-]{0,159}", snapshot_id) or not re.fullmatch(
        r"[0-9a-f]{64}", content_sha256
    ):
        raise ProjectionRetentionError("Invalid capture identity or content SHA-256.")
    return root / "by-capture" / snapshot_id / f"{content_sha256}.json"


def _retain(root: Path, source: Path) -> Path:
    projection = read_projection_handoff(source)
    raw = source.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    target = retained_handoff_path(root, projection.source_snapshot_id, checksum)
    _safe(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".retain-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Validate the bytes actually retained, not only the earlier source read.
        retained = read_projection_handoff(temporary)
        if retained.source_snapshot_id != projection.source_snapshot_id:
            raise ProjectionRetentionError("Handoff changed while retaining its capture identity.")
        # os.link stays the primitive on both platforms: it is the one that fails with
        # FileExistsError instead of overwriting, which is how create-once is enforced.
        # Only the addressing differs - the retained name is long enough to fall outside
        # Windows' MAX_PATH, and addressable() is what puts it back in range there.
        try:
            os.link(addressable(temporary), addressable(target))
        except FileExistsError:
            if Path(addressable(target)).read_bytes() != raw:
                raise ProjectionRetentionError(
                    f"Existing retained bytes are corrupt: {target}."
                ) from None
    finally:
        temporary.unlink(missing_ok=True)
    return target


def publish_retained_handoff(path: Path, projection: InSeasonProjection) -> Path:
    """Preserve the old and new handoffs, then atomically replace the compatible alias.

    Producers must be serialized. An interrupted publication may leave an extra retained
    handoff, but never needs to overwrite retained history. This is process-crash safety,
    not a claim about host power loss or remote filesystem atomicity.
    """

    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _retain(path.parent, path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".handoff-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write_projection_handoff(temporary, projection)
        _retain(path.parent, temporary)
        # Windows requires a writable handle for fsync/_commit.
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
