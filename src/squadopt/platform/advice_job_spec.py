"""What a queued job is *for*, kept beside the queue rather than inside it.

``AdviceJob`` carries three identities and every one of them is a one-way SHA-256 digest:
``job_id`` names the record, ``request_fingerprint`` names the normalized request, and
``cache_key`` names the answer's address. That separation is deliberate and correct —
conflating any two of them is how a cache serves one member another member's plan — but it
leaves a worker that has claimed a job unable to say which member, strategy or rival it was
asked about. A digest does not invert.

So the request travels beside the job. The submission service writes one spec at the
answer's own address before the job is enqueued; the worker reads it back by
``job.cache_key``. Two things follow from choosing this over widening ``AdviceJob``:

- ``BACKEND_JOBS_CONTRACT_VERSION``, its JSON schema and the public job view are untouched,
  so nothing a client or another service already reads changes shape;
- the spec records the context the request was **accepted under**, which is what lets the
  worker tell "this is still the capture I can answer from" apart from "the deployment has
  moved on and this job's inputs are gone".

Specs are write-once at their key, by the same atomic create the advice cache uses. Many
requests share one key by design; they must therefore agree about what that key means, and
two different meanings under one address is a defect worth raising rather than resolving.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from squadopt.platform._damaged_entry import (
    PUBLISH_ATTEMPTS,
    is_damaged,
    quarantine,
    read_entry,
)
from squadopt.platform.advice_read import AdviceRequestContext

__all__ = [
    "ADVICE_JOB_SPEC_CONTRACT_VERSION",
    "AdviceJobSpec",
    "AdviceJobSpecConflictError",
    "AdviceJobSpecError",
    "AdviceJobSpecStore",
    "FileAdviceJobSpecStore",
]

ADVICE_JOB_SPEC_CONTRACT_VERSION: Final = "advice_job_spec_v1"

_KEY_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class AdviceJobSpecError(ValueError):
    """A spec cannot be read, written, or trusted."""


class AdviceJobSpecConflictError(AdviceJobSpecError):
    """One key already means something else: two requests disagree about an address."""


@dataclass(frozen=True, slots=True)
class AdviceJobSpec:
    """The request a job answers, and the context it was accepted under."""

    league_id: int
    entry_id: int
    strategy: str
    window: int
    context: AdviceRequestContext
    rival_entry_id: int | None = None
    contract_version: str = ADVICE_JOB_SPEC_CONTRACT_VERSION
    switches: Mapping[str, Mapping[str, str | int | bool | None]] = field(default_factory=dict)
    """The switched-on part of the request, exactly as it entered the cache key: each
    switch's value and the identity of the input it was accepted against. Empty for a plain
    request, and then absent from the stored bytes, so a plain spec is the spec it has
    always been. The worker reads the values from here and refuses to compute against an
    input whose identity has since changed."""

    def __post_init__(self) -> None:
        if self.contract_version != ADVICE_JOB_SPEC_CONTRACT_VERSION:
            raise AdviceJobSpecError("Unsupported advice job spec contract_version.")
        for label, value in (
            ("league_id", self.league_id),
            ("entry_id", self.entry_id),
            ("window", self.window),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise AdviceJobSpecError(f"{label} must be a positive integer.")
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise AdviceJobSpecError("strategy must be non-empty text.")
        if self.rival_entry_id is not None and (
            isinstance(self.rival_entry_id, bool)
            or not isinstance(self.rival_entry_id, int)
            or self.rival_entry_id < 1
        ):
            raise AdviceJobSpecError("rival_entry_id must be None or a positive integer.")
        if not isinstance(self.context, AdviceRequestContext):
            raise AdviceJobSpecError("context must be an AdviceRequestContext.")
        if not isinstance(self.switches, Mapping):
            raise AdviceJobSpecError("switches must be a mapping of switch name to identity.")
        normalized: dict[str, dict[str, str | int | bool | None]] = {}
        for name, identity in self.switches.items():
            if not isinstance(name, str) or not name.strip():
                raise AdviceJobSpecError("A switch name must be non-empty text.")
            if not isinstance(identity, Mapping) or not identity:
                raise AdviceJobSpecError(f"Switch {name!r} must carry its identity.")
            for part, scalar in identity.items():
                if not isinstance(part, str) or (
                    scalar is not None and not isinstance(scalar, str | int | bool)
                ):
                    raise AdviceJobSpecError(f"Switch {name!r} must hold JSON scalars only.")
            normalized[name] = dict(identity)
        object.__setattr__(self, "switches", normalized)

    def switch(self, name: str) -> Mapping[str, str | int | bool | None]:
        """One switch's recorded identity; empty when it was off."""

        return self.switches.get(name, {})

    def as_payload(self) -> dict[str, object]:
        payload = self._plain_payload()
        if self.switches:
            payload["switches"] = {name: dict(value) for name, value in self.switches.items()}
        return payload

    def _plain_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "league_id": self.league_id,
            "entry_id": self.entry_id,
            "strategy": self.strategy,
            "window": self.window,
            "rival_entry_id": self.rival_entry_id,
            "context": {
                "advice_contract_version": self.context.advice_contract_version,
                "capture_snapshot_id": self.context.capture_snapshot_id,
                "season": self.context.season,
                "gameweek": self.context.gameweek,
                "projection_handoff_fingerprint": self.context.projection_handoff_fingerprint,
                "repository_commit": self.context.repository_commit,
                "configuration_fingerprint": self.context.configuration_fingerprint,
            },
        }

    @classmethod
    def from_payload(cls, payload: object) -> AdviceJobSpec:
        if not isinstance(payload, Mapping):
            raise AdviceJobSpecError("An advice job spec must be a JSON object.")
        context = payload.get("context")
        if not isinstance(context, Mapping):
            raise AdviceJobSpecError("An advice job spec must carry its context.")
        try:
            request_context = AdviceRequestContext(
                advice_contract_version=str(context["advice_contract_version"]),
                capture_snapshot_id=str(context["capture_snapshot_id"]),
                season=str(context["season"]),
                gameweek=int(str(context["gameweek"])),
                projection_handoff_fingerprint=str(context["projection_handoff_fingerprint"]),
                repository_commit=str(context["repository_commit"]),
                configuration_fingerprint=str(context["configuration_fingerprint"]),
            )
            rival = payload.get("rival_entry_id")
            return cls(
                league_id=int(str(payload["league_id"])),
                entry_id=int(str(payload["entry_id"])),
                strategy=str(payload["strategy"]),
                window=int(str(payload["window"])),
                context=request_context,
                rival_entry_id=None if rival is None else int(str(rival)),
                contract_version=str(payload.get("contract_version", "")),
                switches=payload.get("switches", {}),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AdviceJobSpecError(f"Malformed advice job spec: {error}") from error


class AdviceJobSpecStore(Protocol):
    """Where a job's request waits for whichever worker claims it."""

    def get(self, key: str) -> AdviceJobSpec | None: ...

    def put(self, key: str, spec: AdviceJobSpec) -> None: ...


class FileAdviceJobSpecStore:
    """One file per key on the shared mount, written by atomic create.

    The same create-once idiom as the advice cache, for the same reason: two api replicas
    can submit the same request at the same instant, and a read-then-write would let both
    pass the miss before either landed.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise AdviceJobSpecError(f"spec key must be a lowercase SHA-256 digest, got {key!r}.")
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> AdviceJobSpec | None:
        raw = read_entry(self._path(key))
        if raw is None:
            return None
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            # The same refusal as a well-formed document with the wrong fields: the worker
            # records either as a request it cannot read, never as a failed computation.
            raise AdviceJobSpecError("The stored advice job spec is not JSON.") from error
        return AdviceJobSpec.from_payload(document)

    def put(self, key: str, spec: AdviceJobSpec) -> None:
        """Write once. The same meaning again is a no-op; a different one is a defect.

        A spec that is not JSON at all is neither: it is what a crash left before this store
        fsynced its writes. It is moved aside and the address written again, where it used
        to answer every later request for the same answer with 409 ``REQUEST_CONFLICT``.
        The bytes are fsynced before the link, so this write cannot leave one behind.
        """

        payload = _serialize(spec)
        path = self._path(key)
        existing = self._read(path)
        if existing is not None and is_damaged(existing):
            quarantine(path, existing, component="specs")
            existing = None
        if existing is not None:
            _require_identical(key, existing, payload)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for _attempt in range(PUBLISH_ATTEMPTS):
                try:
                    os.link(temporary, path)  # atomic create; fails if the key exists
                    return
                except FileExistsError:
                    winner = self._read(path)
                if winner is not None:
                    _require_identical(key, winner, payload)
                    return
                # Gone before it could be read: another request that read the damage
                # before this spec was written moved it aside, and is linking it back.
            raise AdviceJobSpecError(f"Spec {key[:12]}… exists but cannot be read back.")
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    @staticmethod
    def _read(path: Path) -> bytes | None:
        return read_entry(path)


def _serialize(spec: AdviceJobSpec) -> bytes:
    return json.dumps(spec.as_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_identical(key: str, existing: bytes, payload: bytes) -> None:
    if existing != payload:
        raise AdviceJobSpecConflictError(
            f"Key {key[:12]}… already describes a different request; one address may "
            "only ever mean one question."
        )
