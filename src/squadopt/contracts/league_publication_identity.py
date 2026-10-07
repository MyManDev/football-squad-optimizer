"""Bind current member captures and the retained league history as one publication."""

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

IDENTITY_FILE = "publication-identity.json"
IDENTITY_VERSION = "league_publication_identity_v1"
_PATH = re.compile(
    r"members\.json|entries/[1-9][0-9]*\.json|history/[1-9][0-9]*\.json|scoreboard\.json|series-horizon\.json"
)


def publication_path(name: str) -> bool:
    return _PATH.fullmatch(name) is not None


def document_digest(document: object) -> str:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def publication_identity(
    documents: Mapping[str, Any], *, source_snapshot_id: str | None = None
) -> dict[str, Any]:
    members = documents["members.json"]["payload"]
    captures = set()
    human_names = set()
    for member in members["members"]:
        if member.get("member_kind") != "human":
            continue
        name = f"entries/{member['entry_id']}.json"
        if name not in documents and member.get("data_quality") == "empty":
            continue
        human_names.add(name)
        entry = documents[name]["payload"]
        if (entry.get("season"), entry.get("gameweek"), entry.get("league_id")) != (
            members.get("season"),
            members.get("gameweek"),
            members.get("league_id"),
        ) or entry.get("entry", {}).get("entry_id") != member["entry_id"]:
            raise ValueError(f"League publication identity differs: {name}.")
        capture = entry.get("source_snapshot_id")
        if not isinstance(capture, str) or not capture:
            raise ValueError(f"League publication capture is missing: {name}.")
        captures.add(capture)
    if len(captures) > 1 or (
        captures and source_snapshot_id is not None and captures != {source_snapshot_id}
    ):
        raise ValueError("League publication contains different human entry captures.")
    if captures:
        source_snapshot_id = captures.pop()
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise ValueError("League publication requires its decision capture identity.")
    if {name for name in documents if name.startswith("entries/")} != human_names:
        raise ValueError("League publication entry inventory differs from its members.")
    if any(not publication_path(name) for name in documents):
        raise ValueError("Unsupported league publication identity path.")
    return {
        "contract_version": IDENTITY_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "league_id": members.get("league_id"),
        "season": members.get("season"),
        "gameweek": members.get("gameweek"),
        "files": {name: document_digest(doc) for name, doc in sorted(documents.items())},
    }


def verify_publication_identity(
    read: Callable[[str], Any], *, names: Iterable[str] | None = None
) -> dict[str, Any] | None:
    record = read(IDENTITY_FILE)
    if record is None:
        return None
    if not isinstance(record, dict) or record.get("contract_version") != IDENTITY_VERSION:
        raise ValueError("Unsupported league publication identity record.")
    files = record.get("files")
    if not isinstance(files, dict) or "members.json" not in files:
        raise ValueError("Incomplete league publication identity record.")
    if any(not isinstance(name, str) or not publication_path(name) for name in files):
        raise ValueError("Unsafe league publication identity path.")
    if names is not None and set(names) != set(files):
        raise ValueError("League publication file inventory changed.")
    documents = {}
    for name, digest in files.items():
        document = read(name)
        if document is None or document_digest(document) != digest:
            raise ValueError(f"League publication file changed: {name}.")
        documents[name] = document
    if (
        publication_identity(documents, source_snapshot_id=record.get("source_snapshot_id"))
        != record
    ):
        raise ValueError("League publication identity differs from its held documents.")
    return record
