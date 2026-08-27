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
  a temporary file and an atomic replace, so a killed worker leaves no torn entry.

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
from pathlib import Path
from typing import Final, Protocol

ADVICE_CACHE_CONTRACT_VERSION: Final = "advice_cache_v1"

_KEY_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class AdviceCacheError(ValueError):
    """A cache key or write violates the store's contract."""


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
) -> str:
    """The complete address of one advice answer, as a SHA-256 digest.

    ``strategy_uses_rival`` is the structural guard for the forced-null rule: when the
    strategy ignores rivals, whatever rival the request carried is dropped *here*,
    before hashing, so the ignored parameter cannot split the cache. When the strategy
    uses one, the rival is part of the identity and ``None`` means the server's own
    default choice.
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
    payload = {
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
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AdviceCacheRepository(Protocol):
    """What any advice cache must provide; implementations are adapters."""

    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, payload: bytes) -> None: ...


class FileAdviceCache:
    """The file-backed adapter: one file per key, sharded, written atomically."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise AdviceCacheError(f"cache key must be a lowercase SHA-256 digest, got {key!r}.")
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, payload: bytes) -> None:
        """Write once. Identical bytes again: a no-op. Different bytes: an error.

        Under a complete key a second, different answer can only mean a determinism
        defect, and a cache that silently keeps either version papers over exactly
        the property the rest of this repository measures. The write lands through a
        temporary file and an atomic replace so a killed worker leaves no torn entry.
        """

        if not isinstance(payload, bytes) or not payload:
            raise AdviceCacheError("payload must be non-empty bytes.")
        path = self._path(key)
        existing = self.get(key)
        if existing is not None:
            if existing == payload:
                return
            raise AdviceCacheError(
                f"Key {key[:12]}… already holds different bytes; an immutable key "
                "refuses the overwrite because this can only be a determinism defect."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
