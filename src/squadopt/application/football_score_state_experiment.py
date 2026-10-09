"""Private score-process composition on an unchanged captured minute law.

Native physical goal and clean-sheet moments are checked before learned use.
Only credited goals, assists and clean sheets change. Original weekly appearance,
physical recipient fractions, inventory and nonattacking components are retained.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from numbers import Integral, Real
from typing import cast

import numpy as np
import pandas as pd

from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.features.football_score_state_inputs import (
    ScoreFixture,
    score_input_digest,
    validate_score_fixture,
)
from squadopt.live.minute_evidence import _validate_components
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSIONS
from squadopt.prediction.football_components import component_rows
from squadopt.prediction.football_minutes_role import ROLE_COMPONENT_COLUMNS
from squadopt.prediction.football_score_state import ScoreStateModel, ScoreStatePrediction
from squadopt.scenarios.expected_lineup import ExpectedLineupSearchResult, improve_expected_lineup

EXPERIMENT_VERSION = "football_score_state_experiment_v1"
RECEIPT_ATTR = "football_score_state_experiment_receipt"
_ROSTER_FIELDS = (
    "player_id",
    "name",
    "club_code",
    "team_id",
    "position",
    "buy_price_tenths",
    "sell_price_tenths",
)
_SCHEDULE_FIELDS = ("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at")
_MOMENT_ATOL = 1e-10


@dataclass(frozen=True)
class ScoreStateExperiment:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    receipt_json: str
    resource_bundle_json: str


@dataclass(frozen=True)
class ScoreStateFixedFifteenPlan:
    squad: pd.DataFrame
    search: ExpectedLineupSearchResult
    receipt_json: str
    resource_bundle_json: str


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{field} requires a finite number.")
    return float(value)


def _id(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{field} requires an integer at least {minimum}.")
    return int(value)


def _clock(value: object, field: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} requires an explicit UTC timestamp.")
    instant = as_instant(normalize_utc_timestamp(value, label=field))
    if not value.endswith(("Z", "+00:00")):
        raise ValueError(f"{field} requires UTC.")
    return pd.Timestamp(instant)


def _encode_extra(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return normalize_utc_timestamp(value.isoformat(), label="captured dataframe timestamp")
    raise ValueError("Captured receipts require finite explicit JSON values.")


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_encode_extra
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Captured receipts require finite canonical JSON.") from error


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _copy(frame: pd.DataFrame) -> pd.DataFrame:
    duplicate = frame.copy(deep=True)
    duplicate.attrs = deepcopy(frame.attrs)
    return duplicate


def native_basis_digest(frame: pd.DataFrame) -> str:
    """Seal all cells, their dtypes, ordering, index and nonreceipt metadata.

    Typed missing values are legal only in declared nullable native role fields.
    They are tagged without converting any values in the returned dataframe.
    """
    nullable = {name for name in ROLE_COMPONENT_COLUMNS if name.startswith(("start_", "cameo_"))}
    rows = []
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for field, value in zip(frame.columns, row, strict=True):
            if field in nullable and value is pd.NA:
                cells.append({"native_role_missing_kind": "pandas.NA"})
            elif (
                field in nullable
                and isinstance(value, (float, np.floating))
                and math.isnan(float(value))
            ):
                cells.append({"native_role_missing_kind": "float.NaN"})
            else:
                cells.append(value)
        rows.append(cells)
    return _sha(
        _json(
            {
                "columns": list(frame.columns),
                "dtypes": [str(t) for t in frame.dtypes],
                "rows": rows,
                "index": frame.index.tolist(),
                "attrs": {k: v for k, v in frame.attrs.items() if k != RECEIPT_ATTR},
            }
        )
    )


def _validate_capture(
    native: pd.DataFrame,
    served: pd.DataFrame,
    roster: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
    eligibility: Mapping[int, float],
) -> dict[tuple[int, int], tuple[int, int, int, pd.Timestamp]]:
    for frame in (native, served, roster, calendar):
        if not frame.index.is_unique or frame.columns.duplicated().any():
            raise ValueError("Captured indexes and columns must be unique.")
    if (
        not set(_ROSTER_FIELDS) <= set(roster)
        or roster.empty
        or roster.player_id.duplicated().any()
    ):
        raise ValueError("A complete unique native roster is required.")
    player_ids = set()
    clubs = {}
    for player in roster.to_dict("records"):
        pid = _id(player["player_id"], "player")
        club = _id(player["club_code"], "persistent club")
        _id(player["team_id"], "captured team alias")
        for field in ("buy_price_tenths", "sell_price_tenths"):
            _id(player[field], field, minimum=0)
        if (
            player["position"] not in ("GK", "DEF", "MID", "FWD")
            or not isinstance(player["name"], str)
            or not player["name"].strip()
        ):
            raise ValueError("Native roster identity and positions must be explicit.")
        player_ids.add(pid)
        clubs[pid] = (club, player["position"])
    if (
        roster.groupby("club_code").team_id.nunique().gt(1).any()
        or roster.groupby("team_id").club_code.nunique().gt(1).any()
    ):
        raise ValueError("Persistent club and team aliases must map one to one.")
    if set(eligibility) != player_ids:
        raise ValueError("The captured external eligibility map must cover every roster player.")
    for pid, coefficient in eligibility.items():
        _id(pid, "eligibility player")
        if not 0 <= _number(coefficient, "external eligibility") <= 1:
            raise ValueError("External eligibility is outside [0, 1].")
    if (
        native.attrs.get("season") != season
        or _clock(native.attrs.get("native_cutoff"), "native cutoff") != decision
        or native.attrs.get("availability_application") != "not_applied"
    ):
        raise ValueError("The native fixture basis must precede external eligibility.")
    for frame in (native, calendar):
        if (
            frame.attrs.get("calendar_complete") is not True
            or tuple(frame.attrs.get("covered_gameweeks", ())) != gameweeks
        ):
            raise ValueError("Complete original calendar coverage must bind every requested week.")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", str(native.attrs.get("captured_availability_sha256", "")))
        or not isinstance(native.attrs.get("captured_availability_evidence_ref"), str)
        or not str(native.attrs["captured_availability_evidence_ref"]).strip()
    ):
        raise ValueError("External eligibility needs its original snapshot and source evidence.")
    if not set(_SCHEDULE_FIELDS) <= set(calendar):
        raise ValueError("A complete paired fixture calendar is required.")
    lower = pd.Timestamp(f"{int(season[:4])}-07-01T00:00:00Z")
    upper = pd.Timestamp(f"{int(season[:4]) + 1}-07-01T00:00:00Z")
    schedule = {}
    roster_clubs = set(roster.club_code)
    for row in calendar.to_dict("records"):
        fixture, club, opponent = (_id(row[f], f) for f in ("fixture", "club", "opponent"))
        home, week = _id(row["home"], "home", minimum=0), _id(row["GW"], "week")
        kickoff = _clock(row["kickoff"], "kickoff")
        if (
            club == opponent
            or club not in roster_clubs
            or opponent not in roster_clubs
            or home not in (0, 1)
            or week not in gameweeks
            or not lower <= kickoff < upper
            or kickoff <= deadline
            or _clock(row["decision_at"], "calendar cutoff") != decision
            or (fixture, club) in schedule
        ):
            raise ValueError("The captured fixture identity, season or clock is inconsistent.")
        schedule[fixture, club] = (opponent, home, week, kickoff)
    for (fixture, club), (opponent, home, week, kickoff) in schedule.items():
        if schedule.get((fixture, opponent)) != (club, 1 - home, week, kickoff):
            raise ValueError("Each fixture needs two coherent opposing sides.")
    if not {"player_code", "fixture", "model_version", "GW"} <= set(native):
        raise ValueError("Native component identities are missing.")
    if not native.empty:
        versions = set(native.model_version)
        if len(versions) != 1 or next(iter(versions)) not in (
            FOOTBALL_MODEL_VERSION,
            *JOINT_ROLE_MODEL_VERSIONS,
        ):
            raise ValueError("The original native model version is unsupported.")
        version = str(next(iter(versions)))
        component_rows(native, model_version=version, players=player_ids)
        _validate_components(_copy(native), season, joint_role=version in JOINT_ROLE_MODEL_VERSIONS)
        if (native.goals + native.assists > native.team_goal_rate + _MOMENT_ATOL).any():
            raise ValueError("Native individual credits exceed physical goal mass.")
    identities = {
        (_id(r.fixture, "fixture"), _id(r.player_code, "player")) for r in native.itertuples()
    }
    expected = {
        (fixture, pid)
        for fixture, club in schedule
        for pid, (team, _) in clubs.items()
        if club == team
    }
    if identities != expected:
        raise ValueError("The native basis must contain every full-club player-fixture row.")
    for row in native.to_dict("records"):
        pid = _id(row["player_code"], "native player")
        club, position = clubs[pid]
        opponent, home, week, kickoff = schedule[_id(row["fixture"], "native fixture"), club]
        if (
            row["club"] != club
            or row["opponent"] != opponent
            or row["home"] != home
            or row["GW"] != week
            or row["position"] != position
            or _clock(row["kickoff"], "native kickoff") != kickoff
            or (
                "decision_at" in row and _clock(row["decision_at"], "native row cutoff") != decision
            )
            or ("season" in row and row["season"] != season)
            or row.get("availability_multiplier", 1.0) != 1.0
        ):
            raise ValueError("Native component rows contradict their captured identity.")
    if (
        not {"player_id", "gameweek", "expected_points", "appearance_probability"} <= set(served)
        or served.duplicated(["player_id", "gameweek"]).any()
        or set(zip(served.player_id, served.gameweek, strict=True))
        != {(pid, week) for pid in player_ids for week in gameweeks}
    ):
        raise ValueError("The original served player-week reference must be complete.")
    for row in served.to_dict("records"):
        pid, week = _id(row["player_id"], "served player"), _id(row["gameweek"], "served week")
        q = _number(row["appearance_probability"], "served weekly appearance")
        fixture_rows = native.loc[native.player_code.eq(pid) & native.GW.eq(week)]
        point_rows = fixture_rows["expected_points"]
        marginals = tuple(float(p) for p in fixture_rows.appearance_probability)
        lower_q = eligibility[pid] * max(marginals, default=0.0)
        upper_q = eligibility[pid] * min(1.0, math.fsum(marginals))
        mu = _number(row["expected_points"], "served weekly points")
        if (
            not 0 <= q <= eligibility[pid]
            or q < lower_q - 1e-12
            or q > upper_q + 1e-12
            or not math.isclose(
                mu, eligibility[pid] * math.fsum(point_rows), rel_tol=1e-12, abs_tol=1e-12
            )
        ):
            raise ValueError(
                "The original served reference differs from its captured eligibility or points."
            )
    return schedule


def _support(
    row: Mapping[str, object], version: str
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if (
        version in JOINT_ROLE_MODEL_VERSIONS
        and row["minute_role_status"] == "fitted_known_start_labels"
    ):
        fields = [(role, b) for role in ("start", "cameo") for b in (1, 2, 3)]
        return (
            (
                float(cast(Real, row["zero_probability"])),
                *(
                    _number(row[f"{role}_minute_probability_{b}"], "native role probability")
                    for role, b in fields
                ),
            ),
            (
                0.0,
                *(
                    _number(row[f"{role}_minute_value_{b}"], "native role minutes")
                    for role, b in fields
                ),
            ),
        )
    return (
        tuple(
            _number(row[f"minute_probability_{b}"], "native minute probability") for b in range(4)
        ),
        tuple(_number(row[f"minute_value_{b}"], "native minute support") for b in range(4)),
    )


def _bind_fixtures(
    fixtures: Sequence[ScoreFixture],
    native: pd.DataFrame,
    schedule: Mapping[tuple[int, int], tuple[int, int, int, pd.Timestamp]],
    *,
    season: str,
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
) -> None:
    expected = {fixture for fixture, _ in schedule}
    if len(fixtures) != len(expected) or {f.fixture_id for f in fixtures} != expected:
        raise ValueError(
            "Enabled score dynamics require the complete paired source fixture inventory."
        )
    basis = native_basis_digest(native)
    for fixture in fixtures:
        validate_score_fixture(fixture)
        if (
            fixture.season != season
            or _clock(fixture.decision_at, "process cutoff") != decision
            or _clock(fixture.deadline_at, "process deadline") != deadline
            or fixture.native_basis_sha256 != basis
        ):
            raise ValueError("Score inputs belong to a different captured native basis.")
        rows = native.loc[native.fixture.eq(fixture.fixture_id)]
        version = str(rows.model_version.iloc[0])
        if fixture.native_model_version != version:
            raise ValueError("Score inputs belong to a different original model version.")
        homes = rows.loc[rows.home.eq(1)]
        away = rows.loc[rows.home.eq(0)]
        if (
            fixture.home_club_code != homes.club.iloc[0]
            or fixture.away_club_code != away.club.iloc[0]
            or fixture.gameweek != homes.GW.iloc[0]
            or _clock(fixture.kickoff, "process kickoff")
            != _clock(homes.kickoff.iloc[0], "original kickoff")
            or fixture.native_home_goals != homes.team_goal_rate.iloc[0]
            or fixture.native_away_goals != away.team_goal_rate.iloc[0]
        ):
            raise ValueError("Score source physical totals or paired fixture identity differ.")
        lookup = {_id(row["player_code"], "native player"): row for row in rows.to_dict("records")}
        if {p.player_code for p in fixture.players} != set(lookup) or len(fixture.players) != len(
            lookup
        ):
            raise ValueError("The process must include the complete original club roster.")
        for player in fixture.players:
            row = lookup[player.player_code]
            if (
                player.club_code != row["club"]
                or player.position != row["position"]
                or (player.probabilities, player.credited_minutes)
                != _support({str(k): v for k, v in row.items()}, version)
            ):
                raise ValueError("Captured player intervals have a different native minute law.")


def _check_prediction(
    prediction: ScoreStatePrediction, fixture: ScoreFixture, model: ScoreStateModel
) -> None:
    if (
        score_input_digest(prediction.fixture) != score_input_digest(fixture)
        or prediction.input_sha256 != score_input_digest(fixture)
        or prediction.model_sha256 != model.model_sha256
    ):
        raise ValueError("The predicted process does not match its sealed model and source.")
    tolerance = _number(model.metadata.numerical_tolerance, "declared process tolerance")
    if not 1e-12 <= tolerance <= 1e-6:
        raise ValueError("The private process needs an admitted numerical tolerance.")
    overflow = _number(prediction.overflow_mass, "score overflow")
    mass_error = _number(prediction.mass_error_bound, "score mass error bound")
    goal_error = _number(prediction.goal_moment_error_bound, "goal moment error bound")
    if (
        not 0 <= overflow <= tolerance
        or not 0 <= mass_error <= tolerance
        or not 0 <= goal_error <= tolerance
    ):
        raise ValueError("The score process exceeded its declared numerical error budget.")
    probabilities = tuple(
        _number(p, "score-state probability") for p in prediction.difference_probabilities
    )
    if (
        len(probabilities) != len(prediction.difference_states)
        or any(p < 0 or p > 1 for p in probabilities)
        or not math.isclose(
            math.fsum(probabilities) + overflow, 1.0, rel_tol=0, abs_tol=mass_error + _MOMENT_ATOL
        )
    ):
        raise ValueError("The retained score process and explicit overflow do not close.")
    for value in (prediction.home_physical_goals, prediction.away_physical_goals):
        if _number(value, "predicted physical goal moment") < 0:
            raise ValueError("Physical goal moments must be nonnegative.")
    players = {p.player_code: p for p in fixture.players}
    if len(prediction.player_survival) != len(players) or {
        p.player_code for p in prediction.player_survival
    } != set(players):
        raise ValueError("Player clean-sheet moment coverage is incomplete.")
    for record in prediction.player_survival:
        player = players[record.player_code]
        if (
            record.club_code != player.club_code
            or len(record.survival) != len(player.probabilities)
            or any(not 0 <= _number(p, "player interval survival") <= 1 for p in record.survival)
            or record.survival[0] != 0
        ):
            raise ValueError("Player survival intervals differ from the captured exposure law.")


def _clean_sheets(prediction: ScoreStatePrediction) -> dict[int, float]:
    players = {p.player_code: p for p in prediction.fixture.players}
    return {
        record.player_code: math.fsum(
            probability * survival
            for probability, minutes, survival in zip(
                players[record.player_code].probabilities,
                players[record.player_code].credited_minutes,
                record.survival,
                strict=True,
            )
            if minutes >= 60
        )
        for record in prediction.player_survival
    }


def _check_neutral(prediction: ScoreStatePrediction, native: pd.DataFrame) -> None:
    fixture = prediction.fixture
    if not prediction.zero_coefficients:
        raise ValueError("The native-moment proof must use zero process coefficients.")
    for actual, original in (
        (prediction.home_physical_goals, fixture.native_home_goals),
        (prediction.away_physical_goals, fixture.native_away_goals),
    ):
        if not math.isclose(
            actual, original, rel_tol=0, abs_tol=prediction.goal_moment_error_bound + _MOMENT_ATOL
        ):
            raise ValueError("The declared physical clock does not reproduce native goal moments.")
    moments = _clean_sheets(prediction)
    for row in native.loc[native.fixture.eq(fixture.fixture_id)].to_dict("records"):
        if not math.isclose(
            moments[int(row["player_code"])],
            float(row["clean_sheet_probability"]),
            rel_tol=0,
            abs_tol=prediction.mass_error_bound + _MOMENT_ATOL,
        ):
            raise ValueError(
                "The declared physical intervals do not reproduce native clean-sheet moments."
            )


def _replace_scoring(
    native: pd.DataFrame, predictions: Sequence[ScoreStatePrediction], season: str
) -> pd.DataFrame:
    output = _copy(native)
    goal_value = {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    cs_value = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
    for prediction in predictions:
        fixture = prediction.fixture
        clean = _clean_sheets(prediction)
        for club, physical in (
            (fixture.home_club_code, prediction.home_physical_goals),
            (fixture.away_club_code, prediction.away_physical_goals),
        ):
            indexes = native.index[native.fixture.eq(fixture.fixture_id) & native.club.eq(club)]
            old = native.loc[indexes]
            baseline = float(old.team_goal_rate.iloc[0])
            if baseline == 0 and physical != 0:
                raise ValueError(
                    "A zero native physical goal channel cannot gain unsupported mass."
                )
            original_goals, original_assists = math.fsum(old.goals), math.fsum(old.assists)
            fractions = (
                (original_goals / baseline, original_assists / baseline) if baseline else (0.0, 0.0)
            )
            if any(not 0 <= fraction <= 1 for fraction in fractions):
                raise ValueError("Native physical-to-credit fractions must be in [0, 1].")
            for index, row in old.iterrows():
                goals = physical * fractions[0] * float(row.goals_share)
                assists = physical * fractions[1] * float(row.assists_share)
                cs = clean[_id(row.player_code, "predicted player")]
                if (
                    goals + assists > physical + _MOMENT_ATOL
                    or not 0 <= cs <= float(row.p60) + _MOMENT_ATOL
                ):
                    raise ValueError(
                        "Learned individual credit or clean-sheet bounds are inconsistent."
                    )
                output.at[index, "goals"] = goals
                output.at[index, "assists"] = assists
                output.at[index, "clean_sheet_probability"] = cs
                output.at[index, "team_goal_rate"] = physical
                output.at[index, "opponent_goal_rate"] = (
                    prediction.away_physical_goals
                    if club == fixture.home_club_code
                    else prediction.home_physical_goals
                )
                raw = math.fsum(
                    (
                        float(row.raw_expected_points),
                        goal_value[str(row.position)] * (goals - float(row.goals)),
                        3.0 * (assists - float(row.assists)),
                        cs_value[str(row.position)] * (cs - float(row.clean_sheet_probability)),
                    )
                )
                if not math.isfinite(raw):
                    raise ValueError("Score replacement exceeded finite point support.")
                output.at[index, "raw_expected_points"] = raw
                output.at[index, "expected_points"] = max(0.0, raw)
            for column, fraction in zip(("goals", "assists"), fractions, strict=True):
                if not math.isclose(
                    math.fsum(output.loc[indexes, column]),
                    physical * fraction,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    raise ValueError("The learned credited club mass does not close.")
    output["score_state_native_model_version"] = output.model_version
    output["model_version"] = EXPERIMENT_VERSION
    output.attrs["score_state_scoring_law"] = (
        "paired_physical_goal_process_explicit_interval_survival"
    )
    return output


def _owned(resources: Mapping[str, object], roster: pd.DataFrame) -> tuple[int, ...]:
    captured = resources.get("owned")
    if not isinstance(captured, (list, tuple)) or len(captured) != 15:
        raise ValueError("An explicit original fifteen-player resource receipt is required.")
    ids = tuple(_id(pid, "owned player") for pid in captured)
    if len(set(ids)) != 15 or not set(ids) <= set(roster.player_id):
        raise ValueError(
            "The original captured inventory is duplicated or outside the native roster."
        )
    if "chips" in resources and (
        not isinstance(resources["chips"], dict)
        or any(type(v) is not bool for v in cast(dict[str, object], resources["chips"]).values())
    ):
        raise ValueError("Captured chip availability must use explicit booleans.")
    return tuple(sorted(ids))


def compose_score_state_experiment(
    native_components: pd.DataFrame,
    native_weekly: pd.DataFrame,
    roster: pd.DataFrame,
    calendar: pd.DataFrame,
    resource_bundle: Mapping[str, object],
    fixtures: Sequence[ScoreFixture],
    model: ScoreStateModel | None,
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision_at: str,
    deadline_at: str,
    captured_availability: Mapping[int, float],
    enabled: bool = False,
    control: bool = False,
    zero_coefficients: bool = False,
) -> ScoreStateExperiment:
    """Run a private explicit process arm or preserve the exact served control."""
    if (
        any(type(flag) is not bool for flag in (enabled, control, zero_coefficients))
        or not isinstance(season, str)
        or not re.fullmatch(r"\d{4}-\d{2}", season)
        or int(season[5:]) != (int(season[:4]) + 1) % 100
        or type(gameweeks) is not tuple
        or not gameweeks
        or tuple(sorted(set(gameweeks))) != gameweeks
        or any(_id(week, "covered week") > 38 for week in gameweeks)
    ):
        raise ValueError(
            "The experiment requires explicit switches, season and ordered unique weeks."
        )
    decision, deadline = _clock(decision_at, "decision"), _clock(deadline_at, "deadline")
    if decision >= deadline:
        raise ValueError("The decision must precede its deadline.")
    schedule = _validate_capture(
        native_components,
        native_weekly,
        roster,
        calendar,
        season=season,
        gameweeks=gameweeks,
        decision=decision,
        deadline=deadline,
        eligibility=captured_availability,
    )
    owned = _owned(resource_bundle, roster)
    components, weekly, inventory = _copy(native_components), _copy(native_weekly), _copy(roster)
    predictions = []
    if enabled and not control:
        if model is None:
            raise ValueError("The enabled score process needs a fitted model.")
        _bind_fixtures(
            fixtures,
            native_components,
            schedule,
            season=season,
            decision=decision,
            deadline=deadline,
        )
        for fixture in fixtures:
            neutral = model.predict(fixture, zero_coefficients=True)
            _check_prediction(neutral, fixture, model)
            _check_neutral(neutral, native_components)
            prediction = neutral if zero_coefficients else model.predict(fixture)
            _check_prediction(prediction, fixture, model)
            predictions.append(prediction)
        if not components.empty:
            components = _replace_scoring(native_components, predictions, season)
        for index, row in weekly.iterrows():
            mu = components.loc[
                components.player_code.eq(row.player_id) & components.GW.eq(row.gameweek),
                "expected_points",
            ]
            weekly.at[index, "expected_points"] = captured_availability[
                _id(row.player_id, "weekly player")
            ] * math.fsum(mu)
        weekly.attrs["score_state_process_model_sha256"] = model.model_sha256
    resource_json = _json(resource_bundle)
    receipt = _json(
        {
            "version": EXPERIMENT_VERSION,
            "season": season,
            "gameweeks": gameweeks,
            "decision_at": decision.isoformat(),
            "deadline_at": deadline.isoformat(),
            "enabled": enabled,
            "control": control,
            "zero_coefficients": zero_coefficients,
            "native_basis_sha256": native_basis_digest(native_components),
            "native_weekly_sha256": native_basis_digest(native_weekly),
            "components_sha256": native_basis_digest(components),
            "weekly_sha256": native_basis_digest(weekly),
            "roster_sha256": native_basis_digest(inventory),
            "calendar_sha256": native_basis_digest(calendar),
            "owned_player_ids": owned,
            "resource_bundle_sha256": _sha(resource_json),
            "captured_availability": {str(k): v for k, v in sorted(captured_availability.items())},
            "captured_availability_sha256": native_components.attrs["captured_availability_sha256"],
            "captured_availability_evidence_ref": native_components.attrs[
                "captured_availability_evidence_ref"
            ],
            "appearance_policy": "retain_exact_captured_weekly_appearance",
            "availability_scope": "external_legacy_once_on_weekly_points",
            "process_model_metadata_json": model.metadata_json
            if predictions and model is not None
            else None,
            "process_inputs": [p.input_sha256 for p in predictions],
            "process_error_bounds": [
                {
                    "fixture": p.fixture.fixture_id,
                    "overflow_mass": p.overflow_mass,
                    "mass_error_bound": p.mass_error_bound,
                    "goal_moment_error_bound": p.goal_moment_error_bound,
                }
                for p in predictions
            ],
            "unchanged_terms": "native_minutes_roles_appearance_defcon_and_empirical_residual",
            "scoring_assumptions": (
                "fixed_native_credit_fractions_and_recipient_shares_independent_of_score_path"
            ),
            "exposure_assumptions": (
                "frozen_predecision_player_intervals_independent_of_future_score_path"
            ),
            "role_search_scope": "bounded_fixed_squad_neighborhood_only",
        }
    )
    for frame in (components, weekly, inventory):
        frame.attrs[RECEIPT_ATTR] = receipt
    return ScoreStateExperiment(components, weekly, inventory, receipt, resource_json)


def plan_score_state_fixed_fifteen(
    experiment: ScoreStateExperiment,
    player_ids: Sequence[object],
    starting_xi: Sequence[object],
    ordered_bench: Sequence[object],
    captain_id: object,
    vice_captain_id: object,
    *,
    gameweek: int,
    chip: str | None = None,
    hit_points: float = 0,
    max_evaluations: int = 128,
    locked_first: bool = False,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
) -> ScoreStateFixedFifteenPlan:
    """Choose legal roles within the original captured inventory and resources."""
    gameweek = _id(gameweek, "fixed-fifteen week")
    try:
        receipt, resources = (
            json.loads(experiment.receipt_json),
            json.loads(experiment.resource_bundle_json),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("The private experiment receipt is invalid.") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != EXPERIMENT_VERSION
        or not isinstance(resources, dict)
        or _json(receipt) != experiment.receipt_json
        or _json(resources) != experiment.resource_bundle_json
        or _sha(experiment.resource_bundle_json) != receipt.get("resource_bundle_sha256")
    ):
        raise ValueError("The private experiment and resource receipts changed.")
    for name, frame in (
        ("components", experiment.components),
        ("weekly", experiment.weekly),
        ("roster", experiment.roster),
    ):
        if frame.attrs.get(RECEIPT_ATTR) != experiment.receipt_json or native_basis_digest(
            frame
        ) != receipt.get(name + "_sha256"):
            raise ValueError("Captured private dataframe values or metadata changed.")
    ids = tuple(_id(pid, "fixed-fifteen player") for pid in player_ids)
    if (
        len(ids) != 15
        or len(set(ids)) != 15
        or sorted(ids) != receipt.get("owned_player_ids")
        or gameweek not in receipt["gameweeks"]
    ):
        raise ValueError(
            "Role optimization requires the original captured fifteen and covered week."
        )
    if _id(max_evaluations, "role evaluation budget") > 128:
        raise ValueError("The private role budget permits at most128 evaluations.")
    squad = _copy(experiment.roster.loc[experiment.roster.player_id.isin(ids)])
    if squad.groupby("club_code").size().gt(3).any():
        raise ValueError(
            "The fixed inventory cannot contain more than three players per persistent club."
        )
    start_restrictions, captain_restrictions = tuple(not_starting), tuple(not_captain)
    if chip is not None and (
        not isinstance(resources.get("chips"), dict) or resources["chips"].get(chip) is not True
    ):
        raise ValueError("The requested chip is unavailable in the captured resources.")
    for key, value in (
        ("chip", chip),
        ("hit_points", hit_points),
        ("locked_first", locked_first),
        ("not_starting", list(start_restrictions)),
        ("not_captain", list(captain_restrictions)),
    ):
        if key in resources and _json(resources[key]) != _json(value):
            raise ValueError("Role optimization cannot change captured policies or resources.")
    forecast = experiment.weekly.loc[experiment.weekly.gameweek.eq(gameweek)].set_index("player_id")
    for key in ("expected_points", "appearance_probability"):
        squad[key] = squad.player_id.map(forecast[key])
    search = improve_expected_lineup(
        squad,
        starting_xi,
        ordered_bench,
        captain_id,
        vice_captain_id,
        chip=chip,
        hit_points=hit_points,
        max_evaluations=max_evaluations,
        locked_first=locked_first,
        not_starting=start_restrictions,
        not_captain=captain_restrictions,
    )
    plan_receipt = _json(
        {
            "version": "football_score_state_fixed_fifteen_v1",
            "gameweek": gameweek,
            "experiment_sha256": _sha(experiment.receipt_json),
            "resource_bundle_sha256": _sha(experiment.resource_bundle_json),
            "squad_sha256": native_basis_digest(squad),
            "best_fingerprint": search.best.fingerprint,
            "proof_scope": search.proof_scope,
        }
    )
    return ScoreStateFixedFifteenPlan(squad, search, plan_receipt, experiment.resource_bundle_json)
