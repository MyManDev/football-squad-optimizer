"""Private all-competition minute-law composition on a captured native basis.

The supplied whole-week law is retained, including fixture dependence. External
legacy eligibility is applied once after fixture scoring. These helpers perform no
I/O, training, publication or transfer optimization.
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
from squadopt.features.football_load_inputs import LoadWeek, load_input_digest, validate_load_week
from squadopt.live.minute_evidence import _score_components, _validate_components
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSIONS
from squadopt.prediction.football_components import component_rows
from squadopt.prediction.football_load_minutes import LoadMinutesModel, WeekLoadPrediction
from squadopt.prediction.football_minutes_role import ROLE_COMPONENT_COLUMNS
from squadopt.scenarios.expected_lineup import ExpectedLineupSearchResult, improve_expected_lineup

EXPERIMENT_VERSION = "football_all_competition_load_experiment_v1"
RECEIPT_ATTR = "football_load_experiment_receipt"
_ROSTER = (
    "player_id",
    "name",
    "team_id",
    "club_code",
    "position",
    "buy_price_tenths",
    "sell_price_tenths",
)
_CALENDAR = ("fixture", "club", "opponent", "home", "GW", "kickoff", "decision_at")


@dataclass(frozen=True)
class LoadExperiment:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    receipt_json: str
    resource_bundle_json: str


@dataclass(frozen=True)
class LoadFixedFifteenPlan:
    squad: pd.DataFrame
    search: ExpectedLineupSearchResult
    resource_bundle_json: str
    receipt_json: str


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return normalize_utc_timestamp(value.isoformat(), label="private table timestamp")
    raise ValueError("Private receipts require explicit finite JSON values.")


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Private receipts require finite canonical JSON.") from error


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _integer(value: object, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum:
        raise ValueError(f"Invalid {label}.")
    return int(value)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"Nonfinite or untyped {label}.")
    return float(value)


def _instant(value: object, label: str) -> pd.Timestamp:
    return pd.Timestamp(as_instant(normalize_utc_timestamp(value, label=label)))


def _clone(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy(deep=True)
    result.attrs = deepcopy(frame.attrs)
    return result


def native_basis_digest(frame: pd.DataFrame) -> str:
    """Hash original values and types, including declared nullable native roles.

    Missing roles accepted by the native contract retain an explicit type tag.
    Nonfinite numeric scoring components and resource metadata remain invalid.
    """
    records = frame.to_dict("records")
    for column in ROLE_COMPONENT_COLUMNS:
        if column not in frame or not column.startswith(("start_", "cameo_")):
            continue
        for index, value in enumerate(frame[column].tolist()):
            if value is pd.NA:
                records[index][column] = {"native_nullable_role_value": "pandas.NA"}
            elif isinstance(value, (float, np.floating)) and math.isnan(float(value)):
                records[index][column] = {"native_nullable_role_value": "float.NaN"}
    return _sha(
        _json(
            {
                "columns": list(frame.columns),
                "dtypes": [str(dtype) for dtype in frame.dtypes],
                "rows": records,
                "index": frame.index.tolist(),
                "attrs": {k: v for k, v in frame.attrs.items() if k != RECEIPT_ATTR},
            }
        )
    )


def _validate_frames(
    native: pd.DataFrame,
    weekly: pd.DataFrame,
    roster: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
    availability: Mapping[int, float],
) -> dict[int, tuple[int, str]]:
    for frame in (native, weekly, roster, calendar):
        if not frame.index.is_unique or frame.columns.duplicated().any():
            raise ValueError("Captured frames need unique indexes and columns.")
    if not set(_ROSTER) <= set(roster) or roster.empty or roster.player_id.duplicated().any():
        raise ValueError("A complete unique captured roster is required.")
    players = {}
    for row in roster.to_dict("records"):
        player = _integer(row["player_id"], "player")
        club = _integer(row["club_code"], "persistent club")
        _integer(row["team_id"], "team alias")
        for field in ("buy_price_tenths", "sell_price_tenths"):
            _integer(row[field], field, 0)
        if row["position"] not in ("GK", "DEF", "MID", "FWD"):
            raise ValueError("Unknown player position.")
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise ValueError("A captured player requires an explicit name.")
        players[player] = (club, str(row["position"]))
    if (
        roster.groupby("club_code").team_id.nunique().gt(1).any()
        or roster.groupby("team_id").club_code.nunique().gt(1).any()
    ):
        raise ValueError("Persistent club and team aliases must map one to one.")
    if set(availability) != set(players):
        raise ValueError("Legacy eligibility must cover the complete captured roster.")
    for player, value in availability.items():
        _integer(player, "eligibility player")
        if not 0 <= _number(value, "legacy eligibility") <= 1:
            raise ValueError("Legacy eligibility is outside [0, 1].")
    if (
        native.attrs.get("season") != season
        or _instant(native.attrs.get("native_cutoff"), "native cutoff") != decision
        or native.attrs.get("availability_application") != "not_applied"
    ):
        raise ValueError("The native basis must be original and precede eligibility.")
    for frame in (native, calendar):
        if (
            frame.attrs.get("calendar_complete") is not True
            or tuple(frame.attrs.get("covered_gameweeks", ())) != gameweeks
        ):
            raise ValueError("Complete captured weekly calendar coverage is required.")
    if not re.fullmatch("[0-9a-f]{64}", str(native.attrs.get("captured_availability_sha256", ""))):
        raise ValueError("The legacy factor needs its original snapshot SHA256 receipt.")
    evidence = native.attrs.get("captured_availability_evidence_ref")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("The legacy factor needs an explicit source evidence reference.")
    if not set(_CALENDAR) <= set(calendar):
        raise ValueError("The complete captured fixture calendar is missing.")
    season_start = pd.Timestamp(f"{int(season[:4])}-07-01T00:00:00Z")
    season_end = pd.Timestamp(f"{int(season[:4]) + 1}-07-01T00:00:00Z")
    sides: dict[tuple[int, int], tuple[int, int, int, pd.Timestamp]] = {}
    for row in calendar.to_dict("records"):
        fixture, club, opponent = (_integer(row[n], n) for n in ("fixture", "club", "opponent"))
        week = _integer(row["GW"], "calendar week")
        home = _integer(row["home"], "home", 0)
        kickoff = _instant(row["kickoff"], "kickoff")
        if (
            week not in gameweeks
            or club == opponent
            or home not in (0, 1)
            or _instant(row["decision_at"], "calendar decision") != decision
            or kickoff <= deadline
            or not season_start <= kickoff < season_end
        ):
            raise ValueError("Invalid captured fixture identity or clock.")
        key = (fixture, club)
        if key in sides:
            raise ValueError("Repeated captured fixture side.")
        sides[key] = (opponent, home, week, kickoff)
    for (fixture, club), (opponent, home, week, kickoff) in sides.items():
        if sides.get((fixture, opponent)) != (club, 1 - home, week, kickoff):
            raise ValueError("The fixture calendar must contain coherent opposing sides.")
    if not {"model_version", "fixture", "player_code", "GW"} <= set(native):
        raise ValueError("The original native component identities are missing.")
    if not native.empty:
        versions = set(native.model_version)
        if len(versions) != 1 or next(iter(versions)) not in (
            FOOTBALL_MODEL_VERSION,
            *JOINT_ROLE_MODEL_VERSIONS,
        ):
            raise ValueError("Unsupported original native model version.")
        version = str(next(iter(versions)))
        component_rows(native, model_version=version, players=players)
        _validate_components(
            _clone(native), season, joint_role=version in JOINT_ROLE_MODEL_VERSIONS
        )
        if (native.goals + native.assists > native.team_goal_rate + 1e-12).any():
            raise ValueError("Native player credits exceed physical goal mass.")
    expected = {
        (fixture, player)
        for fixture, club in sides
        for player, (member, _) in players.items()
        if club == member
    }
    actual = {
        (_integer(row.fixture, "native fixture"), _integer(row.player_code, "native player"))
        for row in native.itertuples()
    }
    if actual != expected:
        raise ValueError("Original components lack complete fixture and club-roster coverage.")
    for row in native.to_dict("records"):
        for field in ("player_code", "fixture", "club", "opponent", "GW"):
            _integer(row[field], "native " + field)
        if _number(row["home"], "native home") not in (0, 1):
            raise ValueError("Invalid native home identity.")
        player, fixture = int(row["player_code"]), int(row["fixture"])
        club, position = players[player]
        opponent, home, week, kickoff = sides[fixture, club]
        if (
            row["club"] != club
            or row["position"] != position
            or row["opponent"] != opponent
            or row["home"] != home
            or row["GW"] != week
            or _instant(row["kickoff"], "native kickoff") != kickoff
            or ("decision_at" in row and _instant(row["decision_at"], "row cutoff") != decision)
            or ("season" in row and row["season"] != season)
            or row.get("availability_multiplier", 1.0) != 1.0
        ):
            raise ValueError("Original components contradict captured identity or cutoff.")
    if (
        not {"player_id", "gameweek", "expected_points", "appearance_probability"} <= set(weekly)
        or weekly.duplicated(["player_id", "gameweek"]).any()
        or set(zip(weekly.player_id, weekly.gameweek, strict=True))
        != {(player, week) for player in players for week in gameweeks}
    ):
        raise ValueError(
            "The supplied served reference needs complete unique player-week coverage."
        )
    return players


def _native_minutes(row: Mapping[str, object]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    fields = [(role, b) for role in ("start", "cameo") for b in (1, 2, 3)]
    return (
        (
            _number(row["zero_probability"], "native absence"),
            *(_number(row[f"{role}_minute_probability_{b}"], "native role") for role, b in fields),
        ),
        (0.0, *(_number(row[f"{role}_minute_value_{b}"], "native minutes") for role, b in fields)),
    )


def _bind_weeks(
    weeks: Sequence[LoadWeek],
    native: pd.DataFrame,
    players: Mapping[int, tuple[int, str]],
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
) -> dict[tuple[int, int], float]:
    if len(weeks) != len(players) * len(gameweeks):
        raise ValueError("The load arm needs every original player-week input.")
    basis = native_basis_digest(native)
    native_q: dict[tuple[int, int], float] = {}
    for week in weeks:
        validate_load_week(week)
        key = (week.player_code, week.gameweek)
        if (
            key in native_q
            or key[0] not in players
            or key[1] not in gameweeks
            or week.season != season
            or week.position != players[key[0]][1]
            or _instant(week.decision_at, "load decision") != decision
            or _instant(week.deadline_at, "load deadline") != deadline
            or week.native_basis_sha256 != basis
        ):
            raise ValueError("A load input differs from the original native capture.")
        rows = native.loc[native.player_code.eq(key[0]) & native.GW.eq(key[1])]
        lookup = {int(row["fixture"]): row for row in rows.to_dict("records")}
        if {f.fixture_id for f in week.fixtures} != set(lookup):
            raise ValueError("Load inputs do not contain the complete target fixture calendar.")
        for fixture in week.fixtures:
            row = lookup[fixture.fixture_id]
            if (
                row["model_version"] != week.native_model_version
                or row["model_version"] not in JOINT_ROLE_MODEL_VERSIONS
                or row["minute_role_status"] != "fitted_known_start_labels"
            ):
                raise ValueError("Enabled load needs recorded native starting-role support.")
            if (
                fixture.club_code != row["club"]
                or fixture.opponent_code != row["opponent"]
                or fixture.is_home != row["home"]
                or _instant(fixture.kickoff, "load fixture")
                != _instant(row["kickoff"], "native fixture")
                or _native_minutes({str(key): value for key, value in row.items()})
                != (fixture.probabilities, fixture.minutes)
            ):
                raise ValueError("Load input minute support belongs to a different native fixture.")
        mass = math.fsum(week.native_joint_probabilities)
        native_q[key] = (
            math.fsum(
                p
                for state, p in zip(
                    week.native_joint_states, week.native_joint_probabilities, strict=True
                )
                if any(state)
            )
            / mass
        )
    return native_q


def _prediction_check(prediction: WeekLoadPrediction, model: LoadMinutesModel) -> None:
    week = prediction.week
    if prediction.states != week.native_joint_states or len(prediction.probabilities) != len(
        prediction.states
    ):
        raise ValueError("Learned states must retain the complete declared native inventory.")
    probabilities = tuple(_number(p, "learned state mass") for p in prediction.probabilities)
    if any(p < 0 or p > 1 for p in probabilities) or not math.isclose(
        math.fsum(probabilities), 1.0, rel_tol=0, abs_tol=1e-12
    ):
        raise ValueError("Learned state probability mass is invalid.")
    if any(
        base == 0 and new != 0
        for base, new in zip(week.native_joint_probabilities, probabilities, strict=True)
    ):
        raise ValueError("Learned states cannot activate structural zero native support.")
    if (
        prediction.model_sha256 != model.model_sha256
        or prediction.input_sha256 != load_input_digest(week)
    ):
        raise ValueError("Learned model and input receipts differ from the supplied capture.")
    if len(prediction.fixture_probabilities) != len(week.fixtures):
        raise ValueError("Learned fixture marginal inventory is incomplete.")
    for fixture, marginal in enumerate(prediction.fixture_probabilities):
        if len(marginal) != 7:
            raise ValueError("Learned fixtures require all seven role states.")
        for cell, stated in enumerate(marginal):
            actual = math.fsum(
                p
                for state, p in zip(prediction.states, probabilities, strict=True)
                if state[fixture] == cell
            )
            if not math.isclose(
                _number(stated, "learned marginal"), actual, rel_tol=0, abs_tol=1e-12
            ):
                raise ValueError(
                    "Learned fixture marginals disagree with the retained whole-week law."
                )


def _owned_resources(
    resources: Mapping[str, object], players: Mapping[int, tuple[int, str]]
) -> tuple[int, ...]:
    owned = resources.get("owned")
    if not isinstance(owned, (list, tuple)) or len(owned) != 15:
        raise ValueError("Resources require an explicit original fifteen-player inventory.")
    ids = tuple(_integer(player, "original owned player") for player in owned)
    if len(set(ids)) != 15 or not set(ids) <= set(players):
        raise ValueError(
            "The original owned inventory is duplicated or outside the captured roster."
        )
    if "chips" in resources and (
        not isinstance(resources["chips"], dict)
        or any(
            type(value) is not bool
            for value in cast(dict[str, object], resources["chips"]).values()
        )
    ):
        raise ValueError("Captured chip availability must contain explicit booleans.")
    return tuple(sorted(ids))


def _reference(
    native: pd.DataFrame,
    weekly: pd.DataFrame,
    availability: Mapping[int, float],
    joint_q: Mapping[tuple[int, int], float] | None,
) -> None:
    for row in weekly.to_dict("records"):
        key = (
            _integer(row["player_id"], "served player"),
            _integer(row["gameweek"], "served week"),
        )
        part = native.loc[native.player_code.eq(key[0]) & native.GW.eq(key[1])]
        served_q = _number(row["appearance_probability"], "served appearance")
        if not 0 <= served_q <= availability[key[0]]:
            raise ValueError("The captured served appearance is outside its external eligibility.")
        expected = math.fsum(part.expected_points) * availability[key[0]]
        if not math.isclose(
            _number(row["expected_points"], "served points"), expected, rel_tol=1e-12, abs_tol=1e-12
        ) or (
            joint_q is not None
            and not math.isclose(
                served_q,
                joint_q[key] * availability[key[0]],
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(
                "The exact served control differs from its declared native law or eligibility."
            )


def _apply_predictions(
    native: pd.DataFrame, predictions: Sequence[WeekLoadPrediction], season: str
) -> pd.DataFrame:
    output = _clone(native)
    output.attrs.update(joint_role=True, season=season)
    lookup = {
        (
            _integer(row["fixture"], "native fixture"),
            _integer(row["player_code"], "native player"),
        ): index
        for index, row in native.iterrows()
    }
    for prediction in predictions:
        for f, fixture in enumerate(prediction.week.fixtures):
            index = lookup[fixture.fixture_id, prediction.week.player_code]
            probabilities = prediction.fixture_probabilities[f]
            output.at[index, "zero_probability"] = probabilities[0]
            output.at[index, "unknown_role_probability"] = 0.0
            for role, offset in (("start", 1), ("cameo", 4)):
                for b in (1, 2, 3):
                    output.at[index, f"{role}_minute_probability_{b}"] = probabilities[
                        offset + b - 1
                    ]
    output = _score_components(output)
    for _, indexes in native.groupby(["GW", "fixture", "club"], sort=False).groups.items():
        original = native.loc[indexes]
        old_minutes = original.expected_minutes.to_numpy(float)
        new_minutes = output.loc[indexes, "expected_minutes"].to_numpy(float)
        if ((old_minutes == 0) & (new_minutes != 0)).any():
            raise ValueError("A structural zero native minute law cannot gain exposure.")
        ratio = np.divide(
            new_minutes, old_minutes, out=np.zeros_like(new_minutes), where=old_minutes > 0
        )
        for count in ("goals", "assists"):
            weights = original[count + "_share"].to_numpy(float) * ratio
            denominator = math.fsum(weights)
            total = math.fsum(original[count])
            if total > 0 and denominator <= 0:
                raise ValueError("Retained native attacking mass lacks recipient minute support.")
            shares = weights / denominator if denominator > 0 else np.zeros_like(weights)
            output.loc[indexes, count + "_share"] = shares
            output.loc[indexes, count] = total * shares
    if (output.goals + output.assists > output.team_goal_rate + 1e-12).any():
        raise ValueError("Learned recipient credits exceed physical goal mass.")
    output = _score_components(output)
    if not np.isfinite(output.expected_points.to_numpy(float)).all():
        raise ValueError("Load composition exceeded finite point support.")
    _validate_components(_clone(output), season, joint_role=True)
    output["native_model_version"] = output.model_version
    output["model_version"] = EXPERIMENT_VERSION
    return output


def compose_load_experiment(
    native_components: pd.DataFrame,
    native_weekly: pd.DataFrame,
    roster: pd.DataFrame,
    calendar: pd.DataFrame,
    resource_bundle: Mapping[str, object],
    weeks: Sequence[LoadWeek],
    model: LoadMinutesModel | None,
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision_at: str,
    deadline_at: str,
    captured_availability: Mapping[int, float],
    enabled: bool = False,
    control: bool = False,
    zero_coefficients: bool = False,
) -> LoadExperiment:
    """Compose an explicit standalone arm without altering its supplied control."""
    if any(type(flag) is not bool for flag in (enabled, control, zero_coefficients)):
        raise ValueError("Load experiment switches must be explicit booleans.")
    if (control and not enabled) or (zero_coefficients and (control or not enabled)):
        raise ValueError(
            "Control binds an enabled joint receipt; the zero-coefficient ablation is a"
            " separate enabled learned arm."
        )
    if (
        not isinstance(season, str)
        or not re.fullmatch(r"\d{4}-\d{2}", season)
        or int(season[5:]) != (int(season[:4]) + 1) % 100
        or type(gameweeks) is not tuple
        or not gameweeks
        or tuple(sorted(set(gameweeks))) != gameweeks
        or any(_integer(week, "gameweek") > 38 for week in gameweeks)
    ):
        raise ValueError("An explicit season and unique ordered gameweeks are required.")
    if enabled and not control and season == "2025-26":
        raise ValueError("Protected outcomes cannot enter the learned load arm.")
    decision, deadline = _instant(decision_at, "decision"), _instant(deadline_at, "deadline")
    if decision >= deadline:
        raise ValueError("The decision must precede its deadline.")
    players = _validate_frames(
        native_components,
        native_weekly,
        roster,
        calendar,
        season=season,
        gameweeks=gameweeks,
        decision=decision,
        deadline=deadline,
        availability=captured_availability,
    )
    owned_ids = _owned_resources(resource_bundle, players)
    joint_q = (
        _bind_weeks(
            weeks,
            native_components,
            players,
            season=season,
            gameweeks=gameweeks,
            decision=decision,
            deadline=deadline,
        )
        if enabled
        else {}
    )
    _reference(
        native_components, native_weekly, captured_availability, joint_q if enabled else None
    )
    components, weekly = _clone(native_components), _clone(native_weekly)
    predictions: list[WeekLoadPrediction] = []
    if enabled and not control:
        if model is None:
            raise ValueError("Enabled load needs a fitted model.")
        predictions = [model.predict(week, zero_coefficients=zero_coefficients) for week in weeks]
        for week, prediction in zip(weeks, predictions, strict=True):
            if load_input_digest(prediction.week) != load_input_digest(week):
                raise ValueError(
                    "The learned prediction belongs to a different supplied player-week."
                )
            _prediction_check(prediction, model)
        if not components.empty:
            components = _apply_predictions(native_components, predictions, season)
        by_key = {(p.week.player_code, p.week.gameweek): p for p in predictions}
        for index, row in weekly.iterrows():
            key = (int(row.player_id), int(row.gameweek))
            prediction = by_key[key]
            q = math.fsum(
                p
                for state, p in zip(prediction.states, prediction.probabilities, strict=True)
                if any(state)
            )
            if not math.isclose(q, prediction.weekly_appearance, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Learned weekly appearance disagrees with retained joint states.")
            part = components.loc[components.player_code.eq(key[0]) & components.GW.eq(key[1])]
            weekly.at[index, "expected_points"] = captured_availability[key[0]] * math.fsum(
                part.expected_points
            )
            weekly.at[index, "appearance_probability"] = captured_availability[key[0]] * q
        weekly.attrs["load_model_sha256"] = model.model_sha256
    resources = _json(resource_bundle)
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
            "roster_sha256": native_basis_digest(roster),
            "calendar_sha256": native_basis_digest(calendar),
            "resource_bundle_sha256": _sha(resources),
            "owned_player_ids": owned_ids,
            "captured_availability": {str(k): v for k, v in sorted(captured_availability.items())},
            "captured_availability_sha256": native_components.attrs["captured_availability_sha256"],
            "captured_availability_evidence_ref": native_components.attrs[
                "captured_availability_evidence_ref"
            ],
            "availability_scope": "external_legacy_once_per_player_week",
            "model_metadata_json": model.metadata_json
            if predictions and model is not None
            else None,
            "load_input_sha256": [p.input_sha256 for p in predictions],
            "native_joint_input_sha256": [week.source_sha256 for week in weeks] if enabled else [],
            "lineup_scope": "bounded_fixed_squad_neighborhood_only",
            "lineup_assumptions": "independent_player_week_appearance_and_conditional_points",
        }
    )
    for frame in (components, weekly, roster := _clone(roster)):
        frame.attrs[RECEIPT_ATTR] = receipt
    return LoadExperiment(components, weekly, roster, receipt, resources)


def plan_load_fixed_fifteen(
    experiment: LoadExperiment,
    player_ids: Sequence[object],
    starting_xi: Sequence[object],
    ordered_bench: Sequence[object],
    captain_id: object,
    vice_captain_id: object,
    *,
    gameweek: int,
    max_evaluations: int = 128,
    chip: str | None = None,
    hit_points: float = 0,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
    locked_first: bool = False,
) -> LoadFixedFifteenPlan:
    """Choose legal roles on the same captured fifteen with unchanged resources."""
    try:
        receipt, resources = (
            json.loads(experiment.receipt_json),
            json.loads(experiment.resource_bundle_json),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid private load receipt.") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != EXPERIMENT_VERSION
        or _json(receipt) != experiment.receipt_json
        or _json(resources) != experiment.resource_bundle_json
    ):
        raise ValueError("The private load receipt must retain its canonical version.")
    for name, frame in (
        ("components", experiment.components),
        ("weekly", experiment.weekly),
        ("roster", experiment.roster),
    ):
        if (
            native_basis_digest(frame) != receipt.get(name + "_sha256")
            or frame.attrs.get(RECEIPT_ATTR) != experiment.receipt_json
        ):
            raise ValueError("Private load frame values or metadata changed after composition.")
    if _sha(experiment.resource_bundle_json) != receipt.get("resource_bundle_sha256"):
        raise ValueError("Captured native resources changed after composition.")
    if _integer(max_evaluations, "role evaluation budget") > 128:
        raise ValueError("The private role search permits at most 128 evaluations.")
    week = _integer(gameweek, "plan week")
    ids = {_integer(player, "plan player") for player in player_ids}
    if (
        len(player_ids) != 15
        or len(ids) != 15
        or week not in receipt["gameweeks"]
        or not ids <= set(experiment.roster.player_id)
        or sorted(ids) != receipt.get("owned_player_ids")
    ):
        raise ValueError("The original fifteen and requested covered week must be explicit.")
    squad = _clone(experiment.roster.loc[experiment.roster.player_id.isin(ids)])
    if squad.groupby("club_code").size().gt(3).any():
        raise ValueError("A legal fixed fifteen permits at most three players per persistent club.")
    blocked_start, blocked_captain = tuple(not_starting), tuple(not_captain)
    if not isinstance(resources, dict):
        raise ValueError("Captured resources need an explicit object.")
    if chip is not None and (
        not isinstance(resources.get("chips"), dict) or resources["chips"].get(chip) is not True
    ):
        raise ValueError("The requested chip is unavailable in the original captured inventory.")
    for field, value in (
        ("chip", chip),
        ("hit_points", hit_points),
        ("locked_first", locked_first),
        ("not_starting", list(blocked_start)),
        ("not_captain", list(blocked_captain)),
    ):
        if field in resources and _json(resources[field]) != _json(value):
            raise ValueError("Role search cannot change a retained resource or restriction.")
    weekly = experiment.weekly.loc[experiment.weekly.gameweek.eq(week)].set_index("player_id")
    for field in ("expected_points", "appearance_probability"):
        squad[field] = squad.player_id.map(weekly[field])
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
        not_starting=blocked_start,
        not_captain=blocked_captain,
    )
    plan_receipt = _json(
        {
            "version": "football_load_fixed_fifteen_v1",
            "gameweek": week,
            "experiment_sha256": _sha(experiment.receipt_json),
            "squad_sha256": native_basis_digest(squad),
            "resource_bundle_sha256": _sha(experiment.resource_bundle_json),
            "best_fingerprint": search.best.fingerprint,
            "proof_scope": search.proof_scope,
        }
    )
    return LoadFixedFifteenPlan(squad, search, experiment.resource_bundle_json, plan_receipt)
