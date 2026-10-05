"""The planner policy chain's weekly step.

``docs/research/planner_policy_chain_prereg.md`` fixes every rule this script applies, and the
rule numbers below are that document's.

``check`` prints, from the first chain week on, the decision capture the protocol selects for each
gameweek, whether its deadline has passed and whether its served football forecast can be read.
It writes nothing.

``decide`` writes every arm's decision for each gameweek whose deadline has passed and that is not
yet decided, in order, from the frozen source. Neither command reads an outcome; the scorer is a
separate script, run only at the protocol's readings.

Run from a clean, locked worktree of the runner's merge commit, with S the capture root, A and
H the artifact root and the handoff root the backend served the weeks from (rule 6), E a
directory outside the checkout and outside every root above for the copies of each week's
evidence (rule 39), and U the #632 comment that answers Question PC1:

    git worktree lock --reason "planner policy chain evidence"
    python -m scripts.measure_planner_policy_chain check --snapshot-root S --artifact-root A
        --handoff-root H
    python -m scripts.measure_planner_policy_chain decide --snapshot-root S --artifact-root A
        --handoff-root H --output artifacts/planner_policy_chain --evidence-copy-root E
        --through-gameweek N --answer U

The evidence under ``artifacts/`` is ignored and uncommitted until the final reading, and
``git worktree remove`` deletes ignored files, so ``decide`` refuses an unlocked worktree and
copies every decided week to E.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from importlib import metadata as package_metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd

import squadopt
from squadopt.application import advice as window_advice
from squadopt.application.football_participation import FOOTBALL_PARTICIPATION_VERSION
from squadopt.application.lineup_publication import lineup_fields
from squadopt.data._long_paths import addressable
from squadopt.data.atomic import write_bytes_once, write_document_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE, gameweek_deadlines
from squadopt.live.football_artifact import (
    FootballForecast,
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.recommendation import (
    Projection,
    RecommendationInputs,
    infer_season,
    read_inputs,
    read_projection_handoff,
)
from squadopt.live.rules import SeasonRules, read_season_rules
from squadopt.live.tick import handoff_path_for
from squadopt.live.transfers import (
    HeldSquad,
    _transfer_config,
    plan_transfer_horizon,
    plan_transfers,
)
from squadopt.optimization import SolverStatus, optimize_squad
from squadopt.optimization.config import OptimizationConfig
from squadopt.optimization.optimizer import (
    MIN_TIEBREAK_DETERMINISTIC_TIME,
    wall_clock_stopped_the_search,
)
from squadopt.planning import optimizer as plan_optimizer
from squadopt.planning.horizon import ProjectionHorizon
from squadopt.planning.models import (
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths, spending_power
from squadopt.platform.advice_switches import AdviceSwitchInputs, load_switch_inputs
from squadopt.platform.capture_context import handoff_fingerprint_for
from squadopt.platform.football_bundle import football_bundle_path
from squadopt.platform.football_minute_basis import football_components_path
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)

REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL_FILE = "docs/research/planner_policy_chain_prereg.md"
RUNNER_FILE = "scripts/measure_planner_policy_chain.py"
PROTOCOL_PATH = REPOSITORY / PROTOCOL_FILE
RUNNER_PATH = Path(__file__).resolve()
#: Rule 36: the only directory the chain writes under.
OUTPUT_ROOT = REPOSITORY / "artifacts" / "planner_policy_chain"

PROTOCOL_ID = "planner_policy_chain_v1"
SEASON = "2026-27"
LAST_GAMEWEEK = 38

#: Squad budget, total funds and free transfers, by the rule of measure_shortlist_matrix.py.
PROFILES: tuple[tuple[int, int, int], ...] = ((1000, 1000, 1), (950, 1000, 2), (900, 900, 0))
#: The five arms. Each week every (squad, arm) chain is solved in sorted order.
ARMS: tuple[str, ...] = ("served_3", "served_5", "hold_3", "hold_5", "one_week")
#: Deterministic units per forecast week, the member window's rate, for every arm (rule 11).
UNITS_PER_WEEK = 20.0
#: The standard path's hold probe runs outside the primary limit, so the hold arm's primary
#: limit is one unit short of the others' total (rule 11).
HOLD_PROBE_UNITS = 1.0
#: The model name ``build_football_horizon`` gives a football horizon; ``plan_transfer_horizon``
#: routes and finances a three- or five-week window by it (rule 12).
FOOTBALL_HORIZON_MODEL = "fixture_football_candidate"
#: Rule 6: the served model versions a week may carry, each only as the reader at the frozen
#: commit accepts it. A week records its own version and no two are relabelled as one. The
#: contextual research version, which that reader also accepts, was never served and is not here.
ADMITTED_MODEL_VERSIONS: tuple[str, ...] = (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
#: The configuration measure_shortlist_matrix.py builds its squads under (rule 9).
SQUAD_CONFIG = OptimizationConfig(
    bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
)
#: Rule 9: a squad not proved at 60 units is built once more at this budget, with a wall ceiling
#: that grows with it so the clock does not decide the retry.
SQUAD_RETRY_UNITS = 240.0
SQUAD_RETRY_WALL_SECONDS = 480.0
#: Captures named before this instant belong to an earlier season and are never opened (rule 38).
SEASON_OPENS = datetime(2026, 6, 1, tzinfo=UTC)
CAPTURE_INSTANT = re.compile(r"-(\d{8}T\d{6}Z)-")
#: Rule 40: no chain starts once this gameweek's deadline has passed.
LAPSE_GAMEWEEK = 21
#: Rule 2 and Answer 5948324329: GW6 is the first chain week only if this protocol merged by
#: the end of 6 October and the runner by the end of 8 October, in UTC committer instants.
TARGET_FIRST_WEEK = 6
PROTOCOL_MERGED_BEFORE = datetime(2026, 10, 7, tzinfo=UTC)
RUNNER_MERGED_BEFORE = datetime(2026, 10, 9, tzinfo=UTC)
#: Rule 40: no decision is computed before the 9 to 11 October freeze ends.
FIRST_COMPUTATION = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
#: Packages whose versions decide what the solver returns; a later run must match them.
PINNED_PACKAGES: tuple[str, ...] = ("ortools", "numpy", "pandas")
#: Rule 39: the decision step never runs on a Tuesday or a Friday, operator's time (UTC+3,
#: Turkey keeps no summer time).
OPERATOR_ZONE = timezone(timedelta(hours=3))
REFUSED_WEEKDAYS: frozenset[int] = frozenset({1, 4})
#: The values the protocol states for the entry points it calls (rule 11). The first run
#: refuses a frozen source whose constants differ, so the records describe the stated arms.
STATED_CONSTANTS: Mapping[tuple[object, str], object] = {
    (window_advice, "WINDOW_DETERMINISTIC_UNITS_PER_WEEK"): 20.0,
    (window_advice, "WINDOW_WALL_CEILING_SECONDS"): 1800.0,
    (window_advice, "WINDOW_LINEARIZATION_LEVEL"): 2,
    (plan_optimizer, "PLAN_DETERMINISTIC_TIME_LIMIT"): 20.0,
    (plan_optimizer, "PLAN_WALL_CEILING_SECONDS"): 300.0,
}


class ChainError(RuntimeError):
    """A refusal the protocol requires: the run stops rather than write a wrong record."""


@dataclass(frozen=True)
class ChainState:
    """One arm's squad going into a deadline: what the protocol carries week to week.

    ``lineup`` is the team the arm last played, in the advice record's field names; a failed
    week plays it again (rule 22).
    """

    squad: tuple[int, ...]
    purchase_prices: Mapping[int, int]
    bank_tenths: int
    free_transfers: int
    decided_gameweek: int
    lineup: Mapping[str, object] | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "squad": list(self.squad),
            "purchase_prices": {str(k): int(v) for k, v in sorted(self.purchase_prices.items())},
            "bank_tenths": int(self.bank_tenths),
            "free_transfers": int(self.free_transfers),
            "decided_gameweek": int(self.decided_gameweek),
            "lineup": None if self.lineup is None else dict(self.lineup),
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> ChainState:
        lineup = document.get("lineup")
        return cls(
            squad=tuple(int(p) for p in document["squad"]),
            purchase_prices={int(k): int(v) for k, v in document["purchase_prices"].items()},
            bank_tenths=int(document["bank_tenths"]),
            free_transfers=int(document["free_transfers"]),
            decided_gameweek=int(document["decided_gameweek"]),
            lineup=None if lineup is None else dict(lineup),
        )

    def same_holding(self, other: ChainState) -> bool:
        """Two arms plan from the same state: squad, lots, bank and free transfers."""

        return (self.squad, dict(self.purchase_prices), self.bank_tenths, self.free_transfers) == (
            other.squad,
            dict(other.purchase_prices),
            other.bank_tenths,
            other.free_transfers,
        )

    def held(self) -> HeldSquad:
        return HeldSquad(
            season=SEASON,
            decided_gameweek=self.decided_gameweek,
            squad_player_ids=self.squad,
            purchase_prices=dict(self.purchase_prices),
            bank_tenths=self.bank_tenths,
            free_transfers=self.free_transfers,
            chips_used={},
        )


# ---------------------------------------------------------------------------------------------
# What each week reads (rules 5 to 8)


@dataclass(frozen=True)
class CaptureIndexEntry:
    snapshot_id: str
    captured_at_utc: datetime
    target: int
    deadline_utc: datetime
    #: Rule 5: whether the handoff root holds a served baseline handoff for this capture, so the
    #: backend could have served it. True when no handoff root was given (the index alone).
    served: bool = True


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ChainError(f"Timestamp {text!r} names no time zone.")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CaptureInventory:
    """The season's live captures that target a gameweek, and those taken after every deadline."""

    entries: tuple[CaptureIndexEntry, ...]
    closed: tuple[str, ...]


def _named_before_season(snapshot_id: str) -> bool:
    match = CAPTURE_INSTANT.search(snapshot_id)
    if match is None:
        return False
    named = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return named < SEASON_OPENS


def capture_inventory(snapshot_root: Path, handoff_root: Path | None = None) -> CaptureInventory:
    """Every live capture of the season with its instant, its own target, its deadline and
    whether the backend could have served it (rule 5).

    A capture named before the season opens is never opened, and one of another season is left
    out. A capture taken after every published deadline had closed targets no gameweek and is
    listed apart (rule 5). Any other capture of this season that cannot be read is a fault, as in
    ``scripts/check_football_prospective_inputs.py``: its target is unknown, so no week could be
    said to have its last capture.
    """

    entries = []
    closed = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        if _named_before_season(snapshot_id):
            continue
        try:
            snapshot = read_snapshot(snapshot_root, snapshot_id)
            if infer_season(snapshot) != SEASON:
                continue
            captured = _instant(snapshot.metadata.captured_at_utc)
            deadlines = gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
            if deadlines and all(_instant(d.deadline_utc) <= captured for d in deadlines):
                closed.append(snapshot_id)
                continue
            inputs = read_inputs(snapshot, season=SEASON)
        except (DataError, ValueError, KeyError, TypeError) as error:
            raise ChainError(f"Capture {snapshot_id} cannot be read: {error}") from error
        gameweek = int(inputs.deadline.gameweek)
        served = handoff_root is None or (
            handoff_fingerprint_for(handoff_root, SEASON, gameweek, snapshot_id) is not None
        )
        entries.append(
            CaptureIndexEntry(
                snapshot_id,
                captured,
                gameweek,
                _instant(inputs.deadline.deadline_utc),
                served,
            )
        )
    return CaptureInventory(tuple(entries), tuple(closed))


def capture_index(
    snapshot_root: Path, handoff_root: Path | None = None
) -> tuple[CaptureIndexEntry, ...]:
    """The inventory's captures that target a gameweek."""

    return capture_inventory(snapshot_root, handoff_root).entries


@dataclass(frozen=True)
class Selection:
    snapshot_id: str | None
    reason: str | None


def decision_capture(index: Sequence[CaptureIndexEntry], gameweek: int) -> Selection:
    """Rule 5: the last capture, by instant, whose own target is the gameweek and that the
    backend could have served; an unserved capture is passed over, and a tie is missing."""

    own = [entry for entry in index if entry.target == gameweek]
    if not own:
        return Selection(None, "no_own_target_capture")
    served = [entry for entry in own if entry.served]
    if not served:
        return Selection(None, "no_served_handoff")
    latest = max(entry.captured_at_utc for entry in served)
    at_latest = [entry for entry in served if entry.captured_at_utc == latest]
    if len(at_latest) > 1:
        return Selection(None, "tied_latest_captures")
    return Selection(at_latest[0].snapshot_id, None)


def deadline_of(index: Sequence[CaptureIndexEntry], snapshot_root: Path, gameweek: int) -> datetime:
    """The latest a capture puts the gameweek's deadline: its own captures and the newest one.

    A deadline that moved later is honoured, so a week is never decided while a capture still
    says it is open (rule 5).
    """

    if not index:
        raise ChainError("No live capture to read the deadlines from.")
    stated = [entry.deadline_utc for entry in index if entry.target == gameweek]
    newest = max(index, key=lambda entry: entry.captured_at_utc)
    snapshot = read_snapshot(snapshot_root, newest.snapshot_id)
    for deadline in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
        if int(deadline.gameweek) == gameweek:
            stated.append(_instant(deadline.deadline_utc))
    if not stated:
        raise ChainError(f"No capture states a deadline for GW{gameweek}.")
    return max(stated)


@dataclass(frozen=True)
class WeekInputs:
    inputs: RecommendationInputs
    rules: SeasonRules
    forecast: FootballForecast
    artifact_bytes: bytes
    receipt: Mapping[str, object]


def _receipt(
    snapshot_id: str,
    inputs: RecommendationInputs | None,
    capture_fingerprint: str | None,
    **fields: object,
) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "capture_fingerprint": capture_fingerprint,
        "captured_at_utc": None if inputs is None else inputs.captured_at_utc,
        "deadline_utc": None if inputs is None else inputs.deadline.deadline_utc,
        **fields,
    }


#: Rule 36: a note that names a file carries its path, and a path can name a league or an entry
#: (rule 38), so every run of characters holding a slash is replaced before a note is recorded.
_PATH_IN_NOTE = re.compile(r"[^\s'\"()]*[\\/][^\s'\"()]*")


def binding_notes(notes: Sequence[str]) -> list[str]:
    """Rule 36: the service's notes on the football binding, each file path replaced.

    The Top 100 notes are left out: the chain's call carries no projected table, so the service
    would refuse every Top 100 export for a reason it never gave when serving, and rule 15 sets
    that weight to 0.
    """

    return [_PATH_IN_NOTE.sub("<path>", note) for note in notes if not note.startswith("top100")]


def served_handoff_file(
    handoff_root: Path, season: str, gameweek: int, snapshot_id: str
) -> tuple[str | None, Path | None]:
    """Rule 6: the served baseline handoff's fingerprint, by the backend's own rule, and the file
    that carries it: the gameweek alias when it matches, else the one retained copy that does."""

    fingerprint = handoff_fingerprint_for(handoff_root, season, gameweek, snapshot_id)
    if fingerprint is None:
        return None, None
    alias = handoff_path_for(Path(handoff_root), season, gameweek)
    retained = Path(handoff_root) / "by-capture" / snapshot_id
    for path in (alias, *sorted(retained.glob("*.json"))):
        try:
            if read_projection_handoff(path).fingerprint == fingerprint:
                return fingerprint, path
        except (OSError, ValueError, DataError):
            continue
    return fingerprint, None


def _written_before(path: Path, deadline: datetime) -> tuple[str | None, bool]:
    """When a file was written (None if it is absent), and whether that is before ``deadline``."""

    try:
        if not Path(addressable(path)).exists():
            return None, True
        written = datetime.fromtimestamp(Path(addressable(path)).stat().st_mtime, tz=UTC)
    except OSError as error:  # a file that exists but cannot be read now is not a missing week
        raise ChainError(f"{path.name} cannot be read now: {error}") from error
    return written.isoformat(), written < deadline


def week_inputs(
    snapshot_root: Path,
    artifact_root: Path,
    snapshot_id: str,
    *,
    handoff_root: Path | None = None,
) -> WeekInputs | tuple[str, Mapping[str, object]]:
    """Rules 6 and 7: the served forecast, bound as the service at the frozen commit binds it,
    and the season rules.

    The artifact's bytes are read first; their sha256, fingerprint and modification time are
    the receipt, and a forecast whose fingerprint differs from those bytes' is refused. The
    model version is read from the document before any reader runs. A capture with no served
    baseline handoff is not served, and the ready bundle's marker and the components file must
    have been written before the deadline, as the artifact must. The forecast every arm plans on
    is the one ``load_switch_inputs`` binds for this capture with no configured club-news
    source, so only news a ready bundle seals enters it; a week the service refuses to bind, or
    raises on, is missing, and the receipt says why.
    """

    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season=SEASON)
    fingerprint = snapshot.metadata.fingerprint
    deadline = _instant(inputs.deadline.deadline_utc)
    roots = {
        "artifact_root": artifact_root.name,
        "handoff_root": None if handoff_root is None else handoff_root.name,
    }
    artifact = football_artifact_path(artifact_root, snapshot_id)
    if not artifact.is_file():
        return "no_artifact", _receipt(
            snapshot_id, inputs, fingerprint, reason="no_artifact", **roots
        )
    try:
        written = datetime.fromtimestamp(artifact.stat().st_mtime, tz=UTC)
        data = artifact.read_bytes()
    except OSError as error:  # a file that exists but cannot be read now is not a missing week
        raise ChainError(f"The artifact of {snapshot_id} cannot be read now: {error}") from error
    receipt = _receipt(
        snapshot_id,
        inputs,
        fingerprint,
        **roots,
        artifact=artifact.name,
        artifact_modified_utc=written.isoformat(),
        artifact_sha256=hashlib.sha256(data).hexdigest(),
    )
    if written >= deadline:
        reason = "artifact_written_at_or_after_deadline"
        return reason, {**receipt, "reason": reason}
    try:
        document = json.loads(data)
        if not isinstance(document, dict) or forecast_digest(document) != document.get(
            "fingerprint"
        ):
            raise ValueError("The artifact's bytes do not carry their own fingerprint.")
    except (ValueError, KeyError, TypeError):
        reason = "artifact_unreadable_or_unbound"
        return reason, {**receipt, "reason": reason}
    receipt = {**receipt, "forecast_fingerprint": document["fingerprint"]}
    # Rule 6: the version is the document's own, read before any reader, so a week of another
    # version whose fingerprint verifies is missing as that and never as unreadable.
    declared = document.get("model_version")
    if declared not in ADMITTED_MODEL_VERSIONS:
        reason = "artifact_of_another_model_version"
        return reason, {**receipt, "reason": reason, "model_version": declared}
    try:
        forecast = read_football_forecast(artifact, inputs)
    except OSError as error:
        raise ChainError(f"The artifact of {snapshot_id} cannot be read now: {error}") from error
    except (ValueError, KeyError, TypeError, DataError, TransferPlanningError):
        reason = "artifact_unreadable_or_unbound"
        return reason, {**receipt, "reason": reason, "model_version": declared}
    if forecast.horizon.model_version not in ADMITTED_MODEL_VERSIONS:
        reason = "artifact_of_another_model_version"
        return reason, {
            **receipt,
            "reason": reason,
            "model_version": forecast.horizon.model_version,
        }
    if document.get("fingerprint") != forecast.fingerprint:
        reason = "artifact_changed_while_read"
        return reason, {**receipt, "reason": reason}
    # Rules 6 and 8: the served baseline handoff is used for its fingerprint only; a capture the
    # backend holds no such handoff for is one it does not serve.
    handoff_fingerprint, handoff_file = (
        (None, None)
        if handoff_root is None
        else served_handoff_file(handoff_root, SEASON, int(inputs.deadline.gameweek), snapshot_id)
    )
    if handoff_fingerprint is None or handoff_file is None:
        reason = "no_served_handoff"
        return reason, {**receipt, "reason": reason, "model_version": declared}
    # Rule 6: the backend can republish a corrected handoff, so the handoff the chain reads must
    # have been written before the deadline, like the artifact; and the service could not have
    # bound a marker or a components file written later. A marker or components file that is
    # gone is recorded as absent: the service binds a team_share week without them.
    times: dict[str, object] = {}
    times["handoff_modified_utc"], before = _written_before(handoff_file, deadline)
    if not before:
        reason = "handoff_written_at_or_after_deadline"
        return reason, {**receipt, "reason": reason, "model_version": declared, **times}
    for key, path in (
        ("ready_bundle", football_bundle_path(artifact_root, snapshot_id)),
        ("components", football_components_path(artifact_root, snapshot_id)),
    ):
        times[f"{key}_modified_utc"], before = _written_before(path, deadline)
        times[f"{key}_present"] = times[f"{key}_modified_utc"] is not None
        if not before:
            reason = "binding_input_written_at_or_after_deadline"
            return reason, {**receipt, "reason": reason, "model_version": declared, **times}
    # Rule 6: the service's own binding, with no configured club-news source. What the call
    # raises, the backend turns into no football input (backend_runtime.py), and so does the
    # chain.
    try:
        switches = load_switch_inputs(
            artifact_root=artifact_root,
            club_news_source=None,
            snapshot_root=snapshot_root,
            inputs=inputs,
            projection=Projection(
                inputs.players, (), {"projection_handoff_fingerprint": handoff_fingerprint}
            ),
        )
    except Exception as error:
        switches = AdviceSwitchInputs(
            notes=(f"switch inputs unreadable: {type(error).__name__}: {error}",)
        )
    binding: dict[str, object] = {
        "model_version": declared,
        "handoff_fingerprint": handoff_fingerprint,
        **times,
        "ready_bundle_sha256": switches.football_bundle_sha256,
        "rotation_table_sha256": switches.rotation_table_sha256,
        "components_sha256": switches.football_components_sha256,
        "components_bound": switches.football_components_bound,
        "participation_version": FOOTBALL_PARTICIPATION_VERSION,
        "decision_information": switches.decision_information(snapshot_id),
        "binding_notes": binding_notes(switches.notes),
    }
    bound = switches.football
    if bound is None:
        reason = "served_binding_refused"
        return reason, {**receipt, "reason": reason, **binding}
    if (bound.fingerprint, bound.horizon.model_version) != (
        forecast.fingerprint,
        forecast.horizon.model_version,
    ):
        reason = "artifact_changed_while_read"
        return reason, {**receipt, "reason": reason, **binding}
    try:
        rules = read_season_rules(snapshot, season=SEASON)
    except Exception as error:
        raise ChainError(f"The season rules of {snapshot_id} cannot be read: {error}") from error
    hashes = document.get("archive_hashes")
    # Rule 38: a field the artifact does not carry is recorded as absent, never as an empty list.
    seasons = sorted({key.split("/", 1)[0] for key in hashes}) if isinstance(hashes, dict) else None
    role = document.get("role_metadata")
    return WeekInputs(
        inputs=inputs,
        rules=rules,
        forecast=bound,
        artifact_bytes=data,
        receipt={
            **receipt,
            "reason": None,
            "forecast_fingerprint": forecast.fingerprint,
            **binding,
            "model_version": forecast.horizon.model_version,
            "forecast_archive_seasons": seasons,
            "forecast_training_rows": document.get("training_rows"),
            "forecast_training_latest_kickoff": document.get("training_latest_kickoff"),
            "forecast_training_selection": document.get("training_selection"),
            "forecast_role_metadata": (
                {
                    "version": role.get("version"),
                    "role_feature_version": role.get("role_feature_version"),
                }
                if isinstance(role, dict)
                else None
            ),
        },
    )


def _lineup_block(week: object) -> dict[str, object]:
    """Rules 19 and 26: the lineup in the advice record's field names, for the scorer.

    ``week`` is a plan's first week, or a built squad read through the same publication rule.
    """

    lineup = lineup_fields(cast(PlanningWeekResult, week))
    hits = float(getattr(week, "transfer_hit_points", 0.0))
    return {
        "starting_xi": [_player_id(p) for p in cast(list[object], lineup["starting_xi"])],
        "bench": [_player_id(p) for p in cast(list[object], lineup["bench"])],
        "captain": _player_id(lineup["captain"]),
        "vice_captain": _player_id(lineup["vice_captain"]),
        "chip": lineup["chip"],
        "transfer_hit_points": hits,
        "scoring_complete": True,
    }


@dataclass(frozen=True)
class Squads:
    states: Mapping[str, ChainState]
    dropped: Mapping[str, str]
    statuses: Mapping[str, Sequence[str]]


def initial_states(forecast: FootballForecast, gameweek: int) -> Squads:
    """Rule 9: each profile's squad, proved OPTIMAL from the first chain week's table.

    A squad not proved at 60 units is built once more at 240; one still not proved drops only
    its own chains.
    """

    first = forecast.horizon.table.loc[forecast.horizon.table.gameweek.eq(gameweek)].copy()
    prices = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    states: dict[str, ChainState] = {}
    dropped: dict[str, str] = {}
    statuses: dict[str, list[str]] = {}
    for budget, funds, free_transfers in PROFILES:
        profile = f"p{budget}"
        statuses[profile] = []
        solved = None
        attempts = (
            (SQUAD_CONFIG.solver_deterministic_time_limit, SQUAD_CONFIG.solver_time_limit_seconds),
            (SQUAD_RETRY_UNITS, SQUAD_RETRY_WALL_SECONDS),
        )
        for units, wall in attempts:
            config = replace(
                SQUAD_CONFIG,
                budget_tenths=budget,
                solver_deterministic_time_limit=units,
                solver_time_limit_seconds=wall,
            )
            solved = optimize_squad(first, config, linearization_level=2)
            stopped = wall_clock_stopped_the_search(solved.solver_status, solved.diagnostics)
            statuses[profile].append(
                solved.solver_status.name + ("_clock_stopped" if stopped else "")
            )
            if solved.solver_status is SolverStatus.OPTIMAL:
                break
        assert solved is not None
        if solved.solver_status is not SolverStatus.OPTIMAL:
            dropped[profile] = "squad_not_proved_at_240_units"
            continue
        squad = tuple(sorted(int(p) for p in solved.selected_squad.player_id))
        lineup = _lineup_block(
            SimpleNamespace(
                starting_xi=solved.starting_xi,
                bench=solved.bench,
                captain=solved.captain,
                chip=None,
            )
        )
        states[profile] = ChainState(
            squad=squad,
            purchase_prices={p: prices[p] for p in squad},
            bank_tenths=funds - sum(prices[p] for p in squad),
            free_transfers=free_transfers,
            decided_gameweek=gameweek - 1,
            lineup=lineup,
        )
    return Squads(states, dropped, statuses)


# ---------------------------------------------------------------------------------------------
# Arms (rules 11 to 16)


@dataclass(frozen=True)
class PreparedWindow:
    planning_table: pd.DataFrame
    state: InitialSquadState
    policy: TransferPlanningConfig


def prepare_window(
    inputs: RecommendationInputs,
    horizon: ProjectionHorizon,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    deterministic_units: float,
) -> PreparedWindow:
    """The preparation ``plan_transfer_horizon`` performs before it routes a window.

    The hold arm runs this preparation and then the standard path, so it is checked against
    ``plan_transfer_horizon`` on a horizon that takes the standard path, plan for plan, and
    against its policy on a football window that it routes. ``deterministic_units`` is the
    window's whole budget, the one the routed planner's condition reads.
    """

    horizon.assert_fingerprint()
    first_gameweek = horizon.target_gameweeks[0]
    if (inputs.season, inputs.snapshot_id, inputs.deadline.gameweek) != (
        horizon.season,
        horizon.source_snapshot_id,
        first_gameweek,
    ):
        raise ChainError("The horizon does not bind to the capture it is planned from.")
    if held.decided_gameweek != first_gameweek - 1:
        raise ChainError("The held squad was not decided for the week before this horizon.")
    table = horizon.table
    if bool((table.groupby("player_id", sort=False)["price_tenths"].nunique() > 1).any()):
        raise ChainError("Captured prices must stay fixed across the horizon.")
    first = table.loc[table["gameweek"] == first_gameweek]
    current = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    fee = float(rules.transfers.sell_on_fee)
    budget = spending_power(
        bank_tenths=held.bank_tenths,
        sell_prices_tenths={
            player: sell_price_tenths(
                current[player], held.purchase_prices[player], sell_on_fee=fee
            )
            for player in held.squad_player_ids
        },
        stated_squad_sell_value_tenths=held.squad_sell_value_tenths,
    )
    held_sell_prices = dict(budget.sell_prices_tenths)
    planning_table = table.loc[
        :, ["gameweek", "player_id", "name", "team_id", "position", "expected_points"]
    ].copy(deep=True)
    if "appearance_probability" in table:
        planning_table["appearance_probability"] = table["appearance_probability"]
    planning_table["buy_price_tenths"] = table["price_tenths"].astype("int64")
    planning_table["sell_price_tenths"] = [
        held_sell_prices.get(int(player), int(price))
        for player, price in zip(table["player_id"], table["price_tenths"], strict=True)
    ]
    weeks = len(horizon.target_gameweeks)
    policy = _transfer_config(rules, transfer_cap=None if weeks == 1 else 1)
    if weeks > 1:
        policy = replace(policy, acquisition_sell_on_fee=fee)
    # A three- or five-week football window that plan_transfer_horizon routes also lets a
    # second move come from two banked free transfers (fix11), so the hold arm plans under
    # that policy too and rule 12's fingerprint check still compares like with like.
    if (
        horizon.model_name == FOOTBALL_HORIZON_MODEL
        and weeks in (3, 5)
        and deterministic_units >= 2
    ):
        policy = replace(policy, allow_two_free_transfers=True)
    state = InitialSquadState(
        held.squad_player_ids,
        bank_tenths=budget.bank_tenths,
        free_transfers=min(held.free_transfers, policy.max_free_transfers),
    )
    return PreparedWindow(planning_table, state, policy)


def _width(arm: str) -> int:
    return 1 if arm == "one_week" else int(arm.rsplit("_", 1)[1])


def window_weeks(arm: str, gameweek: int) -> tuple[int, ...]:
    """Rule 14: a window of w weeks, truncated at the season's end."""

    return tuple(range(gameweek, min(gameweek + _width(arm), LAST_GAMEWEEK + 1)))


@dataclass
class ArmOutcome:
    """What one arm did for one squad at one deadline, in what the record will hold."""

    plan: TransferPlanResult | None
    route: str
    route_version: str | None
    deterministic_units: float
    wall_ceiling_seconds: float
    weeks: tuple[int, ...]
    truncated: bool
    configuration_fingerprint: str | None = None
    horizon_fingerprint: str | None = None
    failure: str | None = None
    lineup: dict[str, object] | None = None
    status: dict[str, object] = field(default_factory=dict)
    work: dict[str, object] = field(default_factory=dict)


def _route(plan: TransferPlanResult) -> tuple[str, str | None]:
    """Rule 13: the route the served call took. An observed plan also carries its guarded
    baseline's block, and an expected-lineup plan its chosen guarded proposal's, so those
    two blocks are read before the guarded one."""

    for route, key in (
        ("observed", "observed_window"),
        ("expected", "expected_lineup_window"),
        ("guarded", "sequential_incumbent"),
    ):
        block = plan.diagnostics.get(key)
        if isinstance(block, dict):
            version = block.get("version")
            return route, str(version) if version is not None else None
    return "standard", None


def _block(plan: TransferPlanResult, key: str) -> Mapping[str, object]:
    value = plan.diagnostics.get(key)
    return cast(Mapping[str, object], value) if isinstance(value, dict) else {}


def _status(plan: TransferPlanResult, route: str) -> dict[str, object]:
    """Rules 13 and 20: the solver status, what the product publishes, and whether it proves."""

    observed = _block(plan, "observed_window")
    expected = _block(plan, "expected_lineup_window")
    compared = observed.get("status") == "compared"
    solver = plan.solver_status.name
    published = SolverStatus.FEASIBLE.name if compared else solver
    seed = _block(plan, "sequential_incumbent").get("seed_completed")
    return {
        "solver_status": solver,
        "published_status": published,
        "proved": published == SolverStatus.OPTIMAL.name,
        "selection_status": plan.diagnostics.get("selection_status"),
        "observed_window_status": observed.get("status") if route == "observed" else None,
        "expected_window_status": expected.get("status") if route == "expected" else None,
        "expected_window_chosen": expected.get("chosen") if route == "expected" else None,
        "seed_completed": seed,
        "seed_note": None
        if seed is not None
        else "observed_action_is_not_the_guarded_baseline"
        if route == "observed"
        else "no_guarded_construction",
    }


def _work(plan: TransferPlanResult) -> dict[str, object]:
    """Configured work is in the policy block; this is what the solver actually used."""

    diagnostics = plan.diagnostics
    used = diagnostics.get("deterministic_time_used")
    observed = _block(plan, "observed_window")
    expected = _block(plan, "expected_lineup_window")
    guarded = _block(plan, "sequential_incumbent")
    hold = _block(plan, "hold_protection")
    total: object = used
    if observed:
        total = observed.get("actual_total")
    elif expected:
        # Both proposals' guarded totals, each with its own hold probe inside its share.
        total = expected.get("actual_total")
    elif guarded:
        total = guarded.get("actual_total")
    elif hold and isinstance(used, int | float):
        total = float(used) + float(cast(float, hold.get("deterministic_time") or 0.0))
    return {
        "deterministic_time_used": total,
        "solve_time_seconds": diagnostics.get("solve_time_seconds"),
    }


def _probe_clock_stopped(plan: TransferPlanResult) -> bool:
    """Rule 22: the hold probe's own 30-second clock stopped it before its one unit."""

    hold = _block(plan, "hold_protection")
    if hold.get("status") not in (SolverStatus.FEASIBLE.name, SolverStatus.UNKNOWN.name):
        return False
    used = float(cast(float, hold.get("deterministic_time") or 0.0))
    return used < HOLD_PROBE_UNITS - MIN_TIEBREAK_DETERMINISTIC_TIME


def run_arm(arm: str, week: WeekInputs, held: HeldSquad) -> ArmOutcome:
    """Rules 11 and 22: one arm's plan for one squad at one deadline, or why it failed."""

    gameweek = int(week.inputs.deadline.gameweek)
    weeks = window_weeks(arm, gameweek)
    if arm == "one_week":
        units = float(plan_optimizer.PLAN_DETERMINISTIC_TIME_LIMIT)
        wall = float(plan_optimizer.PLAN_WALL_CEILING_SECONDS)
    else:
        units = UNITS_PER_WEEK * len(weeks)
        wall = float(window_advice.WINDOW_WALL_CEILING_SECONDS)
    route = "served" if arm.startswith("served_") else "hold" if arm.startswith("hold_") else arm
    outcome = ArmOutcome(None, route, None, units, wall, weeks, len(weeks) < _width(arm))
    try:
        if arm == "one_week":
            plan, _decision, policy = plan_transfers(
                week.inputs,
                week.forecast.projection,
                held,
                week.rules,
                optimization=OptimizationConfig(
                    solver_time_limit_seconds=wall, solver_deterministic_time_limit=units
                ),
            )
        elif arm.startswith("served_"):
            plan, policy = plan_transfer_horizon(
                week.inputs,
                week.forecast.build_horizon(weeks),
                held,
                week.rules,
                optimization=OptimizationConfig(
                    solver_time_limit_seconds=wall, solver_deterministic_time_limit=units
                ),
                linearization_level=window_advice.WINDOW_LINEARIZATION_LEVEL,
            )
        else:
            prepared = prepare_window(
                week.inputs,
                week.forecast.build_horizon(weeks),
                held,
                week.rules,
                deterministic_units=units,
            )
            policy = prepared.policy
            plan = optimize_transfer_plan(
                PlanningHorizon(prepared.planning_table),
                prepared.state,
                OptimizationConfig(
                    solver_time_limit_seconds=wall,
                    solver_deterministic_time_limit=units - HOLD_PROBE_UNITS,
                ),
                policy,
                linearization_level=window_advice.WINDOW_LINEARIZATION_LEVEL,
                protect_hold=True,
            )
    except ChainError:
        raise
    except Exception as error:  # rule 22: a failure is recorded, never retried
        outcome.failure = f"raised_{type(error).__name__}"
        outcome.work = {"error": str(error)}
        return outcome
    outcome.plan = plan
    outcome.configuration_fingerprint = policy.configuration_fingerprint
    horizon_fingerprint = plan.diagnostics.get("horizon_fingerprint")
    outcome.horizon_fingerprint = None if horizon_fingerprint is None else str(horizon_fingerprint)
    outcome.work = _work(plan)
    if arm.startswith("served_"):
        outcome.route, outcome.route_version = _route(plan)
    if plan.has_solution and plan.weeks:
        outcome.status = _status(plan, outcome.route)
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        outcome.failure = "wall_clock_stopped_the_search"
    elif _probe_clock_stopped(plan):
        outcome.failure = "hold_probe_clock_stopped"
    elif not plan.has_solution or not plan.weeks:
        outcome.failure = "no_plan"
    else:
        try:
            outcome.lineup = _lineup_block(plan.weeks[0])
        except (ValueError, KeyError, TypeError):  # EntryError is a ValueError
            outcome.failure = "incomplete_lineup"
    return outcome


# ---------------------------------------------------------------------------------------------
# Each week (rules 17 to 20) and missing weeks (rule 21)


def advance(
    state: ChainState,
    week: PlanningWeekResult,
    current: Mapping[int, int],
    fee: float,
    lineup: Mapping[str, object],
) -> ChainState:
    """Rule 18: the state after playing the first week, with the bank derived a second way."""

    outgoing = [int(p) for p in week.transfers_out["player_id"]]
    incoming = [int(p) for p in week.transfers_in["player_id"]]
    purchase = dict(state.purchase_prices)
    for player in outgoing:
        purchase.pop(player)
    for player in incoming:
        purchase[player] = int(current[player])
    squad = tuple(sorted(int(p) for p in week.selected_squad["player_id"]))
    if set(purchase) != set(squad):
        raise ChainError("The played squad does not match the carried purchase prices.")
    proceeds = sum(
        sell_price_tenths(int(current[p]), int(state.purchase_prices[p]), sell_on_fee=fee)
        for p in outgoing
    )
    cost = sum(int(current[p]) for p in incoming)
    if state.bank_tenths + proceeds - cost != int(week.bank_after_tenths):
        raise ChainError("The plan's bank does not follow from its moves (rule 18).")
    return ChainState(
        squad=squad,
        purchase_prices=purchase,
        bank_tenths=int(week.bank_after_tenths),
        free_transfers=int(week.free_transfers_for_next_gameweek),
        decided_gameweek=int(week.gameweek),
        lineup=dict(lineup),
    )


def hold(state: ChainState, gameweek: int, max_free_transfers: int) -> ChainState:
    """Rules 21 and 22: no transfer, one more free transfer up to the captured maximum."""

    return replace(
        state,
        free_transfers=min(state.free_transfers + 1, max_free_transfers),
        decided_gameweek=gameweek,
    )


# ---------------------------------------------------------------------------------------------
# Records (rules 24 and 36 to 38)


def _ids(frame: pd.DataFrame) -> list[int]:
    return [int(p) for p in frame["player_id"]]


def _player_id(player: object) -> int:
    return int(cast(Mapping[str, Any], player)["player_id"])


def players_block(table: pd.DataFrame, wanted: Sequence[int]) -> dict[str, dict[str, object]]:
    """The join map the scorer reads, from the decided week's own forecast rows."""

    pool = {int(str(row["player_id"])): row for _, row in table.iterrows()}
    players = {}
    for player in sorted(set(wanted)):
        row = pool[player]
        players[str(player)] = {
            "name": str(row["name"]),
            "position": str(row["position"]),
            "team": str(row["team_id"]),
            "price_tenths": int(str(row["price_tenths"])),
            "expected_points": float(str(row["expected_points"])),
        }
    return players


def _weeks_summary(plan: TransferPlanResult) -> list[dict[str, object]]:
    return [
        {
            "gameweek": int(week.gameweek),
            "squad": sorted(_ids(week.selected_squad)),
            "starting_xi": sorted(_ids(week.starting_xi)),
            "captain": int(week.captain["player_id"]),
            "transfers_in": _ids(week.transfers_in),
            "transfers_out": _ids(week.transfers_out),
            "bank_after_tenths": int(week.bank_after_tenths),
            "free_transfers_for_next_gameweek": int(week.free_transfers_for_next_gameweek),
            "paid_transfer_count": int(week.paid_transfer_count),
            "projected_score": float(week.projected_score),
            "chip": week.chip,
        }
        for week in plan.weeks
    ]


def replay_identity(document: Mapping[str, object]) -> object:
    """Rule 24: work and clock fields are outside what two writes must agree on."""

    return {key: value for key, value in document.items() if key != "work"}


def _record(**fields: object) -> dict[str, object]:
    return {
        "protocol": PROTOCOL_ID,
        "season": SEASON,
        "outcome_read": False,
        "locked_holdout_accessed": False,
        **fields,
    }


# ---------------------------------------------------------------------------------------------
# Preflight and the frozen source (rules 2, 3 and 39)


def _git(*arguments: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY if cwd is None else cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _git_bytes(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=REPOSITORY, check=True, capture_output=True
    ).stdout


def binding_commits(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Rule 2: the merges that added this protocol and this runner to HEAD's line.

    A file is looked for on HEAD's first-parent line, each commit compared with its first
    parent: a squash merge is found as the squash commit and a normal merge as the merge
    commit, never as the feature commit that wrote the file on its branch.
    """

    commits = {}
    for name, path in (("protocol", PROTOCOL_FILE), ("runner", RUNNER_FILE)):
        added = _git(
            "log",
            "--first-parent",
            "--diff-merges=first-parent",
            "--diff-filter=A",
            "--no-patch",
            "--format=%H %cI",
            "-1",
            "--",
            path,
            cwd=root,
        )
        if not added:
            raise ChainError(f"{path} has no commit; the protocol has not merged.")
        sha, instant = added.split(" ", 1)
        # Its place on the line: two merges of one merge group can share a second.
        position = int(_git("rev-list", "--first-parent", "--count", sha, cwd=root))
        commits[name] = {
            "commit": sha,
            "committed_utc": _instant(instant).isoformat(),
            "line_position": str(position),
        }
    return commits


def binding_instant(commits: Mapping[str, Mapping[str, str]]) -> datetime:
    """Rule 2: the later of the two merges."""

    return max(_instant(entry["committed_utc"]) for entry in commits.values())


def frozen_commit(commits: Mapping[str, Mapping[str, str]]) -> str:
    """Rule 3: the later of the two merge commits on the line is the frozen source.

    Later means further along HEAD's first-parent line; the committer instant only breaks a
    tie between commits whose place was not recorded.
    """

    return max(
        commits.values(),
        key=lambda entry: (int(entry.get("line_position", 0)), _instant(entry["committed_utc"])),
    )["commit"]


def stated_constants_hold() -> None:
    """Rule 11: the entry points' constants are the values the protocol states."""

    for (module, name), stated in STATED_CONSTANTS.items():
        if getattr(module, name) != stated:
            raise ChainError(
                f"{name} is {getattr(module, name)!r}; the protocol states {stated!r}."
            )


def source_identity() -> dict[str, object]:
    """Rule 3: the frozen commit, the two files' sha256, the interpreter, platform and packages."""

    if _git("status", "--porcelain"):
        raise ChainError("The checkout is not clean; the frozen source cannot be named.")
    if not Path(squadopt.__file__).resolve().is_relative_to(REPOSITORY / "src"):
        raise ChainError("squadopt does not resolve into this checkout's src/.")
    commits = binding_commits()
    head = _git("rev-parse", "HEAD")
    frozen = frozen_commit(commits)
    if head != frozen:
        raise ChainError(f"Run from the frozen commit {frozen}; HEAD is {head}.")
    stated_constants_hold()
    return {
        "protocol": PROTOCOL_ID,
        "repository_commit": head,
        "protocol_sha256": hashlib.sha256(_git_bytes("show", f"HEAD:{PROTOCOL_FILE}")).hexdigest(),
        "runner_sha256": hashlib.sha256(_git_bytes("show", f"HEAD:{RUNNER_FILE}")).hexdigest(),
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "versions": {name: package_metadata.version(name) for name in PINNED_PACKAGES},
        "binding_commits": commits,
    }


def first_bound_week(
    index: Sequence[CaptureIndexEntry],
    snapshot_root: Path,
    commits: Mapping[str, Mapping[str, str]],
) -> int:
    """Rule 2: the first gameweek whose deadline, as the newest capture states it, follows the
    later merge; and GW7 at the earliest if either merge missed its date."""

    if not index:
        raise ChainError("No live capture to read the deadlines from.")
    bound = binding_instant(commits)
    newest = max(index, key=lambda entry: entry.captured_at_utc)
    snapshot = read_snapshot(snapshot_root, newest.snapshot_id)
    for deadline in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
        if _instant(deadline.deadline_utc) > bound:
            week = int(deadline.gameweek)
            break
    else:
        raise ChainError("No gameweek deadline falls after the protocol bound.")
    late = (
        _instant(commits["protocol"]["committed_utc"]) >= PROTOCOL_MERGED_BEFORE
        or _instant(commits["runner"]["committed_utc"]) >= RUNNER_MERGED_BEFORE
    )
    return max(week, TARGET_FIRST_WEEK + 1) if late else week


def refuse_unlocked_worktree() -> None:
    """Rule 39: the evidence is uncommitted under an ignored directory, and `git worktree remove`
    deletes ignored files, so the runner refuses a worktree that is not locked."""

    here = REPOSITORY.resolve()
    found = locked = False
    for block in _git("worktree", "list", "--porcelain").split("\n\n"):
        lines = block.strip().splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        if Path(lines[0][len("worktree ") :]).resolve() == here:
            found = True
            locked = any(line == "locked" or line.startswith("locked ") for line in lines)
    if not (found and locked):
        raise ChainError(
            "The evidence lives in this worktree and git worktree remove would delete it; lock "
            'it first: git worktree lock --reason "planner policy chain evidence" (rule 39).'
        )


def refuse_evidence_root(
    copy_root: Path,
    output: Path,
    snapshot_root: Path,
    artifact_root: Path,
    handoff_root: Path | None,
) -> None:
    """Rule 39: the evidence copy root lies outside the checkout and every root the chain reads."""

    resolved = copy_root.resolve()
    roots = [
        REPOSITORY.resolve(),
        output.resolve(),
        snapshot_root.resolve(),
        artifact_root.resolve(),
    ]
    if handoff_root is not None:
        roots.append(handoff_root.resolve())
    for root in roots:
        if resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved):
            raise ChainError(f"The evidence copy root {copy_root} must lie outside {root}.")


def evidence_digest(directory: Path) -> str:
    """The digest of a week's files, each by its relative name and sha256, the manifest left out."""

    digest = hashlib.sha256()
    files = (p for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json")
    for path in sorted(files):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def copy_week_evidence(directory: Path, copy_root: Path) -> tuple[Path, str]:
    """Rule 39: the week's directory copied outside the checkout, once, and checked against the
    digest its manifest records; a copy already there must be the same week."""

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = str(manifest["evidence_digest"])
    if evidence_digest(directory) != expected:
        raise ChainError(f"{directory.name}: the week's files no longer match their manifest.")
    target = copy_root / directory.name
    if target.exists():
        same = (
            evidence_digest(target) == expected
            and (target / "manifest.json").read_bytes() == manifest_path.read_bytes()
        )
        if not same:
            raise ChainError(f"{target} holds a different copy of {directory.name}.")
        return target, expected
    copy_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(directory, target)
    if evidence_digest(target) != expected:
        raise ChainError(f"The copy of {directory.name} does not reproduce its digest.")
    return target, expected


def refuse_output(output: Path, snapshot_root: Path, artifact_root: Path) -> None:
    """Rules 36 and 39: the chain writes only under artifacts/planner_policy_chain/."""

    resolved = output.resolve()
    if not resolved.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ChainError(f"The chain writes only under {OUTPUT_ROOT}.")
    football = football_artifact_path(artifact_root, "chain").parent.resolve()
    for forbidden in (snapshot_root.resolve(), football, REPOSITORY / "data"):
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            raise ChainError(f"The chain never writes under {forbidden}.")


def refuse_roots(snapshot_root: Path, artifact_root: Path, handoff_root: Path | None) -> None:
    """Rule 6: a root that is not the backend's would make every week missing, and a missing
    week is never repaired, so a root that holds nothing the chain reads is refused first."""

    if not snapshot_root.is_dir():
        raise ChainError(f"The capture root {snapshot_root} is not a directory.")
    if not football_artifact_path(artifact_root, "chain").parent.is_dir():
        raise ChainError(f"The artifact root {artifact_root} holds no football forecasts.")
    if handoff_root is not None and not any(
        handoff_path_for(handoff_root, SEASON, gameweek).is_file()
        for gameweek in range(1, LAST_GAMEWEEK + 1)
    ):
        raise ChainError(f"The handoff root {handoff_root} holds no {SEASON} handoff.")


def refuse_before_first_computation(now: datetime) -> None:
    """Rule 40: nothing is computed before the freeze ends, not even an inventory."""

    if now < FIRST_COMPUTATION:
        raise ChainError(
            f"No decision is computed before {FIRST_COMPUTATION.isoformat()}, the end of the "
            "freeze (rule 40)."
        )


def refuse_day(now: datetime) -> None:
    """Rule 39: never on a Tuesday or a Friday, in the operator's time."""

    if now.astimezone(OPERATOR_ZONE).weekday() in REFUSED_WEEKDAYS:
        raise ChainError("The decision step never runs on a Tuesday or a Friday (rule 39).")


@contextmanager
def single_run(output: Path) -> Iterator[None]:
    """Rule 39: one decision step at a time. A lock left by a crash is removed by hand."""

    output.mkdir(parents=True, exist_ok=True)
    lock = output / "run.lock"
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ChainError(
            f"Another decision step holds {lock}; remove it only if none runs."
        ) from error
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.close(handle)
        yield
    finally:
        lock.unlink(missing_ok=True)


def bind_protocol(output: Path, identity: Mapping[str, object]) -> dict[str, Any] | None:
    """Rule 3: the recorded identity, refusing a run whose identity differs; None on a first run."""

    path = output / "protocol.json"
    if not path.exists():
        return None
    recorded = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    for key, value in identity.items():
        if recorded.get(key) != value:
            raise ChainError(f"This run's {key} differs from the frozen source's.")
    return recorded


# ---------------------------------------------------------------------------------------------
# Commands


def check(
    snapshot_root: Path,
    artifact_root: Path,
    *,
    handoff_root: Path | None = None,
    now: datetime | None = None,
    emit: Callable[[str], None] = print,
) -> None:
    """List each week's capture, whether its deadline has passed and its forecast; write nothing."""

    moment = datetime.now(UTC) if now is None else now
    refuse_roots(snapshot_root, artifact_root, handoff_root)
    index = capture_index(snapshot_root, handoff_root)
    first = first_bound_week(index, snapshot_root, binding_commits())
    for gameweek in range(first, LAST_GAMEWEEK + 1):
        pending = moment <= deadline_of(index, snapshot_root, gameweek)
        selection = decision_capture(index, gameweek)
        label = "pending" if pending else "final"
        if selection.snapshot_id is None:
            emit(f"GW{gameweek:02d} {label} missing {selection.reason}")
            continue
        loaded = week_inputs(
            snapshot_root, artifact_root, selection.snapshot_id, handoff_root=handoff_root
        )
        status = "ready" if isinstance(loaded, WeekInputs) else loaded[0]
        emit(f"GW{gameweek:02d} {label} {selection.snapshot_id} {status}")


@dataclass
class ChainRecord:
    """One chain's record for one week, before it is written."""

    name: str
    document: dict[str, object]
    state_after: ChainState
    blocked: bool = False


def _chain_record(
    chain: tuple[str, str],
    state: ChainState,
    gameweek: int,
    week: WeekInputs | tuple[str, Mapping[str, object]],
    blocked: set[tuple[str, str]],
    commit: object,
    max_free: int,
) -> ChainRecord:
    """Rules 17 to 23 for one chain: blocked first, then a missing week, then the arm."""

    profile, arm = chain
    base: dict[str, object] = {
        "gameweek": gameweek,
        "profile": profile,
        "arm": arm,
        "capture_snapshot_id": week.receipt["snapshot_id"]
        if isinstance(week, WeekInputs)
        else week[1].get("snapshot_id"),
        "state_before": state.to_json(),
        "provenance": {"repository_commit": commit},
    }
    name = f"{profile}-{arm}.json"
    if chain in blocked:
        after = replace(state, decided_gameweek=gameweek)
        return ChainRecord(
            name, _record(**base, status="blocked", reason="held_player_absent"), after, True
        )
    if not isinstance(week, WeekInputs):
        after = hold(state, gameweek, max_free)
        document = _record(**base, status="held", reason=week[0], state_after=after.to_json())
        return ChainRecord(name, document, after)
    roster = {int(p) for p in week.inputs.players.player_id}
    if not set(state.squad) <= roster:
        blocked.add(chain)
        after = replace(state, decided_gameweek=gameweek)
        return ChainRecord(
            name, _record(**base, status="blocked", reason="held_player_absent"), after, True
        )
    outcome = run_arm(arm, week, state.held())
    policy = {
        "route": outcome.route,
        "route_version": outcome.route_version,
        "weeks": list(outcome.weeks),
        "truncated": outcome.truncated,
        "deterministic_units": outcome.deterministic_units,
        "wall_ceiling_seconds": outcome.wall_ceiling_seconds,
        "configuration_fingerprint": outcome.configuration_fingerprint,
        "horizon_fingerprint": outcome.horizon_fingerprint,
    }
    table = week.forecast.projection.table
    if outcome.failure is not None or outcome.plan is None or outcome.lineup is None:
        after = hold(state, gameweek, max_free)
        held_team = None if state.lineup is None else {**state.lineup, "transfer_hit_points": 0.0}
        document = _record(
            **base,
            status="failed",
            reason=outcome.failure,
            policy=policy,
            solver=outcome.status,
            advice=held_team,
            players=players_block(table, list(state.squad)),
            state_after=after.to_json(),
            work=outcome.work,
        )
        return ChainRecord(name, document, after)
    first = outcome.plan.weeks[0]
    current = {
        int(p): int(c)
        for p, c in zip(
            week.inputs.players.player_id, week.inputs.players.price_tenths, strict=True
        )
    }
    after = advance(state, first, current, float(week.rules.transfers.sell_on_fee), outcome.lineup)
    document = _record(
        **base,
        status="decided",
        forecast={
            "sha256": week.receipt["artifact_sha256"],
            "fingerprint": week.forecast.fingerprint,
            "model_version": week.forecast.horizon.model_version,
        },
        policy=policy,
        solver=outcome.status,
        plan={"weeks": _weeks_summary(outcome.plan)},
        advice=outcome.lineup,
        players=players_block(table, _ids(first.selected_squad)),
        state_after=after.to_json(),
        work=outcome.work,
    )
    return ChainRecord(name, document, after)


def _refuse_unequal_twins(records: Mapping[tuple[str, str], ChainRecord]) -> None:
    """Rule 12: where served and hold plan from one state, their plans' fingerprints agree."""

    for (profile, arm), record in records.items():
        if not arm.startswith("served_"):
            continue
        twin = records.get((profile, "hold_" + arm.rsplit("_", 1)[1]))
        if twin is None:
            continue
        before = ChainState.from_json(cast(Mapping[str, Any], record.document["state_before"]))
        twin_before = ChainState.from_json(cast(Mapping[str, Any], twin.document["state_before"]))
        if not before.same_holding(twin_before):
            continue
        policies = [r.document.get("policy") for r in (record, twin)]
        if not all(isinstance(p, dict) and p.get("horizon_fingerprint") for p in policies):
            continue
        ours, theirs = (cast(Mapping[str, object], p) for p in policies)
        for key in ("configuration_fingerprint", "horizon_fingerprint"):
            if ours[key] != theirs[key]:
                raise ChainError(f"{profile}: served and hold differ in {key} (rule 12).")


def decide_week(
    output: Path,
    gameweek: int,
    week: WeekInputs | tuple[str, Mapping[str, object]],
    states: Mapping[tuple[str, str], ChainState],
    blocked: set[tuple[str, str]],
    commit: object,
    last_max_free_transfers: int,
    moment: datetime | None = None,
) -> tuple[dict[tuple[str, str], ChainState], int, str]:
    """Rules 17 to 24 for one gameweek: every chain is computed, checked, then written.

    A record already on disk from an interrupted run is carried as it stands rather than
    solved again (rule 24). Returns the states after the week, the free-transfer maximum a
    later missing week holds to, and the manifest's sha256 for the operator's receipt.
    """

    directory = output / f"gw{gameweek:02d}"
    receipt = week.receipt if isinstance(week, WeekInputs) else week[1]
    written = directory / "receipt.json"
    if written.exists():
        earlier = json.loads(written.read_text(encoding="utf-8")).get("snapshot_id")
        if earlier != receipt.get("snapshot_id"):
            raise ChainError(
                f"GW{gameweek:02d} was started from {earlier} and would now be decided from "
                f"{receipt.get('snapshot_id')}; the capture inventory changed under the chain."
            )
    max_free = last_max_free_transfers
    if isinstance(week, WeekInputs):
        max_free = int(week.rules.transfers.max_free_transfers)
    records: dict[tuple[str, str], ChainRecord] = {}
    for chain, state in sorted(states.items()):
        path = directory / f"{chain[0]}-{chain[1]}.json"
        if path.exists():
            document = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
            is_blocked = document["status"] == "blocked"
            after = (
                replace(state, decided_gameweek=gameweek)
                if is_blocked
                else ChainState.from_json(cast(Mapping[str, Any], document["state_after"]))
            )
            if is_blocked:
                blocked.add(chain)
            records[chain] = ChainRecord(path.name, document, after, is_blocked)
            continue
        records[chain] = _chain_record(chain, state, gameweek, week, blocked, commit, max_free)
    _refuse_unequal_twins(records)
    write_document_once(_record(gameweek=gameweek, **dict(receipt)), directory / "receipt.json")
    if isinstance(week, WeekInputs):
        write_bytes_once(week.artifact_bytes, directory / "forecast.json")
    digests: dict[str, str] = {}
    for record in records.values():
        path = directory / record.name
        write_document_once(record.document, path, replay_identity=replay_identity)
        digests[record.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = _record(
        gameweek=gameweek,
        capture_snapshot_id=receipt.get("snapshot_id"),
        missing_reason=None if isinstance(week, WeekInputs) else week[0],
        max_free_transfers=max_free,
        records=digests,
        evidence_digest=evidence_digest(directory),
        work={"decided_at_utc": None if moment is None else moment.isoformat()},
    )
    write_document_once(manifest, directory / "manifest.json", replay_identity=replay_identity)
    after_states = {chain: record.state_after for chain, record in records.items()}
    return (
        after_states,
        max_free,
        hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
    )


def _load_week(
    directory: Path, blocked: set[tuple[str, str]]
) -> tuple[dict[tuple[str, str], ChainState], int]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    states: dict[tuple[str, str], ChainState] = {}
    for name in manifest["records"]:
        record = json.loads((directory / name).read_text(encoding="utf-8"))
        chain = (str(record["profile"]), str(record["arm"]))
        if record["status"] == "blocked":
            blocked.add(chain)
            states[chain] = replace(
                ChainState.from_json(record["state_before"]),
                decided_gameweek=int(manifest["gameweek"]),
            )
        else:
            states[chain] = ChainState.from_json(record["state_after"])
    return states, int(manifest["max_free_transfers"])


def _week(
    index: Sequence[CaptureIndexEntry],
    snapshot_root: Path,
    artifact_root: Path,
    gameweek: int,
    *,
    handoff_root: Path | None = None,
) -> WeekInputs | tuple[str, Mapping[str, object]]:
    own = [
        {
            "snapshot_id": entry.snapshot_id,
            "captured_at_utc": entry.captured_at_utc.isoformat(),
            "served": entry.served,
        }
        for entry in sorted(index, key=lambda entry: (entry.captured_at_utc, entry.snapshot_id))
        if entry.target == gameweek
    ]
    selection = decision_capture(index, gameweek)
    if selection.snapshot_id is None:
        reason = selection.reason or "no_own_target_capture"
        return reason, {"snapshot_id": None, "reason": reason, "own_target_captures": own}
    loaded = week_inputs(
        snapshot_root, artifact_root, selection.snapshot_id, handoff_root=handoff_root
    )
    if isinstance(loaded, WeekInputs):
        return replace(loaded, receipt={**loaded.receipt, "own_target_captures": own})
    return loaded[0], {**loaded[1], "own_target_captures": own}


def start_chain(
    output: Path,
    identity: Mapping[str, object],
    answer: str,
    index: Sequence[CaptureIndexEntry],
    snapshot_root: Path,
    artifact_root: Path,
    moment: datetime,
    *,
    handoff_root: Path | None = None,
) -> dict[str, Any] | None:
    """Rules 2, 9 and 40: the first chain week, its squads and the protocol record, once.

    Nothing is written until a week whose deadline has passed has a usable forecast; a missing
    week before it is skipped and listed. Returns the protocol record, or None while waiting.
    """

    if moment > deadline_of(index, snapshot_root, LAPSE_GAMEWEEK):
        raise ChainError(
            f"No chain started before GW{LAPSE_GAMEWEEK}'s deadline; the protocol lapsed unrun "
            "(rule 40)."
        )
    commits = cast(Mapping[str, Mapping[str, str]], identity["binding_commits"])
    bound_week = first_bound_week(index, snapshot_root, commits)
    skipped: list[dict[str, object]] = []
    for gameweek in range(bound_week, LAST_GAMEWEEK + 1):
        if moment <= deadline_of(index, snapshot_root, gameweek):
            return None
        week = _week(index, snapshot_root, artifact_root, gameweek, handoff_root=handoff_root)
        if not isinstance(week, WeekInputs):
            skipped.append({"gameweek": gameweek, "reason": week[0]})
            continue
        squads = initial_states(week.forecast, gameweek)
        for profile, state in squads.states.items():
            write_document_once(
                _record(
                    profile=profile, state=state.to_json(), statuses=list(squads.statuses[profile])
                ),
                output / "initial" / f"{profile}.json",
            )
        protocol = {
            **identity,
            "season": SEASON,
            "answer": answer,
            "bound_week": bound_week,
            "first_chain_week": gameweek,
            "max_free_transfers": int(week.rules.transfers.max_free_transfers),
            "skipped_weeks": skipped,
            "dropped_profiles": dict(squads.dropped),
            "squad_statuses": {k: list(v) for k, v in squads.statuses.items()},
            "outcome_read": False,
            "locked_holdout_accessed": False,
        }
        write_document_once(protocol, output / "protocol.json")
        return protocol
    raise ChainError("No gameweek in the season has a usable forecast.")


def decide(
    snapshot_root: Path,
    artifact_root: Path,
    output: Path,
    through_gameweek: int,
    answer: str,
    *,
    handoff_root: Path | None = None,
    evidence_copy_root: Path | None = None,
    now: datetime | None = None,
    emit: Callable[[str], None] = print,
) -> None:
    """Write every undecided gameweek through ``through_gameweek`` whose deadline has passed."""

    moment = datetime.now(UTC) if now is None else now
    if not answer.strip():
        raise ChainError("Name the Answer on #632 that names the operator (rule 40).")
    refuse_day(moment)
    refuse_before_first_computation(moment)
    refuse_output(output, snapshot_root, artifact_root)
    refuse_roots(snapshot_root, artifact_root, handoff_root)
    if evidence_copy_root is not None:
        refuse_evidence_root(evidence_copy_root, output, snapshot_root, artifact_root, handoff_root)
    refuse_unlocked_worktree()
    identity = source_identity()
    with single_run(output):
        lines: list[str] = []

        def say(line: str) -> None:
            lines.append(line)
            emit(line)

        try:
            _decide_weeks(
                snapshot_root,
                artifact_root,
                output,
                through_gameweek,
                answer,
                identity,
                moment,
                say,
                handoff_root=handoff_root,
                evidence_copy_root=evidence_copy_root,
            )
        except ChainError as error:
            lines.append(f"refused: {error}")
            raise
        finally:
            _log_run(output, moment, identity["repository_commit"], lines)


def _log_run(output: Path, moment: datetime, commit: object, lines: Sequence[str]) -> None:
    """Rule 24: one line per run, appended; the run log is the only file written twice."""

    with (output / "runs.log").open("a", encoding="utf-8") as log:
        log.write(f"{moment.isoformat()} {commit} {' | '.join(lines) or 'nothing to decide'}\n")


def _decide_weeks(
    snapshot_root: Path,
    artifact_root: Path,
    output: Path,
    through_gameweek: int,
    answer: str,
    identity: Mapping[str, object],
    moment: datetime,
    emit: Callable[[str], None],
    *,
    handoff_root: Path | None = None,
    evidence_copy_root: Path | None = None,
) -> None:
    inventory = capture_inventory(snapshot_root, handoff_root)
    index = inventory.entries
    if inventory.closed:
        emit(f"left out {len(inventory.closed)} captures taken after every deadline")
    protocol = bind_protocol(output, identity)
    if protocol is None:
        protocol = start_chain(
            output,
            identity,
            answer,
            index,
            snapshot_root,
            artifact_root,
            moment,
            handoff_root=handoff_root,
        )
        if protocol is None:
            emit("waiting: no first chain week has both a passed deadline and a forecast")
            return
    first = int(protocol["first_chain_week"])
    states: dict[tuple[str, str], ChainState] = {}
    for profile in sorted(
        set(f"p{budget}" for budget, _, _ in PROFILES) - set(protocol["dropped_profiles"])
    ):
        state = ChainState.from_json(
            json.loads((output / "initial" / f"{profile}.json").read_text(encoding="utf-8"))[
                "state"
            ]
        )
        states.update({(profile, arm): state for arm in ARMS})
    blocked: set[tuple[str, str]] = set()
    # Rule 21: a first week that reads as missing on a later read still holds to the season
    # maximum the first read recorded, never to zero.
    max_free = int(protocol.get("max_free_transfers", 0))
    for gameweek in range(first, min(through_gameweek, LAST_GAMEWEEK) + 1):
        directory = output / f"gw{gameweek:02d}"
        if (directory / "manifest.json").exists():
            states, max_free = _load_week(directory, blocked)
            _copy_evidence(directory, evidence_copy_root, emit)
            continue
        if moment <= deadline_of(index, snapshot_root, gameweek):
            emit(f"GW{gameweek:02d} pending: its deadline has not passed")
            return
        week = _week(index, snapshot_root, artifact_root, gameweek, handoff_root=handoff_root)
        states, max_free, digest = decide_week(
            output,
            gameweek,
            week,
            states,
            blocked,
            identity["repository_commit"],
            max_free,
            moment,
        )
        source = (
            week.receipt["snapshot_id"] if isinstance(week, WeekInputs) else f"missing {week[0]}"
        )
        emit(f"GW{gameweek:02d} decided from {source}; manifest sha256 {digest}")
        _copy_evidence(directory, evidence_copy_root, emit)


def _copy_evidence(directory: Path, copy_root: Path | None, emit: Callable[[str], None]) -> None:
    if copy_root is None:
        return
    target, digest = copy_week_evidence(directory, copy_root)
    emit(f"{directory.name} evidence copied to {target.name} under the copy root; digest {digest}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "decide"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot-root", type=Path, required=True)
        command.add_argument("--artifact-root", type=Path, required=True)
        # Rules 6 and 8: the backend's handoff root, its served baseline handoff used for its
        # fingerprint only. No club-news source is taken: only news a ready bundle seals binds.
        command.add_argument("--handoff-root", type=Path, required=True)
        if name == "decide":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--through-gameweek", type=int, required=True)
            command.add_argument("--answer", required=True)
            # Rule 39: each decided week is copied outside the checkout, where a worktree
            # cleanup cannot reach it.
            command.add_argument("--evidence-copy-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "check":
            check(
                arguments.snapshot_root,
                arguments.artifact_root,
                handoff_root=arguments.handoff_root,
            )
        else:
            decide(
                arguments.snapshot_root,
                arguments.artifact_root,
                arguments.output,
                arguments.through_gameweek,
                arguments.answer,
                handoff_root=arguments.handoff_root,
                evidence_copy_root=arguments.evidence_copy_root,
            )
    except ChainError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
