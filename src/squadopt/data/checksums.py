"""Content digests over raw bytes.

One digest for the whole package: a captured snapshot payload, a residual export and a
settled-outcomes table all record the SHA-256 of the exact bytes on disk, and they must
agree on what that means so a manifest written by one module can be checked by another.
"""

import hashlib
from pathlib import Path

from squadopt.data.errors import DataSourceError


def sha256_of_bytes(content: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of raw bytes."""

    return hashlib.sha256(content).hexdigest()


def compute_table_sha256(path: Path) -> str:
    """Return the lowercase SHA-256 of the exact file bytes a manifest names."""

    if not path.is_file():
        raise DataSourceError(f"Table file does not exist: {path}.")
    return sha256_of_bytes(path.read_bytes())
