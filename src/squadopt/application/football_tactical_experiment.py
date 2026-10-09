"""Private explicit tactical replacement and bounded fixed-fifteen comparison.

The native fixture components remain the minute, defensive contribution and residual
basis. Tactical offsets must reproduce their complete control moments before any
replacement. Captured eligibility is applied once per player and gameweek afterwards.
This module is not connected to a public producer, worker or release command.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from numbers import Integral, Real
from typing import cast

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant
from squadopt.data.timestamps import normalize_utc_timestamp as _normalize_utc_timestamp
from squadopt.features.football_tactical_inputs import (
    PROTECTED_SEASON,
    TacticalProjection,
    projection_digest,
    validate_tactical_projection,
)
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_components import (
    COMPONENT_COLUMNS,
    IDENTITY_COLUMNS,
    component_rows,
)
from squadopt.prediction.football_tactical_matchup import (
    FEATURE_VERSION,
    MODEL_VERSION,
    TacticalAllocatedPlayer,
    TacticalAllocation,
    TacticalMatchupModel,
    normalized_state_weights,
)
from squadopt.scenarios.expected_lineup import ExpectedLineupSearchResult, improve_expected_lineup

EXPERIMENT_VERSION = "football_tactical_experiment_v1"
FIXED_FIFTEEN_VERSION = "football_tactical_fixed_fifteen_v1"
RECEIPT_ATTR = "football_tactical_experiment_receipt"
ROSTER_COLUMNS = (
    "player_id",
    "name",
    "team_id",
    "club_code",
    "position",
    "buy_price_tenths",
    "sell_price_tenths",
)
CALENDAR_COLUMNS = ("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at")
MINUTE_PROBABILITIES = tuple(f"minute_probability_{b}" for b in range(4))
MINUTE_VALUES = tuple(f"minute_value_{b}" for b in range(4))
EXPERIMENT_RECEIPT_FIELDS = (
    "contract_version",
    "enabled",
    "control",
    "season",
    "gameweeks",
    "captured_at",
    "native_cutoff",
    "deadline_at",
    "model_version",
    "feature_version",
    "model_metadata",
    "projection_sha256",
    "native_components_sha256",
    "components_sha256",
    "weekly_sha256",
    "roster_sha256",
    "calendar_sha256",
    "resource_bundle_sha256",
    "captured_availability",
    "eligibility_scope",
    "replacement_scope",
    "retained_scope",
    "control_binding",
    "lineup_proof_scope",
)


@dataclass(frozen=True)
class TacticalExperiment:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    receipt_json: str
    resource_bundle_json: str

    @property
    def table(self) -> pd.DataFrame:
        return self.weekly


@dataclass(frozen=True)
class TacticalFixedFifteenPlan:
    squad: pd.DataFrame
    search: ExpectedLineupSearchResult
    resource_bundle_json: str
    receipt_json: str


def _integer(value: object, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum:
        raise ValueError(f"{label} must be an explicit integer at least {minimum}.")
    return int(value)


def _finite(
    value: object, label: str, minimum: float | None = None, maximum: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be an explicit finite number.")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} exceeds finite numerical support.") from error
    if (
        not math.isfinite(result)
        or (minimum is not None and result < minimum)
        or (maximum is not None and result > maximum)
    ):
        raise ValueError(f"{label} is outside its finite support.")
    return result


def _canonical(value: object) -> object:
    if value is None or type(value) in (str, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return _finite(value, "private receipt number")
    if isinstance(value, pd.Timestamp):
        return normalize_utc_timestamp(value.isoformat(), label="private receipt timestamp")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError("Private receipt objects require named string keys.")
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise ValueError("Private receipts require canonical JSON-compatible values.")


def _json(value: object) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def normalize_utc_timestamp(value: object, *, label: str) -> str:
    try:
        return _normalize_utc_timestamp(value, label=label)
    except DataError as error:
        raise ValueError(f"{label} requires an explicit UTC instant.") from error


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _frame_digest(frame: pd.DataFrame) -> str:
    attrs = {key: value for key, value in frame.attrs.items() if key != RECEIPT_ATTR}
    return _sha(
        _json(
            {
                "columns": list(frame.columns),
                "rows": frame.to_dict("records"),
                "index": frame.index.tolist(),
                "attrs": attrs,
            }
        )
    )


def _frame(
    value: object, columns: tuple[str, ...], label: str, *, allowed_receipt: str | None = None
) -> pd.DataFrame:
    if (
        not isinstance(value, pd.DataFrame)
        or value.columns.duplicated().any()
        or not value.index.is_unique
        or not all(isinstance(c, str) for c in value.columns)
    ):
        raise ValueError(f"{label} must be a DataFrame with unique named columns.")
    if not set(columns) <= set(value):
        raise ValueError(f"{label} lacks its complete declared columns.")
    if RECEIPT_ATTR in value.attrs and value.attrs[RECEIPT_ATTR] != allowed_receipt:
        raise ValueError("Tactical replacements cannot be reapplied to an existing receipt.")
    _frame_digest(value)
    return value.copy(deep=True)


def _close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"Native tactical control {label} differs from its captured component.")


def _raw_points(record: Mapping[str, object], season: str) -> float:
    position = str(record["position"])
    goal = {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}[position]
    clean = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[position]
    return math.fsum(
        (
            float(cast(float, record["appearance_probability"])),
            float(cast(float, record["p60"])),
            goal * float(cast(float, record["goals"])),
            3 * float(cast(float, record["assists"])),
            clean * float(cast(float, record["clean_sheet_probability"])),
            (2 * float(cast(float, record["defcon_probability"])) if season >= "2025-26" else 0),
            float(cast(float, record["appearance_probability"]))
            * float(cast(float, record["residual_if_appearance"])),
        )
    )


def _roster(frame: pd.DataFrame) -> None:
    if frame.empty or frame.player_id.duplicated().any():
        raise ValueError("A complete unique native decision roster is required.")
    clubs_to_teams: dict[int, set[int]] = {}
    teams_to_clubs: dict[int, set[int]] = {}
    for row in frame.to_dict("records"):
        _integer(row["player_id"], "player_id")
        club, team = _integer(row["club_code"], "club_code"), _integer(row["team_id"], "team_id")
        if (
            row["position"] not in ("GK", "DEF", "MID", "FWD")
            or not isinstance(row["name"], str)
            or not row["name"].strip()
        ):
            raise ValueError("A native roster needs explicit position and name.")
        for name in ("buy_price_tenths", "sell_price_tenths"):
            _integer(row[name], name, 0)
        if "club" in row and _integer(row["club"], "club") != club:
            raise ValueError("Native roster club fields disagree on persistent identity.")
        clubs_to_teams.setdefault(club, set()).add(team)
        teams_to_clubs.setdefault(team, set()).add(club)
    if any(len(v) != 1 for v in (*clubs_to_teams.values(), *teams_to_clubs.values())):
        raise ValueError("Persistent clubs and season team IDs must map one to one.")


def _calendar(
    frame: pd.DataFrame,
    *,
    cutoff: str,
    deadline: str,
    weeks: tuple[int, ...],
    clubs: set[int],
    season: str,
) -> pd.DataFrame:
    for row in frame.to_dict("records"):
        for name in ("fixture", "club", "opponent", "GW"):
            _integer(row[name], name)
        if int(row["GW"]) > 38 or _finite(row["home"], "home") not in (0, 1):
            raise ValueError("A native calendar has an invalid gameweek or side.")
        kickoff = normalize_utc_timestamp(
            pd.Timestamp(row["kickoff"]).isoformat(), label="calendar kickoff"
        )
        year = int(season[:4])
        if (
            not as_instant(f"{year}-07-01T00:00:00Z")
            <= as_instant(kickoff)
            < as_instant(f"{year + 1}-08-01T00:00:00Z")
        ):
            raise ValueError("Native calendar kickoff disagrees with its declared season.")
        if normalize_utc_timestamp(row["decision_at"], label="calendar decision") != cutoff:
            raise ValueError("Native calendar disagrees with the common captured decision.")
    if frame.duplicated(["fixture", "club"]).any():
        raise ValueError("Native calendar repeats a paired fixture side.")
    for _, match in frame.groupby("fixture", sort=True):
        if (
            len(match) != 2
            or match.club.nunique() != 2
            or set(match.home) != {0, 1}
            or match.GW.nunique() != 1
            or match.kickoff.nunique() != 1
            or set(match.club) != set(match.opponent)
        ):
            raise ValueError("Native calendar requires complete opposing fixture sides.")
        one, two = match.to_dict("records")
        if one["opponent"] != two["club"] or two["opponent"] != one["club"]:
            raise ValueError("Native calendar sides have inconsistent opponent identities.")
    covered = frame.attrs.get("covered_gameweeks", tuple(sorted(set(int(v) for v in frame.GW))))
    if (
        not isinstance(covered, (tuple, list))
        or any(type(w) is not int or not 1 <= w <= 38 for w in covered)
        or len(set(covered)) != len(covered)
        or not set(int(v) for v in frame.GW) <= set(covered)
        or not set(weeks) <= set(covered)
    ):
        raise ValueError("Native calendar does not capture every requested gameweek.")
    selected = frame.loc[frame.GW.isin(weeks)].copy(deep=True)
    if not set(int(v) for v in selected.club) <= clubs:
        raise ValueError("The calendar names clubs outside the complete native roster.")
    for kickoff in selected.kickoff:
        instant = as_instant(
            normalize_utc_timestamp(pd.Timestamp(kickoff).isoformat(), label="calendar kickoff")
        )
        if instant <= as_instant(cutoff) or instant < as_instant(deadline):
            raise ValueError("Forecast calendar includes a fixture before its decision/deadline.")
    return selected


def _native_components(
    frame: pd.DataFrame, *, roster: pd.DataFrame, calendar: pd.DataFrame, season: str, cutoff: str
) -> dict[tuple[int, int], dict[str, object]]:
    if frame.attrs.get("availability_application", "not_applied") != "not_applied":
        raise ValueError("Native tactical components already include captured eligibility.")
    if "availability_multiplier" in frame:
        for value in frame.availability_multiplier:
            if _finite(value, "native availability_multiplier") != 1:
                raise ValueError("Native tactical components already include captured eligibility.")
    if "captured_availability_multiplier" in frame:
        raise ValueError("Native tactical components already include captured eligibility.")
    expected: set[tuple[int, int]] = set()
    identities = {
        int(cast(int, key)): {str(name): value for name, value in row.items()}
        for key, row in roster.set_index("player_id").to_dict("index").items()
    }
    calendar_rows = {(int(r["fixture"]), int(r["club"])): r for r in calendar.to_dict("records")}
    for row in calendar.to_dict("records"):
        expected.update(
            (int(row["fixture"]), int(player))
            for player in roster.loc[roster.club_code.eq(row["club"]), "player_id"]
        )
    actual: dict[tuple[int, int], dict[str, object]] = {}
    for row in frame.to_dict("records"):
        if normalize_utc_timestamp(row["decision_at"], label="native decision") != cutoff:
            raise ValueError("Native components disagree with the common captured decision.")
        for name in ("GW", "fixture", "club", "opponent", "player_code"):
            _integer(row[name], name)
        _finite(row["home"], "home", 0, 1)
        for name in COMPONENT_COLUMNS:
            _finite(row[name], name)
        fixture, code, club = int(row["fixture"]), int(row["player_code"]), int(row["club"])
        key = (fixture, code)
        if key in actual or code not in identities or (fixture, club) not in calendar_rows:
            raise ValueError("Native tactical components repeat or invent a player-fixture.")
        identity, scheduled = identities[code], calendar_rows[(fixture, club)]
        if identity["club_code"] != club or identity["position"] != row["position"]:
            raise ValueError("Native player-fixture roster identity differs from the capture.")
        if any(
            row[name] != scheduled[name] for name in ("GW", "opponent", "home")
        ) or normalize_utc_timestamp(
            pd.Timestamp(row["kickoff"]).isoformat(), label="native kickoff"
        ) != normalize_utc_timestamp(
            pd.Timestamp(scheduled["kickoff"]).isoformat(), label="calendar kickoff"
        ):
            raise ValueError("Native component calendar identity differs from the full capture.")
        if row["model_version"] != FOOTBALL_MODEL_VERSION:
            raise ValueError("This tactical experiment requires the frozen native v1 basis.")
        if "season" in row and row["season"] != season:
            raise ValueError("Native tactical components name another scoring season.")
        probabilities = [float(cast(float, row[name])) for name in MINUTE_PROBABILITIES]
        minutes = [float(cast(float, row[name])) for name in MINUTE_VALUES]
        if not (
            minutes[0] == 0
            and 0 < minutes[1] < 60
            and 60 <= minutes[2] < 90
            and 90 <= minutes[3] <= 120
        ):
            raise ValueError("Native minute bins have invalid declared support.")
        _close(
            float(cast(float, row["appearance_probability"])), 1 - probabilities[0], "appearance"
        )
        _close(float(cast(float, row["p60"])), probabilities[2] + probabilities[3], "p60")
        _close(
            float(cast(float, row["expected_minutes"])),
            math.fsum(p * m for p, m in zip(probabilities, minutes, strict=True)),
            "expected minutes",
        )
        clean = math.fsum(
            probabilities[b]
            * math.exp(-float(cast(float, row["opponent_goal_rate"])) * minutes[b] / 90)
            for b in (2, 3)
        )
        _close(float(cast(float, row["clean_sheet_probability"])), clean, "native clean-sheet law")
        _close(
            float(cast(float, row["raw_expected_points"])),
            _raw_points({str(k): v for k, v in row.items()}, season),
            "native scoring law",
        )
        actual[key] = {str(k): v for k, v in row.items()}
    if set(actual) != expected:
        raise ValueError(
            "Native tactical components do not cover the complete roster/calendar window."
        )
    if not frame.empty:
        component_rows(frame, model_version=FOOTBALL_MODEL_VERSION, players=set(identities))
    for _, side in frame.groupby(["fixture", "club"], sort=True):
        for head in ("goals", "assists"):
            mass = math.fsum(float(v) for v in side[head])
            _close(math.fsum(float(v) for v in side[head + "_share"]), 1, head + " full-club share")
            for value, share in zip(side[head], side[head + "_share"], strict=True):
                _close(float(value), mass * float(share), head + " native recipient")
    return actual


def _minute_binding(
    projection: TacticalProjection, *, code: int, club: int, native: Mapping[str, object]
) -> None:
    probabilities = [0.0] * 4
    weighted_minutes = [0.0] * 4
    for state, weight in zip(projection.states, normalized_state_weights(projection), strict=True):
        side = state.home if club == projection.home_club else state.away
        player = next(p for p in side.players if p.profile.player_code == code)
        minute = float(player.minutes)
        index = 0 if minute == 0 else 1 if minute < 60 else 2 if minute < 90 else 3
        probabilities[index] += float(weight)
        weighted_minutes[index] += float(weight) * minute
    for b in range(4):
        _close(
            probabilities[b],
            float(cast(float, native[f"minute_probability_{b}"])),
            f"player {code} minute bin {b}",
        )
        _close(
            weighted_minutes[b],
            float(cast(float, native[f"minute_probability_{b}"]))
            * float(cast(float, native[f"minute_value_{b}"])),
            f"player {code} minute exposure {b}",
        )
    _close(
        math.fsum(weighted_minutes),
        float(cast(float, native["expected_minutes"])),
        "state expected minutes",
    )
    _close(
        1 - probabilities[0],
        float(cast(float, native["appearance_probability"])),
        "state appearance",
    )
    _close(probabilities[2] + probabilities[3], float(cast(float, native["p60"])), "state p60")


def _control_binding(
    projection: TacticalProjection,
    control: TacticalAllocation,
    rows: Mapping[tuple[int, int], Mapping[str, object]],
    roster: pd.DataFrame,
) -> None:
    for side, opponent in ((control.home, control.away), (control.away, control.home)):
        known = set(int(v) for v in roster.loc[roster.club_code.eq(side.club), "player_id"])
        if {p.player_code for p in side.players} != known:
            raise ValueError("Tactical projection must include the full captured club roster.")
        for player in side.players:
            native = rows[(projection.fixture, player.player_code)]
            if (
                native["position"] != player.position
                or int(cast(int, native["club"])) != player.club
            ):
                raise ValueError("Tactical projection changed a native persistent player identity.")
            for name in ("goals", "assists", "clean_sheet_probability"):
                _close(
                    float(getattr(player, name)), float(cast(float, native[name])), "player " + name
                )
            _close(
                side.team_goal_rate, float(cast(float, native["team_goal_rate"])), "own intensity"
            )
            _close(
                opponent.team_goal_rate,
                float(cast(float, native["opponent_goal_rate"])),
                "opponent intensity",
            )
            _minute_binding(projection, code=player.player_code, club=player.club, native=native)


def _replace(
    frame: pd.DataFrame,
    allocations: tuple[TacticalAllocation, ...],
    projections: tuple[TacticalProjection, ...],
    season: str,
) -> pd.DataFrame:
    changed = frame.copy(deep=True)
    updates: dict[tuple[int, int], tuple[TacticalAllocatedPlayer, float, float]] = {}
    for allocation, projection in zip(allocations, projections, strict=True):
        for allocated_side, allocated_opponent in (
            (allocation.home, allocation.away),
            (allocation.away, allocation.home),
        ):
            for player in allocated_side.players:
                updates[(projection.fixture, player.player_code)] = (
                    player,
                    allocated_side.team_goal_rate,
                    allocated_opponent.team_goal_rate,
                )
    for index, row in changed.iterrows():
        player, own, opponent = updates[(int(row["fixture"]), int(row["player_code"]))]
        for name in ("goals", "assists", "clean_sheet_probability"):
            changed.at[index, name] = getattr(player, name)
        changed.at[index, "team_goal_rate"], changed.at[index, "opponent_goal_rate"] = own, opponent
    for _, side in changed.groupby(["fixture", "club"], sort=True):
        for head in ("goals", "assists"):
            total = math.fsum(float(v) for v in side[head])
            if total > 0:
                changed.loc[side.index, head + "_share"] = side[head] / total
    for index, record in zip(changed.index, changed.to_dict("records"), strict=True):
        raw = _raw_points({str(k): v for k, v in record.items()}, season)
        changed.at[index, "raw_expected_points"], changed.at[index, "expected_points"] = (
            raw,
            max(0.0, raw),
        )
    changed["model_version"] = MODEL_VERSION
    if not changed.empty:
        component_rows(
            changed, model_version=MODEL_VERSION, players={int(v) for v in changed.player_code}
        )
    return changed


def _weekly(
    components: pd.DataFrame,
    roster: pd.DataFrame,
    weeks: tuple[int, ...],
    eligibility: Mapping[int, float],
) -> pd.DataFrame:
    rows = []
    for week in weeks:
        for resource in roster.to_dict("records"):
            code = int(resource["player_id"])
            part = components.loc[components.GW.eq(week) & components.player_code.eq(code)]
            unconditional = math.fsum(float(v) for v in part.expected_points)
            chance = 1 - math.prod(1 - float(q) for q in part.appearance_probability)
            rows.append(
                {
                    **resource,
                    "gameweek": week,
                    "expected_points": eligibility[code] * unconditional,
                    "appearance_probability": eligibility[code] * chance,
                    "fixture_count": len(part),
                    "home_fixture_count": int(part.home.sum()),
                    "captured_availability_multiplier": eligibility[code],
                }
            )
    weekly = pd.DataFrame(rows)
    weekly.attrs = dict(roster.attrs)
    return weekly


def compose_tactical_candidate(
    native_components: pd.DataFrame,
    *,
    model: TacticalMatchupModel | None = None,
    projections: tuple[TacticalProjection, ...] = (),
    roster: pd.DataFrame,
    fixture_calendar: pd.DataFrame,
    season: str,
    gameweeks: tuple[int, ...],
    captured_at: str,
    native_cutoff: str,
    deadline_at: str,
    captured_availability: Mapping[int, float],
    resource_bundle: Mapping[str, object],
    enabled: bool = True,
    control: bool = False,
) -> TacticalExperiment:
    """Validate complete native control moments, then replace only declared tactical heads.

    Disabled calls do not access the model or tactical projections. Paired projections
    share the native predeadline decision, rather than treating future captures as facts
    already held. The complete native calendar proves all blank player-weeks as well.
    """
    if type(enabled) is not bool or type(control) is not bool or (not enabled and control):
        raise ValueError("Tactical enable/control settings must be compatible explicit booleans.")
    if (
        not isinstance(season, str)
        or len(season) != 7
        or not season.startswith("20")
        or not season[:4].isdigit()
        or not season[-2:].isdigit()
        or season[4] != "-"
        or int(season[-2:]) != (int(season[:4]) + 1) % 100
        or season == PROTECTED_SEASON
    ):
        raise ValueError("Tactical experiment needs an admitted complete scoring season.")
    if (
        type(gameweeks) is not tuple
        or not gameweeks
        or any(type(w) is not int or not 1 <= w <= 38 for w in gameweeks)
        or gameweeks != tuple(range(gameweeks[0], gameweeks[-1] + 1))
    ):
        raise ValueError("Tactical gameweeks must be consecutive explicit integers.")
    captured = normalize_utc_timestamp(captured_at, label="captured_at")
    cutoff = normalize_utc_timestamp(native_cutoff, label="native_cutoff")
    deadline = normalize_utc_timestamp(deadline_at, label="deadline_at")
    if not as_instant(captured) <= as_instant(cutoff) < as_instant(deadline):
        raise ValueError("Native tactical capture/decision must be before the deadline.")
    if not isinstance(resource_bundle, Mapping):
        raise ValueError("Captured tactical resources must be a named resource bundle.")
    resources = _json(resource_bundle)
    original_roster = _frame(roster, ROSTER_COLUMNS, "native roster")
    _roster(original_roster)
    calendar = _frame(fixture_calendar, CALENDAR_COLUMNS, "captured fixture calendar")
    scheduled = _calendar(
        calendar,
        cutoff=cutoff,
        deadline=deadline,
        weeks=gameweeks,
        clubs={int(v) for v in original_roster.club_code},
        season=season,
    )
    native = _frame(
        native_components,
        (*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, "model_version", "decision_at"),
        "native components",
    )
    if not isinstance(captured_availability, Mapping):
        raise ValueError("A complete captured native eligibility mapping is required.")
    eligibility = {
        _integer(code, "captured eligibility player"): _finite(value, "captured eligibility", 0, 1)
        for code, value in captured_availability.items()
    }
    if set(eligibility) != set(int(v) for v in original_roster.player_id):
        raise ValueError("Captured eligibility must cover the complete native roster exactly.")
    native_rows = _native_components(
        native, roster=original_roster, calendar=scheduled, season=season, cutoff=cutoff
    )
    original_component_hash = _frame_digest(native)
    revised = native.copy(deep=True)
    metadata: object = None
    projection_hashes: list[str] = []
    if enabled:
        if (
            not isinstance(model, TacticalMatchupModel)
            or type(projections) is not tuple
            or not all(isinstance(p, TacticalProjection) for p in projections)
        ):
            raise ValueError(
                "An enabled tactical candidate requires its fitted model and paired projections."
            )
        fitted_metadata = model.metadata
        metadata = asdict(fitted_metadata)
        if (
            normalize_utc_timestamp(fitted_metadata.cutoff, label="model cutoff") != cutoff
            or fitted_metadata.target_season != season
            or fitted_metadata.target_gameweek != gameweeks[0]
        ):
            raise ValueError("Tactical model must bind the exact native decision/target window.")
        scheduled_fixtures = set(int(v) for v in scheduled.fixture)
        if (
            len(projections) != len(scheduled_fixtures)
            or len({p.fixture for p in projections}) != len(projections)
            or {p.fixture for p in projections} != scheduled_fixtures
        ):
            raise ValueError(
                "Tactical projections must cover every complete native paired fixture exactly."
            )
        for projection in projections:
            validate_tactical_projection(projection, model_cutoff=cutoff)
            match = scheduled.loc[scheduled.fixture.eq(projection.fixture)]
            home = match.loc[match.home.eq(1)].iloc[0]
            away = match.loc[match.home.eq(0)].iloc[0]
            if (
                projection.season != season
                or projection.gameweek != int(home.GW)
                or projection.home_club != int(home.club)
                or projection.away_club != int(away.club)
                or normalize_utc_timestamp(projection.kickoff, label="projection kickoff")
                != normalize_utc_timestamp(
                    pd.Timestamp(home.kickoff).isoformat(), label="calendar kickoff"
                )
                or normalize_utc_timestamp(projection.decision_at, label="projection decision")
                != cutoff
            ):
                raise ValueError(
                    "Tactical projection differs from the common native calendar/decision."
                )
            neutral = model.predict(projection, control=True)
            if neutral.metadata is not fitted_metadata:
                raise ValueError("Tactical model changed fitted state during composition.")
            _control_binding(projection, neutral, native_rows, original_roster)
            projection_hashes.append(projection_digest(projection))
        if not control:
            learned = [model.predict(projection) for projection in projections]
            if any(result.metadata is not fitted_metadata for result in learned):
                raise ValueError("Tactical model changed fitted state during composition.")
            revised = _replace(native, tuple(learned), projections, season)
            if not any(
                (*fitted_metadata.beta, *fitted_metadata.goal_gamma, *fitted_metadata.assist_gamma)
            ):
                # Preserve exact native numerical values at the explicit zero ablation.
                revised = native.copy(deep=True)
                revised["model_version"] = MODEL_VERSION
    weekly = _weekly(revised, original_roster, gameweeks, eligibility)
    receipt = _json(
        {
            "contract_version": EXPERIMENT_VERSION,
            "enabled": enabled,
            "control": control,
            "season": season,
            "gameweeks": gameweeks,
            "captured_at": captured,
            "native_cutoff": cutoff,
            "deadline_at": deadline,
            "model_version": MODEL_VERSION if enabled else FOOTBALL_MODEL_VERSION,
            "feature_version": FEATURE_VERSION if enabled else None,
            "model_metadata": metadata,
            "projection_sha256": projection_hashes,
            "native_components_sha256": original_component_hash,
            "components_sha256": _frame_digest(revised),
            "weekly_sha256": _frame_digest(weekly),
            "roster_sha256": _frame_digest(original_roster),
            "calendar_sha256": _frame_digest(calendar),
            "resource_bundle_sha256": _sha(resources),
            "captured_availability": {str(k): v for k, v in sorted(eligibility.items())},
            "eligibility_scope": "one_state_per_player_week_after_fixture_scoring",
            "replacement_scope": "paired_goal_rates_and_player_goal_assist_clean_sheet_marginals",
            "retained_scope": "native_minutes_defcon_residual_and_resources",
            "control_binding": "full_roster_rates_goal_assist_clean_sheet_and_four_minute_moments",
            "lineup_proof_scope": "bounded_fixed_squad_neighborhood_only",
        }
    )
    for frame in (revised, weekly, original_roster):
        frame.attrs[RECEIPT_ATTR] = receipt
    return TacticalExperiment(revised, weekly, original_roster, receipt, resources)


def _bound_candidate(
    candidate: TacticalExperiment, resource_bundle: Mapping[str, object]
) -> dict[str, object]:
    if not isinstance(candidate, TacticalExperiment):
        raise ValueError("A private tactical candidate is required.")
    try:
        receipt = json.loads(candidate.receipt_json)
    except (ValueError, TypeError) as error:
        raise ValueError("Tactical candidate has an invalid canonical receipt.") from error
    if (
        not isinstance(receipt, dict)
        or set(receipt) != set(EXPERIMENT_RECEIPT_FIELDS)
        or receipt.get("contract_version") != EXPERIMENT_VERSION
        or _json(receipt) != candidate.receipt_json
    ):
        raise ValueError("Tactical candidate has an unsupported canonical receipt.")
    if not isinstance(resource_bundle, Mapping):
        raise ValueError("Captured tactical resources must be a named resource bundle.")
    if (
        _json(resource_bundle) != candidate.resource_bundle_json
        or _sha(candidate.resource_bundle_json) != receipt["resource_bundle_sha256"]
    ):
        raise ValueError("Tactical fixed-fifteen resources differ from the captured bundle.")
    for name, frame in (
        ("components", candidate.components),
        ("weekly", candidate.weekly),
        ("roster", candidate.roster),
    ):
        if (
            frame.attrs.get(RECEIPT_ATTR) != candidate.receipt_json
            or _frame_digest(frame) != receipt[name + "_sha256"]
        ):
            raise ValueError("Tactical candidate frame/attrs differ from their private receipt.")
    return cast(dict[str, object], receipt)


def plan_tactical_fixed_fifteen(
    candidate: TacticalExperiment,
    *,
    squad: pd.DataFrame,
    gameweek: int,
    starting_xi: Sequence[object],
    ordered_bench: Sequence[object],
    captain_id: object,
    vice_captain_id: object,
    resource_bundle: Mapping[str, object],
    chip: str | None = None,
    hit_points: float = 0.0,
    max_evaluations: int = 128,
    locked_first: bool = False,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
) -> TacticalFixedFifteenPlan:
    """Change only roles on an explicit legal15; transaction resources are byte-bound.

    The accepted current engine has exact utility under independent weekly appearances
    but explores a bounded XI neighborhood. It is not the unmerged exhaustive engine.
    """
    receipt = _bound_candidate(candidate, resource_bundle)
    week = _integer(gameweek, "fixed-fifteen gameweek")
    if week not in cast(list[int], receipt["gameweeks"]):
        raise ValueError("Fixed-fifteen week is outside the bound tactical window.")
    if (
        isinstance(max_evaluations, bool)
        or not isinstance(max_evaluations, Integral)
        or not 1 <= max_evaluations <= 128
    ):
        raise ValueError("The tactical role neighborhood needs a cap in [1,128].")
    resource_columns = tuple(
        name
        for name in candidate.roster.columns
        if name not in ("expected_points", "appearance_probability")
    )
    selected = _frame(
        squad, resource_columns, "fixed-fifteen squad", allowed_receipt=candidate.receipt_json
    )
    selected_attrs = {k: v for k, v in selected.attrs.items() if k != RECEIPT_ATTR}
    captured_attrs = {k: v for k, v in candidate.roster.attrs.items() if k != RECEIPT_ATTR}
    if _json(selected_attrs) != _json(captured_attrs):
        raise ValueError("Fixed-fifteen attrs differ from captured native resources.")
    _roster(selected)
    if (
        len(selected) != 15
        or selected.position.value_counts().to_dict() != {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
        or (selected.club_code.value_counts() > 3).any()
    ):
        raise ValueError(
            "Fixed fifteen requires legal2/5/5/3 and at most3 players per persistent club."
        )
    roster = candidate.roster.set_index("player_id")
    for row in selected.to_dict("records"):
        if row["player_id"] not in roster.index or _json(
            {name: row[name] for name in resource_columns}
        ) != _json(
            {
                name: roster.loc[row["player_id"], name]
                if name != "player_id"
                else row["player_id"]
                for name in resource_columns
            }
        ):
            raise ValueError("Fixed-fifteen identity/prices differ from captured native resources.")
    original_resources = selected.drop(
        columns=[c for c in ("expected_points", "appearance_probability") if c in selected]
    )
    weekly = candidate.weekly.loc[candidate.weekly.gameweek.eq(week)].set_index("player_id")
    for name in ("expected_points", "appearance_probability"):
        selected[name] = selected.player_id.map(weekly[name])
    search = improve_expected_lineup(
        selected,
        starting_xi,
        ordered_bench,
        captain_id,
        vice_captain_id,
        chip=chip,
        hit_points=hit_points,
        not_starting=not_starting,
        not_captain=not_captain,
        max_evaluations=int(max_evaluations),
        locked_first=locked_first,
    )
    plan_receipt = _json(
        {
            "contract_version": FIXED_FIFTEEN_VERSION,
            "candidate_receipt_sha256": _sha(candidate.receipt_json),
            "gameweek": week,
            "resource_bundle_sha256": _sha(candidate.resource_bundle_json),
            "fixed_squad_resources_sha256": _frame_digest(original_resources),
            "scored_squad_sha256": _frame_digest(selected),
            "incumbent_fingerprint": search.incumbent.fingerprint,
            "selected_fingerprint": search.best.fingerprint,
            "proof_scope": search.proof_scope,
            "max_evaluations": search.max_evaluations,
            "evaluations": search.evaluations,
            "locked_first": search.locked_first,
        }
    )
    selected.attrs[RECEIPT_ATTR] = plan_receipt
    return TacticalFixedFifteenPlan(selected, search, candidate.resource_bundle_json, plan_receipt)
