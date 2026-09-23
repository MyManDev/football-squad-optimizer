"""The per-capture inputs behind a request's switches, and how they enter an address.

A plain request is answered from the capture and its handoff. A switched-on request also
reads something ops produced beside them: a Top 100 setting reads the week's elite-picks
evidence export, the manager's word reads the rotation table coded from club news. Neither
is named by a client. They are found under the deployment's artifact root by the names the
weekly run writes them under, gated exactly as the batch gates them, and their identity is
hashed into the cache key of every answer that used them, so an answer computed from one
export can never be served as the answer from another.

**Absent is an answer.** No artifact root, no export for the week, an export the gate
refuses, no rotation table for the capture: each leaves its input ``None``, and a request
that needs it is refused by name rather than answered without it.

**Adding a switch.** One more optional field on ``AdviceSwitchInputs``, one more entry in
``switch_identity`` under its own name, and one more line in ``discovery_signature``. The
cache key and the job spec carry the identity mapping whole, so neither changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from squadopt.application.advice_chips import CHIP_CHOICE_BASIS
from squadopt.application.manager_words import (
    MANAGERS_WORD_RULE_VERSION,
    ManagerWords,
    load_manager_words,
)
from squadopt.application.top100_weight import (
    TOP100_PRICE_BASIS,
    Top100Counts,
    Top100InputsRefused,
    load_top100_counts,
    top100_manifest_path,
)
from squadopt.application.weekly_plan import evidence_artifact, rotation_artifact
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.data.errors import DataError
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.football_artifact import (
    FootballForecast,
    football_artifact_path,
    read_football_forecast,
)
from squadopt.planning.chip_strategy import CHIP_STRATEGY_VERSION

__all__ = [
    "CHIP_SWITCH",
    "EVIDENCE_DIRECTORY",
    "MANAGERS_WORD_SWITCH",
    "ROTATION_DIRECTORY",
    "TOP100_SWITCH",
    "AdviceSwitchInputs",
    "SwitchIdentity",
    "SwitchInputUnavailable",
    "discovery_signature",
    "load_switch_inputs",
    "switch_identity",
]

CHIP_SWITCH: Final = "chip"
MODEL_SWITCH: Final = "model"
TOP100_SWITCH: Final = "top100"
MANAGERS_WORD_SWITCH: Final = "managers_word"
#: Where the weekly run writes the two artifacts, under the repository's ``artifacts/``.
EVIDENCE_DIRECTORY: Final = "phase_b"
ROTATION_DIRECTORY: Final = "rotation"

#: One switch's identity: JSON scalars only, because it is hashed and stored as written.
SwitchIdentity = dict[str, dict[str, str | int | bool | None]]


class SwitchInputUnavailable(ValueError):
    """A switch was asked for and this capture has no input for it; ``switch`` names it."""

    def __init__(self, switch: str, detail: str) -> None:
        super().__init__(detail)
        self.switch = switch


@dataclass(frozen=True, slots=True)
class AdviceSwitchInputs:
    """What one capture offers the switches; every field may be absent."""

    top100_counts: Top100Counts | None = None
    manager_words: ManagerWords | None = None
    #: The rotation table's digest from its verified manifest: the word's identity.
    rotation_table_sha256: str | None = None
    #: Why an input is absent, for the operator's log and never for a response.
    notes: tuple[str, ...] = ()
    football: FootballForecast | None = None


def switch_identity(
    inputs: AdviceSwitchInputs,
    *,
    top100_weight: int = 0,
    managers_word: bool = False,
    chip: str | None = None,
    model: str = "current",
    preferences: DecisionPreferences = NO_PREFERENCES,
) -> SwitchIdentity:
    """What the switched-on part of a request adds to its address; empty when all are off.

    Each switch contributes its value **and** the identity of the input it will be
    computed from, together with the version of the rule that applies it. The rule
    versions live here rather than in the configuration fingerprint because that
    fingerprint is in every plain key already written; here they reach only the keys
    they can change.
    """

    identity: SwitchIdentity = {}
    if preferences.active:
        identity["preferences"] = {
            "version": "decision_preferences_v1",
            "value": preferences.canonical(),
        }
    if model != "current":
        if model != "football" or inputs.football is None:
            raise SwitchInputUnavailable(
                MODEL_SWITCH, "This capture has no usable football forecast."
            )
        identity[MODEL_SWITCH] = {"name": model, "fingerprint": inputs.football.fingerprint}
    if chip is not None:
        identity[CHIP_SWITCH] = {
            "chip": chip,
            "basis": CHIP_CHOICE_BASIS,
            "strategy_version": CHIP_STRATEGY_VERSION,
        }
    if top100_weight:
        counts = inputs.top100_counts
        if counts is None:
            raise SwitchInputUnavailable(
                TOP100_SWITCH,
                "This capture has no usable Top 100 counts, so no setting is offered.",
            )
        identity[TOP100_SWITCH] = {
            "weight": int(top100_weight),
            "price_basis": TOP100_PRICE_BASIS,
            "table_sha256": counts.table_sha256,
            "cohort_snapshot_id": counts.cohort_snapshot_id,
            "picks_snapshot_id": counts.picks_snapshot_id,
            "picks_gameweek": counts.picks_gameweek,
        }
    if managers_word:
        words = inputs.manager_words
        if words is None or inputs.rotation_table_sha256 is None:
            raise SwitchInputUnavailable(
                MANAGERS_WORD_SWITCH,
                "This capture has no coded club news, so the manager's word is not offered.",
            )
        identity[MANAGERS_WORD_SWITCH] = {
            "rule_version": MANAGERS_WORD_RULE_VERSION,
            "rotation_table_sha256": inputs.rotation_table_sha256,
            "source_kind": words.source_kind,
            "source_label": words.source_label,
        }
    return identity


def _evidence_candidates(artifact_root: Path, season: str, gameweek: int) -> list[Path]:
    # The naming function with a wildcard where the picks capture's hash goes, so the
    # pattern cannot drift from the name the weekly run writes.
    pattern = evidence_artifact(Path(EVIDENCE_DIRECTORY), season, gameweek, "*")[0].name
    return sorted((artifact_root / EVIDENCE_DIRECTORY).glob(pattern))


def _generated_at(table: Path) -> str:
    try:
        document = json.loads(top100_manifest_path(table).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = document.get("generated_at_utc") if isinstance(document, dict) else None
    return value if isinstance(value, str) else ""


def _stat(path: Path) -> tuple[str, int, int]:
    try:
        status = path.stat()
    except OSError:
        return (path.name, -1, -1)
    return (path.name, status.st_size, status.st_mtime_ns)


def discovery_signature(
    *,
    artifact_root: Path | None,
    club_news_source: Path | None,
    season: str,
    gameweek: int,
    capture_snapshot_id: str,
) -> tuple[object, ...]:
    """A cheap reading of what ``load_switch_inputs`` would look at, to notice a change.

    The api and the worker each hold their inputs for the life of a context. An export
    that lands after one of them looked would otherwise leave the two disagreeing about
    an address for as long as the capture lasts; comparing this signature per request
    (a directory listing and a few ``stat`` calls) lets both pick it up.
    """

    if artifact_root is None:
        return ()
    found: list[tuple[str, int, int]] = []
    found.append(_stat(football_artifact_path(artifact_root, capture_snapshot_id)))
    for table in _evidence_candidates(artifact_root, season, gameweek):
        found.extend((_stat(table), _stat(top100_manifest_path(table))))
    if club_news_source is not None:
        found.extend(
            _stat(path)
            for path in rotation_artifact(
                artifact_root / ROTATION_DIRECTORY, season, gameweek, capture_snapshot_id
            )
        )
        found.append(_stat(club_news_source))
    return tuple(found)


def load_switch_inputs(
    *,
    artifact_root: Path | None,
    club_news_source: Path | None,
    snapshot_root: Path,
    inputs: RecommendationInputs,
    projection: Projection,
) -> AdviceSwitchInputs:
    """Find and gate this capture's switch inputs; never raises for an absent one.

    Top 100: among the week's exports, the newest generated one that passes
    ``load_top100_counts`` for this capture. A rehearsal's export and Friday's can both be
    on disk, and an export taken after this capture is refused by the gate, so "newest
    that passes" is the one the batch would have been handed. The word: the rotation
    table named after this capture, read with the configured club-news source.
    """

    if artifact_root is None:
        return AdviceSwitchInputs()
    season, gameweek = str(inputs.season), int(inputs.deadline.gameweek)
    notes: list[str] = []
    counts: Top100Counts | None = None
    candidates = _evidence_candidates(Path(artifact_root), season, gameweek)
    for table in sorted(
        candidates, key=lambda path: (_generated_at(path), path.name), reverse=True
    ):
        try:
            counts = load_top100_counts(table, inputs=inputs, projection=projection)
        except Top100InputsRefused as refusal:
            notes.append(f"top100 {table.name}: {refusal.reason}: {refusal}")
            continue
        break
    if not candidates:
        notes.append(f"top100: no export for {season} gameweek {gameweek}")
    words: ManagerWords | None = None
    digest: str | None = None
    if club_news_source is None:
        notes.append("managers_word: no club-news source configured")
    else:
        table, manifest = rotation_artifact(
            Path(artifact_root) / ROTATION_DIRECTORY, season, gameweek, inputs.snapshot_id
        )
        if not table.is_file():
            notes.append(f"managers_word: no rotation table {table.name}")
        else:
            try:
                words = load_manager_words(
                    table, club_news_source=Path(club_news_source), snapshot_root=snapshot_root
                )
                recorded = json.loads(manifest.read_text(encoding="utf-8")).get("table_sha256")
                if (words.season, words.gameweek) != (season, gameweek):
                    raise ValueError(f"the table is for {words.season} gameweek {words.gameweek}")
                if not isinstance(recorded, str) or not recorded:
                    raise ValueError("the manifest records no table_sha256")
                digest = recorded
            except (DataError, OSError, ValueError, KeyError) as error:
                # An unreadable table turns the switch off; it does not stop the backend.
                notes.append(f"managers_word {table.name}: {error}")
                words, digest = None, None
    football = None
    try:
        football = read_football_forecast(
            football_artifact_path(artifact_root, inputs.snapshot_id), inputs
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        notes.append(f"football: {error}")
    return AdviceSwitchInputs(
        top100_counts=counts,
        manager_words=words,
        rotation_table_sha256=digest,
        notes=tuple(notes),
        football=football,
    )
