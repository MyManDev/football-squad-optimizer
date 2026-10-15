"""The inputs of the football prospective protocol, read without the advice backend.

Shared by ``check_football_prospective_inputs.py`` and the scoring runner the protocol
names. Three rules live here, as ``docs/football_prospective_pairing_note.md`` states them:

- the scored capture of a gameweek: the last ``fpl-live`` capture, by capture instant,
  whose own target is the gameweek;
- the shadow football artifact of that capture, with the receipt
  ``scripts/build_football_shadow.py`` wrote beside it, checked against the artifact's
  bytes, fingerprint and digest;
- default 1, the pairing of the current arm: the handoff the published plans used, named
  by the pre-deadline member advice records (branch a); the backend's own rule when the
  capture has no such record (branch b), under which a late file makes the week a
  replay; and otherwise a missing week (branch c).

Nothing here imports the backend's platform package, so the backend can be retired
without breaking either prospective script. Branch b is this module's own copy of the
backend's selection, and ``backend_rule_fingerprint`` reports what that rule selects at
reading time whichever branch paired the week. A handoff or record file that exists but
raises ``OSError`` when read is a refusal of the run, not a missing week: the exception
is raised to the caller rather than read as an absence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.application.advice_record import AdviceRecordError, load_member_advice_record
from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.football_artifact import (
    FootballForecast,
    football_artifact_path,
    read_football_forecast,
)
from squadopt.live.recommendation import (
    InSeasonProjection,
    RecommendationInputs,
    read_projection_handoff,
)
from squadopt.live.tick import handoff_path_for
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

#: The protocol's reason for a week whose current arm cannot be paired.
UNPAIRED_REASON = "cannot pair the scored capture with exactly one handoff"

#: The contract the shadow builder writes; pinned to the builder's constant by a test.
SHADOW_RECEIPT_CONTRACT = "football_shadow_receipt_v1"

#: The branches of default 1, as the note names them.
BRANCH_PUBLISHED_RECORD = "a"
BRANCH_BACKEND_RULE = "b"
BRANCH_MISSING = "c"


def _utc_text(instant: datetime) -> str:
    return instant.astimezone(UTC).isoformat()


def _write_instant(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


@dataclass(frozen=True)
class ScoredCapture:
    """The capture a gameweek is scored from, or why it has none.

    ``reason`` is ``no_own_target_capture`` when no capture of the inventory targets the
    gameweek and ``ambiguous_latest_capture`` when two share the last instant; it is
    ``None`` exactly when ``inputs`` is set.
    """

    gameweek: int
    inputs: RecommendationInputs | None
    reason: str | None


def scored_capture(captures: Sequence[RecommendationInputs], gameweek: int) -> ScoredCapture:
    """The last capture, by capture instant, whose own target is ``gameweek``."""

    eligible = [item for item in captures if int(item.deadline.gameweek) == gameweek]
    if not eligible:
        return ScoredCapture(gameweek, None, "no_own_target_capture")
    latest = max(as_instant(item.captured_at_utc) for item in eligible)
    selected = [item for item in eligible if as_instant(item.captured_at_utc) == latest]
    if len(selected) != 1:
        return ScoredCapture(gameweek, None, "ambiguous_latest_capture")
    return ScoredCapture(gameweek, selected[0], None)


@dataclass(frozen=True)
class ShadowArtifact:
    """The football arm of one scored capture, read from the artifact root.

    ``status`` is ``usable``, ``late`` (a readable v1 artifact written at or after the
    deadline, or after ``as_of`` when one is given), ``missing`` (no file) or ``invalid``
    (unreadable, failing its digest, or not v1). ``forecast`` is set for ``usable`` and
    ``late``. ``receipt_matches`` is true only when the receipt beside the artifact
    names the artifact's bytes and fingerprint and records ``served: false``;
    ``receipt_status`` says why it does not. ``football_served`` is what the receipt
    records, and ``None`` when no receipt could be read.
    """

    path: Path
    status: str
    forecast: FootballForecast | None
    write_utc: str | None
    sha256: str | None
    receipt_path: Path
    receipt_status: str
    receipt_matches: bool
    football_served: bool | None


def _read_receipt(receipt_path: Path) -> tuple[str, dict[str, Any] | None]:
    """The receipt document, or the status that says why it could not be read."""

    if not receipt_path.is_file():
        return "absent", None
    try:
        document = json.loads(receipt_path.read_text(encoding="utf-8"))
    except ValueError:
        return "unreadable", None
    if not isinstance(document, dict) or document.get("contract_version") != (
        SHADOW_RECEIPT_CONTRACT
    ):
        return "not_a_receipt", None
    if not isinstance(document.get("served"), bool):
        return "served_not_recorded", None
    return "read", document


def _receipt_status(
    receipt_path: Path, *, snapshot_id: str, sha256: str, fingerprint: str | None
) -> tuple[str, bool, bool | None]:
    """Compare the receipt with the artifact: its status, whether it matches, and ``served``.

    ``fingerprint`` is ``None`` for an artifact the reader refused, which no receipt can
    match.
    """

    status, document = _read_receipt(receipt_path)
    if document is None:
        return status, False, None
    served = bool(document["served"])
    if document.get("snapshot_id") != snapshot_id:
        return "other_capture", False, served
    if fingerprint is None:
        return "artifact_invalid", False, served
    if document.get("artifact_sha256") != sha256:
        return "sha256_mismatch", False, served
    if document.get("fingerprint") != fingerprint:
        return "fingerprint_mismatch", False, served
    if served:
        return "served", False, served
    return "matches", True, served


def shadow_artifact(
    artifact_root: Path,
    inputs: RecommendationInputs,
    *,
    as_of: datetime | None = None,
) -> ShadowArtifact:
    """Read the v1 artifact of ``inputs``' capture under ``artifact_root`` and its receipt.

    The receipt is read from ``<artifact_root>/receipts/<capture>.json``, where the shadow
    builder writes it; an ordinary artifact root has none, and the week then reports the
    receipt as absent and ``football_served`` as unknown.
    """

    path = football_artifact_path(artifact_root, inputs.snapshot_id)
    receipt_path = artifact_root / "receipts" / path.name
    if not path.is_file():
        return ShadowArtifact(
            path, "missing", None, None, None, receipt_path, "absent", False, None
        )
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    written = _write_instant(path)
    try:
        forecast = read_football_forecast(path, inputs)
        if forecast.projection.diagnostics["model_version"] != FOOTBALL_MODEL_VERSION:
            raise ValueError("The frozen protocol requires football v1.")
    except (ValueError, DataError, KeyError, TypeError):
        receipt_status, _, served = _receipt_status(
            receipt_path, snapshot_id=inputs.snapshot_id, sha256=sha256, fingerprint=None
        )
        return ShadowArtifact(
            path,
            "invalid",
            None,
            _utc_text(written),
            sha256,
            receipt_path,
            receipt_status,
            False,
            served,
        )
    receipt_status, matches, served = _receipt_status(
        receipt_path,
        snapshot_id=inputs.snapshot_id,
        sha256=sha256,
        fingerprint=forecast.fingerprint,
    )
    late = written >= as_instant(inputs.deadline.deadline_utc)
    if as_of is not None and written > as_of:
        late = True
    return ShadowArtifact(
        path,
        "late" if late else "usable",
        forecast,
        _utc_text(written),
        sha256,
        receipt_path,
        receipt_status,
        matches,
        served,
    )


@dataclass(frozen=True)
class CurrentPairing:
    """How the current arm of one scored capture was paired, under default 1.

    ``branch`` is ``a``, ``b`` or ``c``. ``handoff`` and the fields describing it are set
    for ``a`` and ``b``; ``reason`` is set for ``c`` and is always the protocol's
    ``UNPAIRED_REASON``, with ``detail`` saying which case produced it. ``replay`` is true
    only under branch b, for a selected file written at or after the deadline.
    ``backend_rule_fingerprint`` is what branch b selects at reading time whichever branch
    paired the week, and ``backend_rule_differs`` flags a selected fingerprint other than
    it. ``record_fingerprints`` lists every fingerprint the counted records name.
    """

    branch: str
    handoff: InSeasonProjection | None
    fingerprint: str | None
    model_version: str | None
    path: Path | None
    write_utc: str | None
    replay: bool
    reason: str | None
    detail: str | None
    records_counted: int
    record_fingerprints: tuple[str, ...]
    backend_rule_fingerprint: str | None
    backend_rule_differs: bool


def _matching_handoffs(
    handoff_root: Path, season: str, gameweek: int, snapshot_id: str
) -> list[tuple[Path, InSeasonProjection]]:
    """Every readable handoff of the alias and the retained copies that names the capture.

    The alias comes first. A file that is absent, malformed or fails its own fingerprint
    is skipped, as the backend skips it; one that raises ``OSError`` is not, and the error
    reaches the caller.
    """

    alias = handoff_path_for(handoff_root, season, gameweek)
    retained = handoff_root / "by-capture" / snapshot_id
    found: list[tuple[Path, InSeasonProjection]] = []
    for path in (alias, *sorted(retained.glob("*.json"))):
        try:
            handoff = read_projection_handoff(path)
        except (ValueError, DataError):
            continue
        if (handoff.source_snapshot_id, handoff.season, handoff.gameweek) != (
            snapshot_id,
            season,
            gameweek,
        ):
            continue
        found.append((path, handoff))
    return found


def backend_rule_handoff(
    handoff_root: Path, season: str, gameweek: int, snapshot_id: str
) -> tuple[Path, InSeasonProjection] | None:
    """Branch b: the backend's selection as on develop at 6e7e6176.

    The matching alias wins; otherwise exactly one matching retained fingerprint is
    required, and ``None`` says there was none or more than one.
    """

    alias = handoff_path_for(handoff_root, season, gameweek)
    matches: dict[str, tuple[Path, InSeasonProjection]] = {}
    for path, handoff in _matching_handoffs(handoff_root, season, gameweek, snapshot_id):
        if path == alias:
            return path, handoff
        matches.setdefault(handoff.fingerprint, (path, handoff))
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def _counted_record_fingerprints(
    advice_record_root: Path, season: str, gameweek: int, snapshot_id: str, deadline: datetime
) -> tuple[int, tuple[str, ...]]:
    """The fingerprints the pre-deadline advice records of the capture name, with their count.

    A record is read through ``load_member_advice_record``, so one whose files fail their
    own digests raises ``AdviceRecordError`` rather than being skipped: a record that
    cannot be trusted is a person's question, not a silent fall to branch b. A record
    published at or after the deadline is not counted.
    """

    # The parent of every ``entry_directory`` of the week: ``<root>/<season>/gw<NN>``.
    week_directory = advice_record_root / season / f"gw{gameweek:02d}"
    counted = 0
    fingerprints: set[str] = set()
    if not week_directory.is_dir():
        return 0, ()
    for member in sorted(week_directory.iterdir()):
        if not member.is_dir() or not member.name.startswith("entry-"):
            continue
        try:
            entry_id = int(member.name.removeprefix("entry-"))
        except ValueError:
            continue
        if not (member / snapshot_id).is_dir():
            continue
        record = load_member_advice_record(
            advice_record_root, season, gameweek, entry_id, snapshot_id
        )
        capture = record.get("capture")
        if (
            not isinstance(capture, dict)
            or capture.get("snapshot_id") != snapshot_id
            or record.get("season") != season
            or record.get("gameweek") != gameweek
        ):
            raise AdviceRecordError(
                f"The advice record of entry {entry_id} under {member / snapshot_id} does not "
                f"name {season} gameweek {gameweek} of capture {snapshot_id!r}."
            )
        stamp = record.get("generated_at_utc")
        if not isinstance(stamp, str):
            raise AdviceRecordError(
                f"The advice record of entry {entry_id} records no publication time."
            )
        published = as_instant(normalize_utc_timestamp(stamp, label="generated_at_utc"))
        if published >= deadline:
            continue
        provenance = record.get("provenance")
        named = (
            provenance.get("projection_handoff_fingerprint")
            if isinstance(provenance, dict)
            else None
        )
        if not isinstance(named, str) or not named:
            raise AdviceRecordError(
                f"The advice record of entry {entry_id} names no projection handoff fingerprint."
            )
        counted += 1
        fingerprints.add(named)
    return counted, tuple(sorted(fingerprints))


def pair_current(
    handoff_root: Path,
    inputs: RecommendationInputs,
    *,
    advice_record_root: Path | None = None,
) -> CurrentPairing:
    """Pair the current arm of ``inputs``' capture under default 1.

    With no ``advice_record_root`` no record is read, so the pairing can only be branch b
    or c; the caller says so beside the result.
    """

    season = inputs.season
    gameweek = int(inputs.deadline.gameweek)
    snapshot_id = inputs.snapshot_id
    deadline = as_instant(inputs.deadline.deadline_utc)
    backend = backend_rule_handoff(handoff_root, season, gameweek, snapshot_id)
    backend_fingerprint = None if backend is None else backend[1].fingerprint

    def missing(detail: str, counted: int, named: tuple[str, ...]) -> CurrentPairing:
        return CurrentPairing(
            BRANCH_MISSING,
            None,
            None,
            None,
            None,
            None,
            False,
            UNPAIRED_REASON,
            detail,
            counted,
            named,
            backend_fingerprint,
            False,
        )

    counted, named = (
        (0, ())
        if advice_record_root is None
        else _counted_record_fingerprints(
            advice_record_root, season, gameweek, snapshot_id, deadline
        )
    )
    if counted:
        if len(named) != 1:
            return missing(
                "the pre-deadline advice records name more than one fingerprint", counted, named
            )
        wanted = named[0]
        carrying = [
            (path, handoff)
            for path, handoff in _matching_handoffs(handoff_root, season, gameweek, snapshot_id)
            if handoff.fingerprint == wanted
        ]
        if not carrying:
            return missing("no handoff file carries the recorded fingerprint", counted, named)
        # The retained copy is the create-once file of this capture, so it is the one
        # reported when it and the alias both carry the fingerprint; the alias is
        # reported only when no retained copy does.
        path, handoff = carrying[-1]
        return CurrentPairing(
            BRANCH_PUBLISHED_RECORD,
            handoff,
            handoff.fingerprint,
            handoff.model_version,
            path,
            _utc_text(_write_instant(path)),
            False,
            None,
            None,
            counted,
            named,
            backend_fingerprint,
            backend_fingerprint != handoff.fingerprint,
        )
    if backend is None:
        return missing("no eligible advice record, and the backend rule finds none or two", 0, ())
    path, handoff = backend
    written = _write_instant(path)
    return CurrentPairing(
        BRANCH_BACKEND_RULE,
        handoff,
        handoff.fingerprint,
        handoff.model_version,
        path,
        _utc_text(written),
        written >= deadline,
        None,
        None,
        0,
        (),
        backend_fingerprint,
        False,
    )


def pairing_fields(pairing: CurrentPairing) -> dict[str, Any]:
    """The per-week fields a record reports for the pairing, without local paths."""

    return {
        "pairing_branch": pairing.branch,
        "pairing_detail": pairing.detail,
        "current_fingerprint": pairing.fingerprint,
        "current_model": pairing.model_version,
        "handoff_write_utc": pairing.write_utc,
        "advice_records_counted": pairing.records_counted,
        "recorded_handoff_fingerprints": list(pairing.record_fingerprints),
        "backend_rule_fingerprint": pairing.backend_rule_fingerprint,
        "backend_rule_differs": pairing.backend_rule_differs,
    }


__all__ = [
    "BRANCH_BACKEND_RULE",
    "BRANCH_MISSING",
    "BRANCH_PUBLISHED_RECORD",
    "SHADOW_RECEIPT_CONTRACT",
    "UNPAIRED_REASON",
    "CurrentPairing",
    "ScoredCapture",
    "ShadowArtifact",
    "backend_rule_handoff",
    "pair_current",
    "pairing_fields",
    "scored_capture",
    "shadow_artifact",
]
