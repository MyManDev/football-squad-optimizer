"""The advice cache: an immutable-key store behind a protocol, and the key itself.

Two design rules carry everything here:

- **The key is the whole identity.** Everything that could change the answer is in the
  digest — the advice contract version, the capture, the request coordinates, the
  projection handoff fingerprint, the repository commit and the configuration
  fingerprint — so a republished handoff or a new deploy simply *misses* and
  recomputes; nobody hand-invalidates a cache, ever. For a strategy that does not use
  a rival the rival is **forced to null before hashing**: two requests that differ
  only in an ignored rival must hit the same entry, or the cache multiplies work by
  the number of rivals for no reason.
- **Writes never overwrite.** A key is written once; writing identical bytes again is
  a no-op (the disposable worker's retry), and writing *different* bytes to an
  existing key is an error, because under a complete key that can only mean a
  determinism defect — the one thing a cache must never paper over. Writes go through
  a temporary file, fsynced, and an atomic create, so neither a killed worker nor a power
  loss leaves a torn entry; one left before the fsync is moved aside and computed again.

The protocol keeps the store an attached resource: the file implementation is the
first adapter, and the ADR 0005 trigger moving this to Postgres/Redis is an adapter
swap, not a rewrite.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Protocol

from squadopt.platform._damaged_entry import is_damaged, quarantine

ADVICE_CACHE_CONTRACT_VERSION: Final = "advice_cache_v1"

_KEY_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class AdviceCacheError(ValueError):
    """A cache key or write violates the store's contract."""


class AdviceCacheConflictError(AdviceCacheError):
    """Two different answers met under one complete key: a determinism defect."""


def advice_cache_key(
    *,
    advice_contract_version: str,
    capture_snapshot_id: str,
    season: str,
    gameweek: int,
    league_id: int,
    entry_id: int,
    strategy: str,
    window: int,
    projection_handoff_fingerprint: str,
    repository_commit: str,
    configuration_fingerprint: str,
    rival_entry_id: int | None = None,
    strategy_uses_rival: bool = False,
    switches: Mapping[str, Mapping[str, str | int | bool | None]] | None = None,
) -> str:
    """The complete address of one advice answer, as a SHA-256 digest.

    ``strategy_uses_rival`` is the structural guard for the forced-null rule: when the
    strategy ignores rivals, whatever rival the request carried is dropped *here*,
    before hashing, so the ignored parameter cannot split the cache. When the strategy
    uses one, the rival is part of the identity and ``None`` means the server's own
    default choice.

    ``switches`` is the switched-on part of a request: one entry per switch that is on,
    holding its value and the identity of the per-capture input it is computed from
    (``advice_switches.switch_identity``). With every switch off it is empty and the
    field is **left out of the hashed document**, so a plain request's key is the key it
    has always had and nothing already cached or queued is orphaned. A further switch
    is one more entry in the same mapping, never a new parameter here.
    """

    for label, value in (
        ("advice_contract_version", advice_contract_version),
        ("capture_snapshot_id", capture_snapshot_id),
        ("season", season),
        ("strategy", strategy),
        ("projection_handoff_fingerprint", projection_handoff_fingerprint),
        ("repository_commit", repository_commit),
        ("configuration_fingerprint", configuration_fingerprint),
    ):
        if not isinstance(value, str) or not value.strip():
            raise AdviceCacheError(f"{label} must be non-empty text.")
    for label, number in (
        ("gameweek", gameweek),
        ("league_id", league_id),
        ("entry_id", entry_id),
        ("window", window),
    ):
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise AdviceCacheError(f"{label} must be a positive integer.")
    if rival_entry_id is not None and (
        isinstance(rival_entry_id, bool)
        or not isinstance(rival_entry_id, int)
        or rival_entry_id < 1
    ):
        raise AdviceCacheError("rival_entry_id must be None or a positive integer.")
    switched: dict[str, dict[str, str | int | bool | None]] = {}
    for name, identity in (switches or {}).items():
        if not isinstance(name, str) or not name.strip() or not isinstance(identity, Mapping):
            raise AdviceCacheError("A switch must be a name mapped to its identity.")
        if not identity:
            raise AdviceCacheError(f"Switch {name!r} carries no identity; leave it out when off.")
        for part, scalar in identity.items():
            if not isinstance(part, str) or (
                scalar is not None and not isinstance(scalar, str | int | bool)
            ):
                raise AdviceCacheError(f"Switch {name!r} identity must hold JSON scalars only.")
        switched[name] = dict(identity)
    payload: dict[str, object] = {
        "cache_contract_version": ADVICE_CACHE_CONTRACT_VERSION,
        "advice_contract_version": advice_contract_version,
        "capture_snapshot_id": capture_snapshot_id,
        "season": season,
        "gameweek": gameweek,
        "league_id": league_id,
        "entry_id": entry_id,
        "strategy": strategy,
        "window": window,
        "rival_entry_id": rival_entry_id if strategy_uses_rival else None,
        "projection_handoff_fingerprint": projection_handoff_fingerprint,
        "repository_commit": repository_commit,
        "configuration_fingerprint": configuration_fingerprint,
    }
    if switched:
        payload["switches"] = switched
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AdviceCacheRepository(Protocol):
    """What any advice cache must provide; implementations are adapters."""

    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, payload: bytes) -> None: ...


class FileAdviceCache:
    """The file-backed adapter: one file per key, sharded, written atomically.

    It holds JSON documents only. The worker validates every answer as an advice document
    before publishing it, so bytes that are not JSON at a key were never written as an
    answer: they are what a crash left, and they are moved aside rather than served.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise AdviceCacheError(f"cache key must be a lowercase SHA-256 digest, got {key!r}.")
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> bytes | None:
        """The bytes at ``key``, or ``None``; an entry that is not JSON is moved aside.

        Such an entry is what a crash left before this store fsynced its writes. Returned,
        it answered 500 to every read and refused every new computation of the same key,
        until the next capture or deploy. Moved aside, the key is a miss and is computed
        again. An entry that parses but fails validation is still returned as it is.
        """

        path = self._path(key)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        if is_damaged(raw):
            quarantine(path, raw, component="cache")
            return None
        return raw

    def put(self, key: str, payload: bytes) -> None:
        """Write once. Identical bytes again: a no-op. Different bytes: a conflict.

        The no-overwrite rule is enforced by an atomic create — ``os.link`` from a
        finished temporary file onto the final name succeeds exactly once — not by a
        read followed by a replace, which two concurrent writers can both pass before
        either lands (the reviewed race: both observed the miss, the last replace won
        silently). The loser of creation reads the winner and accepts only
        byte-identical content; different bytes raise ``AdviceCacheConflictError``,
        because under a complete key that can only be a determinism defect. A killed
        writer leaves no torn entry: the final name only ever appears complete, and the
        bytes are fsynced before the link, so a power loss cannot leave the name pointing
        at bytes that never reached the disk.
        """

        if not isinstance(payload, bytes) or not payload:
            raise AdviceCacheError("payload must be non-empty bytes.")
        path = self._path(key)
        if is_damaged(payload):
            raise AdviceCacheError("payload must be a JSON document.")
        existing = self.get(key)
        if existing is not None:
            self._require_identical(key, existing, payload)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)  # atomic create; fails if the key exists
            except FileExistsError:
                winner = self.get(key)
                if winner is None:
                    raise AdviceCacheError(
                        f"Key {key[:12]}… exists but cannot be read back."
                    ) from None
                self._require_identical(key, winner, payload)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    @staticmethod
    def _require_identical(key: str, existing: bytes, payload: bytes) -> None:
        if existing != payload:
            raise AdviceCacheConflictError(
                f"Key {key[:12]}… already holds different bytes; an immutable key "
                "refuses the overwrite because this can only be a determinism defect."
            )
