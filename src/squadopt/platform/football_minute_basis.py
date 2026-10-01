"""Read an optional fixture basis beside a served forecast, without fitting a model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import RecommendationInputs
from squadopt.live.football_artifact import FootballForecast, football_artifact_path
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.prediction.availability import apply_availability


@dataclass(frozen=True, slots=True)
class FootballMinuteBasisLoad:
    basis: FixtureComponentBasis | None
    components_sha256: str | None
    reason: str | None


def football_components_path(root: Path, snapshot_id: str) -> Path:
    """The exact capture sibling; never search other captures for a usable basis."""
    return football_artifact_path(root, snapshot_id).with_suffix(".components.json")


def _basis_from_snapshot(
    served: dict[str, Any],
    companion: dict[str, Any],
    snapshot: CapturedSnapshot,
    inputs: RecommendationInputs,
    football: FootballForecast,
) -> FixtureComponentBasis:
    if (
        snapshot.metadata.snapshot_id != inputs.snapshot_id
        or snapshot.metadata.captured_at_utc != inputs.captured_at_utc
        or served.get("source_fingerprint") != snapshot.metadata.fingerprint
        or served.get("fingerprint") != football.fingerprint
        or served.get("season") != inputs.season
        or served.get("gameweek") != inputs.deadline.gameweek
        or served.get("captured_at_utc") != inputs.captured_at_utc
        or served.get("source_snapshot_id") != inputs.snapshot_id
    ):
        raise ValueError("Fixture basis does not identify the served source capture.")
    bootstrap = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    clubs = {team["id"]: team["code"] for team in bootstrap["teams"]}
    source_players = {player["code"]: clubs[player["team"]] for player in bootstrap["elements"]}
    roster_clubs = {int(player): int(source_players[player]) for player in inputs.players.player_id}
    fixtures = pd.DataFrame(json.loads(snapshot.payloads[FIXTURES_PAYLOAD]))
    fixtures = fixtures.loc[fixtures.event.isin(football.horizon.table.gameweek.unique())]
    if fixtures.empty or fixtures.kickoff_time.isna().any():
        raise ValueError("A dated captured league calendar is required.")
    # An unassigned fixture elsewhere in the capture gives the entire event column
    # a float dtype. Restore the selected integer gameweeks before strict validation.
    if fixtures.event.isna().any() or not fixtures.event.mod(1).eq(0).all():
        raise ValueError("Captured league gameweeks must be integers.")
    fixtures = fixtures.copy()
    fixtures["event"] = fixtures.event.astype(int)
    calendar = pd.concat(
        [
            pd.DataFrame(
                {
                    "fixture": fixtures.id,
                    "club": fixtures["team_h" if home else "team_a"].map(clubs),
                    "opponent": fixtures["team_a" if home else "team_h"].map(clubs),
                    "home": int(home),
                    "GW": fixtures.event,
                    "kickoff": pd.to_datetime(fixtures.kickoff_time, utc=True),
                }
            )
            for home in (True, False)
        ],
        ignore_index=True,
    )
    basis = FixtureComponentBasis.from_documents(
        served, companion, fixture_calendar=calendar, roster_clubs=roster_clubs
    )
    # Check the captured multiplier even for zero-point/zero-q players, for whom a
    # comparison of scaled points alone cannot detect a mismatched header.
    actual = (
        apply_availability(inputs.players.assign(expected_points=1.0), inputs.availability)
        .table.set_index("player_id")
        .expected_points
    )
    declared = pd.Series(
        {
            entry["player_code"]: entry["multiplier"]
            for entry in companion["captured_availability"]["multipliers"]
        }
    ).reindex(actual.index)
    if not np.allclose(actual, declared, rtol=0.0, atol=1e-12):
        raise ValueError("Component availability differs from the captured rule.")
    keys = ["gameweek", "player_id"]
    loaded = football.horizon.table.set_index(keys).sort_index()
    rebuilt = basis.weekly_rows.set_index(keys).sort_index()
    if not loaded.index.equals(rebuilt.index):
        raise ValueError("Component weeks differ from the loaded football horizon.")
    for column in ("expected_points", "appearance_probability"):
        if not np.allclose(loaded[column], rebuilt[column], rtol=1e-12, atol=1e-12):
            raise ValueError("Component points or participation differ from the loaded basis.")
    return basis


def load_football_minute_basis(
    *,
    artifact_root: Path | None,
    snapshot_root: Path | None,
    inputs: RecommendationInputs,
    football: FootballForecast,
) -> FootballMinuteBasisLoad:
    """A missing or refused optional companion cannot disable the served forecast.

    The raw digest addresses every readable candidate, including invalid JSON. The
    verified document fingerprint remains inside ``basis``. No producer, archive,
    latest-capture discovery, queue, cache or external service is consulted here.
    """
    if artifact_root is None:
        return FootballMinuteBasisLoad(None, None, "missing_components")
    path = football_components_path(artifact_root, inputs.snapshot_id)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return FootballMinuteBasisLoad(None, None, "missing_components")
    except OSError:
        return FootballMinuteBasisLoad(None, None, "unreadable_components")
    digest = hashlib.sha256(raw).hexdigest()
    if snapshot_root is None:
        return FootballMinuteBasisLoad(None, digest, "missing_source_snapshot")
    try:
        companion = json.loads(raw)
        served = json.loads(
            football_artifact_path(artifact_root, inputs.snapshot_id).read_text(encoding="utf-8")
        )
        if not isinstance(served, dict) or not isinstance(companion, dict):
            raise ValueError("Football fixture documents must be objects.")
        snapshot = read_snapshot(snapshot_root, inputs.snapshot_id)
        basis = _basis_from_snapshot(served, companion, snapshot, inputs, football)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, DataError):
        return FootballMinuteBasisLoad(None, digest, "invalid_components_or_source")
    return FootballMinuteBasisLoad(basis, digest, None)
