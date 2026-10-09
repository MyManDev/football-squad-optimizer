"""Private flag replacement using a learned whole-week minute distribution.

The old served forecast is a separate exact control. Learned participation replaces
its captured flag multiplier, rather than applying it again to each match or week.
No public producer, worker or member route invokes this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import cast

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from squadopt.features.football_flag_inputs import PlayerWeekInput, validate_week_input
from squadopt.live.minute_evidence import _validate_components
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSIONS
from squadopt.prediction.football_components import component_rows
from squadopt.prediction.football_flag_minutes import FlagMinutesModel, WeekMinutePrediction
from squadopt.scenarios.expected_lineup import ExpectedLineupSearchResult, improve_expected_lineup

EXPERIMENT_VERSION = "football_flag_experiment_v1"
RECEIPT_ATTR = "football_flag_experiment_receipt"
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
GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}


@dataclass(frozen=True)
class FlagExperiment:
    components: pd.DataFrame
    weekly: pd.DataFrame
    roster: pd.DataFrame
    receipt_json: str
    resource_bundle_json: str


@dataclass(frozen=True)
class FlagFixedFifteenPlan:
    squad: pd.DataFrame
    search: ExpectedLineupSearchResult
    resource_bundle_json: str
    receipt_json: str


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} requires a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} requires a finite real number.")
    return result


def _integer(value: object, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum:
        raise ValueError(f"{label} requires an integer at least {minimum}.")
    return int(value)


def _instant(value: object, label: str) -> pd.Timestamp:
    if not isinstance(value, (str, pd.Timestamp)):
        raise ValueError(f"{label} requires an explicit timezone-aware instant.")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label} requires an explicit instant.") from error
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError(f"{label} requires an explicit timezone-aware instant.")
    return result.tz_convert("UTC")


def _canonical(value: object) -> object:
    if value is None or type(value) in (str, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return _finite(value, "receipt number")
    if isinstance(value, pd.Timestamp):
        return _instant(value, "receipt instant").isoformat()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError("Receipt objects require named string keys.")
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise ValueError("Receipts require canonical JSON-compatible values.")


def _json(value: object) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def native_basis_digest(frame: pd.DataFrame) -> str:
    """Bind the complete supplied basis, including order, index and metadata."""
    return _sha(
        _json(
            {
                "columns": list(frame.columns),
                "rows": frame.to_dict("records"),
                "index": frame.index.tolist(),
                "attrs": {key: value for key, value in frame.attrs.items() if key != RECEIPT_ATTR},
            }
        )
    )


def _roster(frame: pd.DataFrame) -> dict[int, tuple[int, str]]:
    if not set(ROSTER_COLUMNS) <= set(frame) or frame.empty or frame.player_id.duplicated().any():
        raise ValueError("A complete unique captured roster is required.")
    result: dict[int, tuple[int, str]] = {}
    for row in frame.to_dict("records"):
        player = _integer(row["player_id"], "roster player")
        club = _integer(row["club_code"], "roster club")
        if row["position"] not in GOAL_POINTS:
            raise ValueError("Unknown roster position.")
        if not isinstance(row["name"], str) or not row["name"]:
            raise ValueError("Roster names require explicit text.")
        _integer(row["team_id"], "roster team")
        _integer(row["buy_price_tenths"], "buy price", 0)
        _integer(row["sell_price_tenths"], "sell price", 0)
        result[player] = (club, str(row["position"]))
    if (
        frame.groupby("club_code").team_id.nunique().gt(1).any()
        or frame.groupby("team_id").club_code.nunique().gt(1).any()
    ):
        raise ValueError(
            "Captured team and persistent club identities require a bijective mapping."
        )
    return result


def _calendar(
    frame: pd.DataFrame,
    gameweeks: tuple[int, ...],
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
) -> dict[tuple[int, int], tuple[int, int, int, pd.Timestamp]]:
    if not set(CALENDAR_COLUMNS) <= set(frame):
        raise ValueError("A complete explicitly covered fixture calendar is required.")
    result: dict[tuple[int, int], tuple[int, int, int, pd.Timestamp]] = {}
    for row in frame.to_dict("records"):
        fixture = _integer(row["fixture"], "fixture")
        club = _integer(row["club"], "club")
        opponent = _integer(row["opponent"], "opponent")
        week = _integer(row["GW"], "gameweek")
        home = _integer(row["home"], "home", 0)
        kickoff = _instant(row["kickoff"], "kickoff")
        if week not in gameweeks or home not in (0, 1) or club == opponent:
            raise ValueError("Calendar fixture identity is invalid.")
        if _instant(row["decision_at"], "calendar decision") != decision or kickoff < deadline:
            raise ValueError("Calendar decision or kickoff mismatches the capture.")
        key = (fixture, club)
        if key in result:
            raise ValueError("Repeated fixture side.")
        result[key] = (opponent, home, week, kickoff)
    for (fixture, club), (opponent, home, week, kickoff) in result.items():
        if result.get((fixture, opponent)) != (club, 1 - home, week, kickoff):
            raise ValueError("Calendar lacks consistent paired fixture sides.")
    return result


def _native_support(row: Mapping[str, object]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    probabilities = [_finite(row["zero_probability"], "native zero mass")]
    minutes = [0.0]
    for role in ("start", "cameo"):
        for b in (1, 2, 3):
            probabilities.append(_finite(row[f"{role}_minute_probability_{b}"], "role mass"))
            minutes.append(_finite(row[f"{role}_minute_value_{b}"], "role minutes"))
    return tuple(probabilities), tuple(minutes)


def _validate_basis(
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
) -> tuple[dict[int, tuple[int, str]], str]:
    players = _roster(roster)
    if (
        native.attrs.get("season") != season
        or _instant(native.attrs.get("native_cutoff"), "native cutoff") != decision
        or native.attrs.get("calendar_complete") is not True
        or tuple(native.attrs.get("covered_gameweeks", ())) != gameweeks
    ):
        raise ValueError("Native basis lacks its original cutoff or complete weekly coverage.")
    if native.attrs.get("availability_application") != "not_applied":
        raise ValueError("Native basis must precede the captured eligibility rule.")
    legacy_config = native.attrs.get(
        "legacy_availability_config",
        {
            "unknown_is_available": True,
            "doubtful_multiplier_floor": 0.0,
        },
    )
    if (
        not isinstance(legacy_config, Mapping)
        or set(legacy_config) != {"unknown_is_available", "doubtful_multiplier_floor"}
        or legacy_config["unknown_is_available"] is not True
        or _finite(legacy_config["doubtful_multiplier_floor"], "legacy floor") != 0
    ):
        raise ValueError("This private comparison requires the declared default legacy rule.")
    if set(availability) != set(players):
        raise ValueError("Captured legacy eligibility must cover the full roster.")
    for player, multiplier in availability.items():
        _integer(player, "availability player")
        if not 0 <= _finite(multiplier, "legacy eligibility") <= 1:
            raise ValueError("Legacy eligibility lies outside unit support.")
    sides = _calendar(calendar, gameweeks, decision, deadline)
    if not {"model_version", "fixture", "club", "player_code"} <= set(native):
        raise ValueError("Native fixture basis lacks identity or version fields.")
    if not native.index.is_unique or not weekly.index.is_unique or not roster.index.is_unique:
        raise ValueError("Private frame indexes must be unique before replacement.")
    if not native.empty:
        versions = set(native.model_version)
        if len(versions) != 1 or not isinstance(next(iter(versions)), str):
            raise ValueError("Native basis must declare one original model version.")
        if str(next(iter(versions))) not in (FOOTBALL_MODEL_VERSION, *JOINT_ROLE_MODEL_VERSIONS):
            raise ValueError("Unsupported native component model version.")
        component_rows(native, model_version=str(next(iter(versions))), players=players)
        _validate_components(
            native.copy(deep=True),
            season,
            joint_role=str(next(iter(versions))) in JOINT_ROLE_MODEL_VERSIONS,
        )
    expected = {
        (fixture, player)
        for fixture, club in sides
        for player, (player_club, _) in players.items()
        if club == player_club
    }
    actual = {
        (_integer(row.fixture, "native fixture"), _integer(row.player_code, "native player"))
        for row in native.itertuples()
    }
    if expected != actual:
        raise ValueError("Native components do not cover the complete captured club rosters.")
    for row in native.to_dict("records"):
        fixture = _integer(row["fixture"], "native fixture")
        player = _integer(row["player_code"], "native player")
        for name in ("club", "opponent", "GW"):
            _integer(row[name], "native " + name)
        if _finite(row["home"], "native home") not in (0, 1):
            raise ValueError("Native home flag must be zero or one.")
        if (
            "decision_at" in row and _instant(row["decision_at"], "native row decision") != decision
        ) or ("season" in row and row["season"] != season):
            raise ValueError("Native row season or decision clock contradicts its original basis.")
        club, position = players[player]
        if row["club"] != club or row["position"] != position:
            raise ValueError("Native player club or position mismatches the captured roster.")
        opponent, home, week, kickoff = sides[fixture, club]
        if (
            row["opponent"] != opponent
            or row["home"] != home
            or row["GW"] != week
            or _instant(row["kickoff"], "native kickoff") != kickoff
            or ("availability_multiplier" in row and row["availability_multiplier"] != 1)
        ):
            raise ValueError("Native fixture identity or unapplied eligibility mismatches.")
    if not {"player_id", "gameweek", "expected_points", "appearance_probability"} <= set(weekly):
        raise ValueError("Original served weekly forecast is required for the exact control.")
    if weekly.duplicated(["player_id", "gameweek"]).any():
        raise ValueError("Repeated served player-week.")
    if set(zip(weekly.player_id, weekly.gameweek, strict=True)) != {
        (player, week) for player in players for week in gameweeks
    }:
        raise ValueError("Original served weekly forecast lacks complete roster/week coverage.")
    for row in weekly.to_dict("records"):
        player = _integer(row["player_id"], "weekly player")
        week = _integer(row["gameweek"], "weekly gameweek")
        part = native.loc[native.player_code.eq(player) & native.GW.eq(week)]
        multiplier = availability[player]
        points = float(part.expected_points.sum()) * multiplier
        q = (1 - math.prod(1 - float(v) for v in part.appearance_probability)) * multiplier
        if not math.isclose(
            _finite(row["expected_points"], "weekly points"), points, rel_tol=1e-12, abs_tol=1e-12
        ) or not math.isclose(
            _finite(row["appearance_probability"], "weekly appearance"),
            q,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Original served values do not bind the native legacy control.")
    return players, native_basis_digest(native)


def _bind_weeks(
    weeks: Sequence[PlayerWeekInput],
    native: pd.DataFrame,
    players: Mapping[int, tuple[int, str]],
    gameweeks: tuple[int, ...],
    season: str,
    decision: pd.Timestamp,
    deadline: pd.Timestamp,
    basis_digest: str,
    captured_availability: Mapping[int, float],
) -> None:
    if len(weeks) != len(players) * len(gameweeks):
        raise ValueError("Enabled learned inputs must cover every captured player-week.")
    seen: set[tuple[int, int]] = set()
    for week in weeks:
        validate_week_input(week)
        key = (week.player_code, week.gameweek)
        if key in seen or key[0] not in players or key[1] not in gameweeks:
            raise ValueError("Duplicate or unknown learned player-week.")
        seen.add(key)
        if (
            week.season != season
            or _instant(week.decision_at, "input decision") != decision
            or _instant(week.deadline_at, "input deadline") != deadline
            or week.native_basis_sha256 != basis_digest
            or week.position != players[week.player_code][1]
        ):
            raise ValueError("Learned input differs from its original native capture basis.")
        legacy = apply_availability(
            pd.DataFrame({"player_id": [week.player_code], "expected_points": [1.0]}),
            pd.DataFrame(
                {
                    "player_id": [week.player_code],
                    "status": [week.status],
                    "chance_of_playing": [week.legacy_next_round_label],
                }
            ),
        )
        if float(legacy.multiplier.iloc[0]) != captured_availability[week.player_code]:
            raise ValueError(
                "Learned facts and legacy control use different captured availability."
            )
        part = native.loc[native.player_code.eq(week.player_code) & native.GW.eq(week.gameweek)]
        by_fixture = {int(row["fixture"]): row for row in part.to_dict("records")}
        if {f.fixture for f in week.fixtures} != set(by_fixture):
            raise ValueError("Input lacks complete player-week fixture coverage.")
        for fixture in week.fixtures:
            row = by_fixture[fixture.fixture]
            if row["model_version"] not in JOINT_ROLE_MODEL_VERSIONS:
                raise ValueError("Learned role replacement needs a native known-role basis.")
            if row["minute_role_status"] != "fitted_known_start_labels":
                raise ValueError("Missing starting roles cannot be inferred from minutes.")
            if (
                fixture.club != row["club"]
                or fixture.opponent != row["opponent"]
                or fixture.home != row["home"]
                or _instant(fixture.kickoff, "input kickoff") != _instant(row["kickoff"], "kickoff")
            ):
                raise ValueError("Input minute support belongs to another fixture side.")
            probabilities, minutes = _native_support(
                {str(key): value for key, value in row.items()}
            )
            if probabilities != fixture.probabilities or minutes != fixture.minutes:
                raise ValueError("Input minute law differs from the immutable native support.")


def _marginal_updates(
    row: Mapping[str, object],
    prediction: WeekMinutePrediction,
    fixture_index: int,
    season: str,
) -> dict[str, object]:
    fixture = prediction.week.fixtures[fixture_index]
    p = np.asarray(prediction.fixture_probabilities[fixture_index], dtype=float)
    m = np.asarray(fixture.minutes, dtype=float)
    q = float(p[1:].sum())
    expected = float(p @ m)
    bins = np.array([0, 1, 2, 3, 1, 2, 3])
    p60 = float(p[bins >= 2].sum())
    cs = float(
        np.sum(
            p[bins >= 2]
            * np.exp(-_finite(row["opponent_goal_rate"], "opposing intensity") * m[bins >= 2] / 90)
        )
    )
    position = str(row["position"])
    threshold = 10 if position == "DEF" else 12
    rate = _finite(row["defcon_rate90"], "defensive count rate")
    dispersion = _finite(row["defcon_dispersion"], "defensive dispersion")
    means = rate * m[1:] / 90
    dc = (
        0.0
        if position == "GK"
        else float(
            np.sum(p[1:] * nbinom.sf(threshold - 1, dispersion, dispersion / (dispersion + means)))
        )
    )
    if not all(math.isfinite(v) for v in (q, expected, p60, cs, dc)):
        raise ValueError("Learned minute scoring exceeded finite support.")
    result: dict[str, object] = dict(row)
    result.update(
        expected_minutes=expected,
        appearance_probability=q,
        p60=p60,
        clean_sheet_probability=cs,
        defcon_probability=dc,
        zero_probability=float(p[0]),
        start_probability=float(p[1:4].sum()),
        cameo_probability=float(p[4:].sum()),
        unknown_role_probability=0.0,
        expected_minutes_if_appearance=expected / q if q else 0.0,
        model_version=EXPERIMENT_VERSION,
        availability_multiplier=1.0,
    )
    for role, offset in (("start", 0), ("cameo", 3)):
        for b in (1, 2, 3):
            result[f"{role}_minute_probability_{b}"] = float(p[offset + b])
            result[f"{role}_minute_value_{b}"] = float(m[offset + b])
    for b in range(4):
        mask = bins == b
        mass = float(p[mask].sum())
        representative = float(np.sum(p[mask] * m[mask]) / mass) if mass else (0, 30, 75, 90)[b]
        lower, upper = (
            (0, 0),
            (np.nextafter(0.0, 1.0), np.nextafter(60.0, 0.0)),
            (60, np.nextafter(90.0, 0.0)),
            (90, 120),
        )[b]
        result[f"minute_probability_{b}"] = mass
        result[f"minute_value_{b}"] = float(np.clip(representative, lower, upper))
    result["flag_minute_model_sha256"] = prediction.model_sha256
    result["flag_input_sha256"] = prediction.input_sha256
    result["flag_weekly_appearance"] = prediction.weekly_appearance
    result["flag_eligibility_application"] = "replaced_by_learned_whole_week_law"
    # Points are recomputed after complete-club allocation below.
    result["flag_defcon_active"] = int(season[:4]) >= 2025
    result["flag_goal_coefficient"] = (
        10 if position == "GK" and season >= "2024-25" else GOAL_POINTS[position]
    )
    return result


def _allocate_and_score(native: pd.DataFrame, updated: pd.DataFrame) -> pd.DataFrame:
    output = updated.copy(deep=True)
    originals = native.set_index(["fixture", "player_code"])
    for (fixture, _), group in output.groupby(["fixture", "club"], sort=True):
        indices = group.index
        old = originals.loc[[(fixture, int(p)) for p in group.player_code]]
        old_minutes = old.expected_minutes.to_numpy(float)
        new_minutes = group.expected_minutes.to_numpy(float)
        if ((old_minutes == 0) & (new_minutes > 0)).any():
            raise ValueError("Native zero minute support cannot allocate a new positive recipient.")
        ratio = np.divide(
            new_minutes, old_minutes, out=np.zeros_like(new_minutes), where=old_minutes > 0
        )
        for count, share in (("goals", "goals_share"), ("assists", "assists_share")):
            total = math.fsum(old[count].to_numpy(float))
            old_share = old[share].to_numpy(float)
            if total > 0 and not math.isclose(
                math.fsum(old_share), 1.0, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("Native positive attacking mass lacks a full-club share basis.")
            if not np.allclose(
                old[count].to_numpy(float), total * old_share, rtol=1e-12, atol=1e-12
            ):
                raise ValueError("Native attacking counts disagree with their club share basis.")
            weights = old_share * ratio
            mass = math.fsum(weights)
            if total > 0 and mass <= 0:
                raise ValueError("A positive native club total has no learned minute support.")
            shares = weights / mass if mass > 0 else np.zeros_like(weights)
            output.loc[indices, share] = shares
            output.loc[indices, count] = total * shares
    if (
        output.goals.to_numpy(float) + output.assists.to_numpy(float)
        > output.team_goal_rate.to_numpy(float) + 1e-12
    ).any():
        raise ValueError(
            "A player cannot receive scorer and assist credit on the same physical goal."
        )
    q = output.appearance_probability.to_numpy(float)
    p60 = output.p60.to_numpy(float)
    raw = (
        q
        + p60
        + output.flag_goal_coefficient.to_numpy(float) * output.goals.to_numpy(float)
        + 3 * output.assists.to_numpy(float)
        + output.position.map(CS_POINTS).to_numpy(float)
        * output.clean_sheet_probability.to_numpy(float)
        + 2 * output.flag_defcon_active.to_numpy(float) * output.defcon_probability.to_numpy(float)
        + q * output.residual_if_appearance.to_numpy(float)
    )
    if not np.isfinite(raw).all():
        raise ValueError("Learned fixture points exceeded finite support.")
    output["raw_expected_points"] = raw
    output["expected_points"] = np.maximum(raw, 0)
    return output


def compose_flag_experiment(
    native_components: pd.DataFrame,
    native_weekly: pd.DataFrame,
    roster: pd.DataFrame,
    calendar: pd.DataFrame,
    resource_bundle: Mapping[str, object],
    weeks: Sequence[PlayerWeekInput],
    model: FlagMinutesModel | None,
    *,
    season: str,
    gameweeks: tuple[int, ...],
    decision_at: str,
    deadline_at: str,
    captured_availability: Mapping[int, float],
    enabled: bool = False,
    control: bool = False,
    zero_coefficients: bool = False,
) -> FlagExperiment:
    """Compose a private replacement; preserve supplied served values in control.

    Zero coefficients mean the unflagged independent-fixture native ablation.
    They do not mean the old served rule has been applied. Conditional fixture
    independence is replaced within each week; player-week independence in the
    downstream bounded role scorer remains an explicit approximation.
    """
    if any(type(flag) is not bool for flag in (enabled, control, zero_coefficients)):
        raise ValueError("Experiment switches must be explicit booleans.")
    if (
        not isinstance(season, str)
        or len(season) != 7
        or season[4] != "-"
        or not season[:4].isdigit()
        or not season[5:].isdigit()
        or not gameweeks
        or type(gameweeks) is not tuple
        or tuple(sorted(set(gameweeks))) != gameweeks
    ):
        raise ValueError("Experiment requires explicit season and unique ordered weeks.")
    for week in gameweeks:
        if _integer(week, "gameweek") > 38:
            raise ValueError("Unsupported gameweek.")
    if enabled and not control and season == "2025-26":
        raise ValueError("Protected 2025-26 cannot enter this private learned experiment.")
    decision, deadline = _instant(decision_at, "decision"), _instant(deadline_at, "deadline")
    if decision >= deadline:
        raise ValueError("Decision must precede its deadline.")
    players, basis = _validate_basis(
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
    resources_json = _json(resource_bundle)
    components = native_components.copy(deep=True)
    weekly = native_weekly.copy(deep=True)
    predictions: list[WeekMinutePrediction] = []
    if enabled and not control:
        if model is None:
            raise ValueError("Enabled learned replacement needs a fitted model.")
        _bind_weeks(
            weeks,
            native_components,
            players,
            gameweeks,
            season,
            decision,
            deadline,
            basis,
            captured_availability,
        )
        predictions = [model.predict(week, zero_coefficients=zero_coefficients) for week in weeks]
        updates: dict[tuple[int, int], dict[str, object]] = {}
        originals = {
            (int(row["fixture"]), int(row["player_code"])): {
                str(key): value for key, value in row.items()
            }
            for row in native_components.to_dict("records")
        }
        week_values: dict[tuple[int, int], float] = {}
        for prediction in predictions:
            week_values[prediction.week.player_code, prediction.week.gameweek] = (
                prediction.weekly_appearance
            )
            for index, fixture in enumerate(prediction.week.fixtures):
                key = (fixture.fixture, prediction.week.player_code)
                updates[key] = _marginal_updates(originals[key], prediction, index, season)
        if updates:
            components = pd.DataFrame(
                [
                    updates[int(row["fixture"]), int(row["player_code"])]
                    for row in native_components.to_dict("records")
                ],
                index=native_components.index,
            )
            components.attrs = dict(native_components.attrs)
            components = _allocate_and_score(native_components, components)
        for weekly_index, row in weekly.iterrows():
            player, week = int(row.player_id), int(row.gameweek)
            weekly.loc[weekly_index, "expected_points"] = float(
                components.loc[
                    components.player_code.eq(player) & components.GW.eq(week), "expected_points"
                ].sum()
            )
            weekly.loc[weekly_index, "appearance_probability"] = week_values[player, week]
    receipt: dict[str, object] = {
        "contract_version": EXPERIMENT_VERSION,
        "enabled": enabled,
        "control": control,
        "zero_coefficients": zero_coefficients,
        "season": season,
        "gameweeks": gameweeks,
        "decision_at": decision.isoformat(),
        "deadline_at": deadline.isoformat(),
        "native_basis_sha256": basis,
        "native_weekly_sha256": native_basis_digest(native_weekly),
        "components_sha256": native_basis_digest(components),
        "weekly_sha256": native_basis_digest(weekly),
        "roster_sha256": native_basis_digest(roster),
        "calendar_sha256": native_basis_digest(calendar),
        "resource_bundle_sha256": _sha(resources_json),
        "captured_availability": {
            str(key): value for key, value in sorted(captured_availability.items())
        },
        "replacement_scope": "legacy_control"
        if not enabled or control
        else "learned_whole_week_minutes",
        "availability_application": "legacy_once"
        if not enabled or control
        else "no_second_flag_multiplier",
        "legacy_availability_config": {
            "unknown_is_available": True,
            "doubtful_multiplier_floor": 0.0,
        },
        "legacy_availability_source_field": "chance_of_playing_next_round",
        "minute_input_sha256": [prediction.input_sha256 for prediction in predictions],
        "model_sha256": None if not predictions else predictions[0].model_sha256,
        "model_metadata_json": None if not predictions else model.metadata_json if model else None,
        "retained_scope": (
            "native_team_intensity_club_credited_totals_per90_defcon_residual_resources"
        ),
        "lineup_proof_scope": "bounded_fixed_squad_neighborhood_only",
        "lineup_assumption": "independent_player_week_appearances_and_conditional_points",
    }
    receipt_json = _json(receipt)
    for frame in (components, weekly):
        frame.attrs[RECEIPT_ATTR] = receipt_json
    return FlagExperiment(components, weekly, roster.copy(deep=True), receipt_json, resources_json)


def _validate_experiment(experiment: FlagExperiment) -> dict[str, object]:
    try:
        receipt = json.loads(experiment.receipt_json)
        resources = json.loads(experiment.resource_bundle_json)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid private experiment receipt.") from error
    if not isinstance(receipt, dict) or receipt.get("contract_version") != EXPERIMENT_VERSION:
        raise ValueError("Unknown private experiment receipt.")
    if (
        _json(receipt) != experiment.receipt_json
        or _json(resources) != experiment.resource_bundle_json
    ):
        raise ValueError("Private receipts must remain canonical.")
    for name, frame in (
        ("components", experiment.components),
        ("weekly", experiment.weekly),
        ("roster", experiment.roster),
    ):
        if native_basis_digest(frame) != receipt.get(f"{name}_sha256"):
            raise ValueError(f"Private experiment {name} changed after composition.")
        if name != "roster" and frame.attrs.get(RECEIPT_ATTR) != experiment.receipt_json:
            raise ValueError("Private frame receipt differs from the experiment receipt.")
    if _sha(experiment.resource_bundle_json) != receipt.get("resource_bundle_sha256"):
        raise ValueError("Native resources changed after composition.")
    return cast(dict[str, object], receipt)


def plan_flag_fixed_fifteen(
    experiment: FlagExperiment,
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
) -> FlagFixedFifteenPlan:
    """Select roles on the same legal fifteen; transfers/resources remain outside search."""
    receipt = _validate_experiment(experiment)
    if _integer(max_evaluations, "private role evaluation budget") > 128:
        raise ValueError("This private role experiment permits at most 128 evaluations.")
    week = _integer(gameweek, "plan gameweek")
    if week not in cast(list[int], receipt["gameweeks"]):
        raise ValueError("Private forecast does not cover the requested plan week.")
    if len(player_ids) != 15 or len(set(player_ids)) != 15:
        raise ValueError("Exactly fifteen unique captured players are required.")
    ids = {_integer(player, "plan player") for player in player_ids}
    roster = experiment.roster
    if not ids <= set(roster.player_id):
        raise ValueError("Plan contains an uncaptured player.")
    if roster.loc[roster.player_id.isin(ids)].groupby("club_code").size().gt(3).any():
        raise ValueError("The same legal fifteen permits at most three players per club.")
    resources = json.loads(experiment.resource_bundle_json)
    blocked_start, blocked_captain = tuple(not_starting), tuple(not_captain)
    if isinstance(resources, dict):
        for name, value in (
            ("hit_points", hit_points),
            ("chip", chip),
            ("locked_first", locked_first),
        ):
            if name in resources and resources[name] != value:
                raise ValueError("Plan would change a retained native resource or restriction.")
        for name, values in (("not_starting", blocked_start), ("not_captain", blocked_captain)):
            if name in resources and _json(resources[name]) != _json(list(values)):
                raise ValueError("Plan would change a retained native restriction.")
    squad = roster.loc[roster.player_id.isin(ids)].copy()
    forecasts = experiment.weekly.loc[experiment.weekly.gameweek.eq(week)].set_index("player_id")
    for name in ("expected_points", "appearance_probability"):
        squad[name] = squad.player_id.map(forecasts[name])
    search = improve_expected_lineup(
        squad,
        starting_xi,
        ordered_bench,
        captain_id,
        vice_captain_id,
        chip=chip,
        hit_points=hit_points,
        not_starting=blocked_start,
        not_captain=blocked_captain,
        max_evaluations=max_evaluations,
        locked_first=locked_first,
    )
    plan_receipt = _json(
        {
            "contract_version": "football_flag_fixed_fifteen_v1",
            "experiment_sha256": _sha(experiment.receipt_json),
            "gameweek": week,
            "player_ids": sorted(ids),
            "squad_sha256": native_basis_digest(squad),
            "best_fingerprint": search.best.fingerprint,
            "resource_bundle_sha256": _sha(experiment.resource_bundle_json),
            "proof_scope": search.proof_scope,
        }
    )
    return FlagFixedFifteenPlan(squad, search, experiment.resource_bundle_json, plan_receipt)
