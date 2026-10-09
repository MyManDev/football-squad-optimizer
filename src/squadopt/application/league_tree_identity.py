"""Record the complete protected league set after a normal writer finishes."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from squadopt.contracts.league_publication_identity import (
    IDENTITY_FILE,
    publication_identity,
    publication_path,
    verify_publication_identity,
)
from squadopt.data._long_paths import addressable
from squadopt.data.atomic import document_bytes, replace_retrying


def protected_files(tree: Path) -> dict[str, Path]:
    readable = Path(addressable(tree))
    return {
        path.relative_to(readable).as_posix(): tree / path.relative_to(readable)
        for path in sorted(readable.rglob("*.json"))
        if publication_path(path.relative_to(readable).as_posix())
    }


def check_tree_identity(tree: Path) -> dict[str, Any] | None:
    def read(name: str) -> Any:
        path = Path(addressable(tree / name))
        return json.loads(path.read_bytes()) if path.is_file() else None

    return verify_publication_identity(read, names=protected_files(tree))


def record_tree_identity(tree: Path, *, source_snapshot_id: str | None = None) -> Path:
    documents = {
        name: json.loads(Path(addressable(path)).read_bytes())
        for name, path in protected_files(tree).items()
    }
    record = publication_identity(documents, source_snapshot_id=source_snapshot_id)
    target = tree / IDENTITY_FILE
    temporary = tree / (IDENTITY_FILE + ".tmp-" + uuid4().hex)
    try:
        Path(addressable(temporary)).write_bytes(document_bytes(record))
        replace_retrying(temporary, target)
    finally:
        Path(addressable(temporary)).unlink(missing_ok=True)
    check_tree_identity(tree)
    return target
