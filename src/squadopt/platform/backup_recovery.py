"""Offline, checksummed copies of explicitly selected private filesystem roots.

Writers must be stopped across every selected root. Hash checks detect a changed copy;
they do not create a transaction across a running publisher, ledger and job queue.
No source is deleted, no existing destination is overwritten, and no retention policy
or external storage provider is selected here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_SCHEMA_VERSION = "private_backup_v1"
MANIFEST_NAME = "manifest.json"
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class BackupError(ValueError):
    """A copy cannot be completed or independently verified safely."""


@dataclass(frozen=True, slots=True)
class BackupReceipt:
    manifest_sha256: str
    file_count: int
    total_bytes: int


def _path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise BackupError("Manifest paths must be nonempty relative POSIX paths.")
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or any(character in part for character in '\\:*?"<>|')
        or any(ord(character) < 32 for character in part)
        or part.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        for part in parts
    ):
        raise BackupError(f"Unsafe or nonportable manifest path: {value!r}.")
    return value


def _safe_path(path: Path) -> Path:
    """Reject symlinks/junctions, including existing ancestors of a new target."""

    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise BackupError(f"Symlink/reparse paths are not supported: {candidate}.")
    return absolute


def _disjoint(paths: Sequence[Path]) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise BackupError(f"Roots and destinations must not overlap: {left}, {right}.")


def _hash(path: Path) -> tuple[int, str]:
    _safe_path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise BackupError(f"Only regular files can be copied: {path}.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(_CHUNK):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def _inventory(roots: Mapping[str, Path]) -> tuple[list[str], list[dict[str, Any]]]:
    directories: list[str] = []
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, root in sorted(roots.items()):
        if not _NAME.fullmatch(name) or not root.is_dir():
            raise BackupError(f"Each root needs a simple name and an existing directory: {name}.")
        pending = [(root, name)]
        while pending:
            directory, relative = pending.pop()
            _safe_path(directory)
            directories.append(relative)
            for child in sorted(directory.iterdir()):
                _safe_path(child)
                location = _path(f"{relative}/{child.name}")
                if location.casefold() in seen:
                    raise BackupError(f"Case-insensitive path collision: {location}.")
                seen.add(location.casefold())
                if child.is_dir():
                    pending.append((child, location))
                else:
                    size, checksum = _hash(child)
                    files.append({"path": location, "size": size, "sha256": checksum})
    return sorted(directories), sorted(files, key=lambda row: row["path"])


def _empty_target(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise BackupError(f"Destination must be absent or an empty directory: {path}.")
    elif not path.parent.is_dir():
        raise BackupError(f"Create the destination's parent directory first: {path.parent}.")


def _copy(source: Path, destination: Path, row: Mapping[str, Any]) -> None:
    _safe_path(source)
    _safe_path(destination)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while block := reader.read(_CHUNK):
            writer.write(block)
            digest.update(block)
            size += len(block)
        writer.flush()
        os.fsync(writer.fileno())
    if size != row["size"] or digest.hexdigest() != row["sha256"]:
        raise BackupError(f"Source changed during copy: {row['path']}.")


def _receipt(document: Mapping[str, Any], manifest: bytes) -> BackupReceipt:
    return BackupReceipt(
        hashlib.sha256(manifest).hexdigest(),
        len(document["files"]),
        sum(row["size"] for row in document["files"]),
    )


def _manifest(backup: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    if not _SHA256.fullmatch(expected_sha256):
        raise BackupError("Supply the SHA-256 from the separately retained creation receipt.")
    manifest_path = _safe_path(backup / MANIFEST_NAME)
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise BackupError("Manifest SHA-256 does not match the creation receipt.")
    document = json.loads(raw)
    keys = {"schema_version", "created_at_utc", "consistency", "roots", "directories", "files"}
    if not isinstance(document, dict) or set(document) != keys:
        raise BackupError("Invalid backup manifest object.")
    if document["schema_version"] != BACKUP_SCHEMA_VERSION or document["consistency"] != (
        "writers_stopped"
    ):
        raise BackupError("Unsupported backup schema or consistency declaration.")
    stamp = document["created_at_utc"]
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        raise BackupError("Manifest creation time must be UTC.")
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    roots = document["roots"]
    if (
        not isinstance(roots, list)
        or not roots
        or any(not isinstance(name, str) or not _NAME.fullmatch(name) for name in roots)
        or roots != sorted(set(roots))
    ):
        raise BackupError("Invalid manifest root names.")
    directories, files = document["directories"], document["files"]
    if not isinstance(directories, list) or not isinstance(files, list):
        raise BackupError("Manifest files and directories must be arrays.")
    paths = [_path(value) for value in directories]
    for row in files:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            raise BackupError("Invalid file record.")
        paths.append(_path(row["path"]))
        if (
            type(row["size"]) is not int
            or row["size"] < 0
            or not isinstance(row["sha256"], str)
            or not _SHA256.fullmatch(row["sha256"])
        ):
            raise BackupError("Invalid file size or SHA-256.")
    if len(paths) != len({path.casefold() for path in paths}):
        raise BackupError("Manifest contains duplicate or colliding paths.")
    directory_set = set(directories)
    if not set(roots).issubset(directory_set):
        raise BackupError("Every root must have a directory record.")
    for path in paths:
        if path.split("/")[0] not in roots or (
            "/" in path and path.rsplit("/", 1)[0] not in directory_set
        ):
            raise BackupError("Manifest path has an undeclared root or parent directory.")
    return document, raw


def _verify_tree(document: Mapping[str, Any], directory: Path) -> None:
    expected_roots = set(document["roots"])
    _safe_path(directory)
    if not directory.is_dir() or {child.name for child in directory.iterdir()} != expected_roots:
        raise BackupError("Backup/restore tree has missing or unexpected roots.")
    directories, files = _inventory({name: directory / name for name in expected_roots})
    if directories != sorted(document["directories"]) or files != sorted(
        document["files"], key=lambda row: row["path"]
    ):
        raise BackupError("Backup/restore paths, sizes or SHA-256 checksums do not match.")


def create_backup(
    roots: Mapping[str, Path | str], destination: Path | str, *, writers_stopped: bool
) -> BackupReceipt:
    """Copy all selected roots; publish the completion manifest only after verification."""

    if not writers_stopped:
        raise BackupError("Stop every writer before backing up the selected roots.")
    if not roots:
        raise BackupError("Select at least one explicit source root.")
    sources = {name: _safe_path(Path(path)) for name, path in roots.items()}
    target = _safe_path(Path(destination))
    _disjoint([*sources.values(), target])
    _empty_target(target)
    directories, files = _inventory(sources)
    document = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "consistency": "writers_stopped",
        "roots": sorted(sources),
        "directories": directories,
        "files": files,
    }
    target.mkdir(exist_ok=True)
    payload_root = target / "files"
    payload_root.mkdir()
    for relative in directories:
        (payload_root / relative).mkdir()
    for row in files:
        root_name, relative = row["path"].split("/", 1)
        _copy(sources[root_name] / relative, payload_root / row["path"], row)
    if _inventory(sources) != (directories, files):
        raise BackupError("Source tree changed during backup; no completion manifest published.")
    _verify_tree(document, payload_root)
    raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with (target / MANIFEST_NAME).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return _receipt(document, raw)


def verify_backup(backup: Path | str, *, manifest_sha256: str) -> BackupReceipt:
    """Verify every byte and the exact file set against a separately held manifest hash."""

    directory = _safe_path(Path(backup))
    document, raw = _manifest(directory, manifest_sha256)
    if {child.name for child in directory.iterdir()} != {MANIFEST_NAME, "files"}:
        raise BackupError("Backup has unexpected top-level entries.")
    _verify_tree(document, directory / "files")
    return _receipt(document, raw)


def restore_backup(
    backup: Path | str,
    destination: Path | str,
    *,
    manifest_sha256: str,
    writers_stopped: bool,
) -> BackupReceipt:
    """Verify first, restore to an empty target, then verify the complete restored tree."""

    if not writers_stopped:
        raise BackupError("The isolated restore target must have no active writers.")
    source, target = _safe_path(Path(backup)), _safe_path(Path(destination))
    _disjoint([source, target])
    _empty_target(target)
    receipt = verify_backup(source, manifest_sha256=manifest_sha256)
    document, _ = _manifest(source, manifest_sha256)
    target.mkdir(exist_ok=True)
    for relative in sorted(document["directories"]):
        (target / relative).mkdir()
    for row in document["files"]:
        _copy(source / "files" / row["path"], target / row["path"], row)
    _verify_tree(document, target)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Copy explicit roots while all writers are stopped")
    create.add_argument("--root", action="append", required=True, metavar="NAME=PATH")
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--writers-stopped", action="store_true", required=True)
    for command in ("verify", "restore"):
        sub = commands.add_parser(command)
        sub.add_argument("--backup", type=Path, required=True)
        sub.add_argument("--manifest-sha256", required=True)
        if command == "restore":
            sub.add_argument("--destination", type=Path, required=True)
            sub.add_argument("--writers-stopped", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            roots: dict[str, Path] = {}
            for item in args.root:
                name, separator, value = item.partition("=")
                if not separator or not value or name in roots:
                    raise BackupError("Supply unique --root NAME=PATH entries.")
                roots[name] = Path(value)
            receipt = create_backup(roots, args.destination, writers_stopped=args.writers_stopped)
        elif args.command == "restore":
            receipt = restore_backup(
                args.backup,
                args.destination,
                manifest_sha256=args.manifest_sha256,
                writers_stopped=args.writers_stopped,
            )
        else:
            receipt = verify_backup(args.backup, manifest_sha256=args.manifest_sha256)
    except (BackupError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
        return 1
    print(json.dumps({"status": "verified", **asdict(receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
