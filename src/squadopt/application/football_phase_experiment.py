"""Private phase allocation, weekly eligibility and fixed-fifteen role adapter.

No live route invokes this module. It replaces the native attacking marginals,
retains nonattacking components and resources, and delegates official autosubs
to the existing bounded role scorer after full-club allocation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict
from numbers import Integral, Real
from typing import Any, cast

import numpy as np
import pandas as pd

from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.features.football_phase_inputs import (
    PhaseProjection,
    projection_digest,
    validate_projection,
)
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSIONS,
    ROLE_MODEL_VERSION,
)
from squadopt.prediction.football_components import (
    COMPONENT_COLUMNS,
    IDENTITY_COLUMNS,
    component_rows,
)
from squadopt.prediction.football_phase_duties import (
    FEATURE_VERSION,
    MODEL_VERSION,
    PhaseAllocation,
    PhaseDutyModel,
)
from squadopt.scenarios.expected_lineup import (
    ExpectedLineupSearchResult,
    improve_expected_lineup,
)

PHASE_COMPONENT_VERSION = "private_football_phase_components_v1"
PHASE_WEEKLY_VERSION = "private_football_phase_weekly_v1"
_NATIVE_VERSIONS = (FOOTBALL_MODEL_VERSION, ROLE_MODEL_VERSION, *JOINT_ROLE_MODEL_VERSIONS)
_CALENDAR = ("GW", "fixture", "club", "opponent", "home", "kickoff", "decision_at")
_SCORED_COLUMNS = (
    "goals",
    "assists",
    "goals_share",
    "assists_share",
    "raw_expected_points",
    "expected_points",
)
_COMPONENT_RECEIPT_ATTRS = ("phase_receipt_json", "phase_receipt_sha256")
_WEEKLY_RECEIPT_ATTRS = ("phase_weekly_receipt_json", "phase_weekly_receipt_sha256")


def _identity(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or not 0 < int(value) <= 2**63 - 1
    ):
        raise ValueError("Phase application requires a positive persistent integer identity.")
    return int(value)


def _canonical(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            raise ValueError("A phase frame timestamp must have its UTC identity.")
        return normalize_utc_timestamp(value.isoformat(), label="frame timestamp")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("A phase receipt cannot carry nonfinite frame values.")
        return number
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("A phase receipt dictionary needs text keys.")
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    raise ValueError("A phase receipt has an unsupported value type.")


def _json(value: object) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _frame_sha(frame: pd.DataFrame, *, keys: Sequence[str]) -> str:
    if frame.columns.duplicated().any() or any(not isinstance(name, str) for name in frame.columns):
        raise ValueError("A phase frame has ambiguous columns.")
    ordered = frame.sort_values(list(keys), kind="stable")
    return _sha(_json({"columns": list(ordered.columns), "records": ordered.to_dict("records")}))


def _attributes_sha(frame: pd.DataFrame, *, reserved: Sequence[str] = ()) -> str:
    return _sha(_json({key: value for key, value in frame.attrs.items() if key not in reserved}))


def _close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=1e-10, abs_tol=1e-12)


def _in_minute_bin(minutes: float, bin_index: int) -> bool:
    if bin_index == 0:
        return minutes == 0
    if bin_index == 1:
        return 0 < minutes < 60
    if bin_index == 2:
        return 60 <= minutes < 90
    return 90 <= minutes <= 120


def _raw_points(frame: pd.DataFrame, season: str) -> np.ndarray[Any, np.dtype[np.float64]]:
    goal = frame.position.map(
        {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    ).to_numpy(float)
    clean = frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
    return np.asarray(
        frame.appearance_probability
        + frame.p60
        + goal * frame.goals
        + 3 * frame.assists
        + clean * frame.clean_sheet_probability
        + (2 * frame.defcon_probability if season >= "2025-26" else 0)
        + frame.appearance_probability * frame.residual_if_appearance,
        dtype=float,
    )


def _native(frame: pd.DataFrame, *, season: str) -> str:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("A complete nonempty native fixture frame is required.")
    if not set((*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, "model_version", "decision_at")) <= set(
        frame
    ):
        raise ValueError("Native phase inputs lack fixture identity or scoring components.")
    if frame.columns.duplicated().any() or frame.model_version.nunique() != 1:
        raise ValueError("Native phase inputs have ambiguous columns or model versions.")
    version = str(frame.model_version.iloc[0])
    if version not in _NATIVE_VERSIONS:
        raise ValueError("Phase replacement requires native pre-eligibility components.")
    if "availability_multiplier" in frame:
        values = frame.availability_multiplier
        if any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or value != 1
            for value in values
        ):
            raise ValueError("Phase replacement refuses already-applied fixture availability.")
    if (
        "availability_application" in frame.attrs
        and frame.attrs["availability_application"] != "not_applied"
    ):
        raise ValueError("Phase replacement requires explicitly unapplied native availability.")
    for name in ("GW", "fixture", "club", "opponent", "player_code"):
        for value in frame[name]:
            _identity(value)
    if (frame.GW > 38).any():
        raise ValueError("A native phase frame names an invalid gameweek.")
    for kickoff in frame.kickoff:
        normalize_utc_timestamp(pd.Timestamp(kickoff).isoformat(), label="native kickoff")
    for decision, kickoff in zip(frame.decision_at, frame.kickoff, strict=True):
        decision_instant = as_instant(
            normalize_utc_timestamp(pd.Timestamp(decision).isoformat(), label="native decision_at")
        )
        kickoff_instant = as_instant(
            normalize_utc_timestamp(pd.Timestamp(kickoff).isoformat(), label="native kickoff")
        )
        if decision_instant > kickoff_instant:
            raise ValueError("The native phase decision follows kickoff.")
    component_rows(frame, model_version=version, players=set(frame.player_code))
    bins = frame[[f"minute_probability_{b}" for b in range(4)]].to_numpy(float)
    minutes = frame[[f"minute_value_{b}" for b in range(4)]].to_numpy(float)
    if (
        not np.allclose(frame.appearance_probability, 1 - bins[:, 0], rtol=1e-10, atol=1e-12)
        or not np.allclose(frame.p60, bins[:, 2:].sum(axis=1), rtol=1e-10, atol=1e-12)
        or not np.allclose(
            frame.expected_minutes, (bins * minutes).sum(axis=1), rtol=1e-10, atol=1e-12
        )
    ):
        raise ValueError("The native phase frame has inconsistent minute marginals.")
    if (
        (minutes[:, 0] != 0).any()
        or (minutes[:, 1] < 0).any()
        or (minutes[:, 1] >= 60).any()
        or (minutes[:, 2] < 60).any()
        or (minutes[:, 2] >= 90).any()
        or (minutes[:, 3] < 90).any()
    ):
        raise ValueError("The native phase frame has invalid minute bin supports.")
    if not np.allclose(
        frame.raw_expected_points, _raw_points(frame, season), rtol=1e-10, atol=1e-12
    ):
        raise ValueError("The native phase frame has inconsistent scoring algebra.")
    if (
        (
            frame.loc[
                frame.appearance_probability.eq(0),
                ["clean_sheet_probability", "defcon_probability"],
            ]
            != 0
        )
        .any()
        .any()
    ):
        raise ValueError("An absent native player cannot retain appearance scoring events.")
    for _, side in frame.groupby(["fixture", "club"], sort=True):
        positive = side.expected_minutes > 0
        for head in ("goals", "assists"):
            shares = side[head + "_share"].to_numpy(float)
            if (
                not _close(math.fsum(shares), float(positive.any()))
                or (side.loc[~positive, head] != 0).any()
                or (side.loc[~positive, head + "_share"] != 0).any()
            ):
                raise ValueError("Native attacking shares disagree with positive minute exposure.")
            mass = math.fsum(side[head].to_numpy(float))
            if not np.allclose(side[head], mass * shares, rtol=1e-10, atol=1e-12):
                raise ValueError("Native attacking counts disagree with their club shares.")
            if mass > float(side.team_goal_rate.iloc[0]) + 1e-12:
                raise ValueError("Native credited attacking mass exceeds physical club goals.")
    return version


def _bind_projection(side: pd.DataFrame, projection: PhaseProjection, *, cutoff: str) -> None:
    validate_projection(projection, model_cutoff=cutoff)
    for field, expected_identity in (
        ("GW", projection.gameweek),
        ("fixture", projection.fixture),
        ("club", projection.club),
        ("opponent", projection.opponent),
        ("home", int(projection.home)),
    ):
        if not side[field].eq(expected_identity).all():
            raise ValueError("A phase projection names another native fixture context.")
    kickoff = as_instant(normalize_utc_timestamp(projection.kickoff, label="projection kickoff"))
    if any(
        as_instant(normalize_utc_timestamp(pd.Timestamp(value).isoformat(), label="kickoff"))
        != kickoff
        for value in side.kickoff
    ):
        raise ValueError("A phase projection has another native kickoff.")
    decision = as_instant(
        normalize_utc_timestamp(projection.decision_at, label="projection decision_at")
    )
    if any(
        as_instant(
            normalize_utc_timestamp(pd.Timestamp(value).isoformat(), label="native decision_at")
        )
        != decision
        for value in side.decision_at
    ):
        raise ValueError("A phase projection has another native decision cutoff.")
    roster = side.set_index("player_code")
    players = {p.player_code: p for p in projection.states[0].players}
    if set(players) != set(roster.index):
        raise ValueError("Phase allocation must precede selection over the complete club roster.")
    for code, player in players.items():
        row = cast("pd.Series[Any]", roster.loc[code])
        if row.position != player.position:
            raise ValueError("A phase projection changed the native FPL scoring position.")
        by_state = [
            (s.weight, next(p.minutes for p in s.players if p.player_code == code))
            for s in projection.states
        ]
        expected = math.fsum(weight * minutes for weight, minutes in by_state)
        q = math.fsum(weight for weight, minutes in by_state if minutes > 0)
        p60 = math.fsum(weight for weight, minutes in by_state if minutes >= 60)
        if (
            not _close(expected, float(row.expected_minutes))
            or not _close(q, float(row.appearance_probability))
            or not _close(p60, float(row.p60))
        ):
            raise ValueError(
                "Projected phase participation disagrees with retained native marginals."
            )
        for b in range(4):
            probability = math.fsum(
                weight for weight, minutes in by_state if _in_minute_bin(minutes, b)
            )
            weighted = math.fsum(
                weight * minutes for weight, minutes in by_state if _in_minute_bin(minutes, b)
            )
            if not _close(probability, float(row[f"minute_probability_{b}"])) or not _close(
                weighted, float(row[f"minute_probability_{b}"]) * float(row[f"minute_value_{b}"])
            ):
                raise ValueError(
                    "Projected phase minute bins disagree with retained native support."
                )
    for head, state_field, weight_field in (
        ("goals", "goal_mass", "goal_weight90"),
        ("assists", "assist_mass", "assist_weight90"),
    ):
        if not _close(
            math.fsum(s.weight * getattr(s, state_field) for s in projection.states),
            math.fsum(side[head].to_numpy(float)),
        ):
            raise ValueError("Projected phase mass does not conserve the native full-club head.")
        weights = {
            code: getattr(player, weight_field)
            * float(cast("pd.Series[Any]", roster.loc[code]).expected_minutes)
            for code, player in players.items()
        }
        denominator = math.fsum(weights.values())
        if math.fsum(side[head].to_numpy(float)) > 0 and (
            denominator <= 0
            or any(
                not _close(
                    weights[code] / denominator,
                    float(cast(float, roster.loc[code, head + "_share"])),
                )
                for code in players
            )
        ):
            raise ValueError(
                "Causal phase exposure weights do not bind the native allocation basis."
            )
    if not _close(
        math.fsum(s.weight * s.physical_goal_mass for s in projection.states),
        float(side.team_goal_rate.iloc[0]),
    ):
        raise ValueError("Projected physical goal mass differs from the retained native club rate.")


def phase_fixture_components(
    native_components: pd.DataFrame,
    projections: tuple[PhaseProjection, ...],
    model: PhaseDutyModel,
    *,
    season: str,
    enabled: bool = True,
) -> pd.DataFrame:
    """Replace full-club attacking marginals; disabled returns an exact native copy."""
    if type(enabled) is not bool or not isinstance(native_components, pd.DataFrame):
        raise ValueError("The phase switch and native frame must have explicit types.")
    if not enabled:
        return native_components.copy(deep=True)
    if any(key in native_components.attrs for key in _COMPONENT_RECEIPT_ATTRS):
        raise ValueError("Native inputs cannot already carry a phase allocation receipt.")
    native_attributes_sha = _attributes_sha(native_components)
    version = _native(native_components, season=season)
    if not isinstance(model, PhaseDutyModel) or type(projections) is not tuple or not projections:
        raise ValueError(
            "An explicit fitted phase model and complete immutable projections are required."
        )
    if season == "2025-26":
        raise ValueError("The protected season is excluded from phase applications.")
    keys = {
        (int(row["fixture"]), int(row["club"]))
        for row in native_components[["fixture", "club"]].drop_duplicates().to_dict("records")
    }
    by_key = {}
    for projection in projections:
        if not isinstance(projection, PhaseProjection) or projection.season != season:
            raise ValueError("The phase projection season identity differs.")
        key = (projection.fixture, projection.club)
        if key in by_key:
            raise ValueError("The phase application repeats a club-fixture projection.")
        by_key[key] = projection
    if set(by_key) != keys:
        raise ValueError("Phase projections omit or invent native club-fixture sides.")
    cutoff = model.metadata.cutoff
    for key, projection in by_key.items():
        side = native_components.loc[
            native_components.fixture.eq(key[0]) & native_components.club.eq(key[1])
        ]
        _bind_projection(side, projection, cutoff=cutoff)
    # Every predecision GW uses one agreed deadline across all clubs/fixtures.
    for week in set(native_components.GW):
        deadlines = {
            as_instant(normalize_utc_timestamp(p.decision_at, label="phase decision_at"))
            for p in projections
            if p.gameweek == week
        }
        if len(deadlines) != 1:
            raise ValueError("The phase fixture sides disagree on their gameweek decision cutoff.")
    result = native_components.copy(deep=True)
    allocations: list[PhaseAllocation] = []
    for key in sorted(by_key):
        allocation = model.predict(by_key[key])
        if (
            allocation.projection_sha256 != projection_digest(by_key[key])
            or allocation.model_version != MODEL_VERSION
            or allocation.feature_version != FEATURE_VERSION
        ):
            raise ValueError("A phase allocation lacks its exact projected/model receipt.")
        allocations.append(allocation)
        side_mask = result.fixture.eq(key[0]) & result.club.eq(key[1])
        by_player = {p.player_code: p for p in allocation.players}
        if set(by_player) != set(result.loc[side_mask, "player_code"]):
            raise ValueError("A phase allocation does not cover the full native club roster.")
        for head, mass in (
            ("goals", allocation.total_goals),
            ("assists", allocation.total_assists),
        ):
            result.loc[side_mask, head] = (
                result.loc[side_mask, "player_code"]
                .map({code: getattr(player, head) for code, player in by_player.items()})
                .to_numpy(float)
            )
            if mass > 0:
                result.loc[side_mask, head + "_share"] = (
                    result.loc[side_mask, head].to_numpy(float) / mass
                )
            # Zero mass keeps the native normalized allocation distribution.
    result["raw_expected_points"] = _raw_points(result, season)
    result["expected_points"] = np.maximum(result.raw_expected_points, 0)
    result["native_model_version"] = version
    result["model_version"] = PHASE_COMPONENT_VERSION
    invariant = [
        c for c in native_components.columns if c not in (*_SCORED_COLUMNS, "model_version")
    ]
    pd.testing.assert_frame_equal(native_components[invariant], result[invariant], check_exact=True)
    _native(result.assign(model_version=version), season=season)
    receipt = {
        "contract_version": PHASE_COMPONENT_VERSION,
        "season": season,
        "native_model_version": version,
        "native_frame_sha256": _frame_sha(native_components, keys=("fixture", "player_code")),
        "native_attributes_sha256": native_attributes_sha,
        "projection_sha256": [projection_digest(by_key[key]) for key in sorted(by_key)],
        "projections": [asdict(by_key[key]) for key in sorted(by_key)],
        "allocations": [asdict(allocation) for allocation in allocations],
        "output_frame_sha256": _frame_sha(result, keys=("fixture", "player_code")),
    }
    encoded = _json(receipt)
    result.attrs = {
        **deepcopy(native_components.attrs),
        "phase_receipt_json": encoded,
        "phase_receipt_sha256": _sha(encoded),
    }
    return result


def _component_receipt(components: pd.DataFrame) -> dict[str, Any]:
    encoded = components.attrs.get("phase_receipt_json")
    if not isinstance(encoded, str) or _sha(encoded) != components.attrs.get(
        "phase_receipt_sha256"
    ):
        raise ValueError("Private phase components lack their unchanged canonical receipt.")
    document = json.loads(encoded)
    if not isinstance(document, dict) or _json(document) != encoded:
        raise ValueError("The private phase component receipt is not canonical.")
    if document.get("contract_version") != PHASE_COMPONENT_VERSION or document.get(
        "output_frame_sha256"
    ) != _frame_sha(components, keys=("fixture", "player_code")):
        raise ValueError("Private phase components changed after allocation.")
    if document.get("native_attributes_sha256") != _attributes_sha(
        components, reserved=_COMPONENT_RECEIPT_ATTRS
    ):
        raise ValueError("Private phase component resources or native metadata changed.")
    if set(components.model_version) != {PHASE_COMPONENT_VERSION} or set(
        components.native_model_version
    ) != {document["native_model_version"]}:
        raise ValueError("Private phase components changed their model identity.")
    _native(
        components.assign(model_version=document["native_model_version"]), season=document["season"]
    )
    return document


def _calendar_rows(calendar: pd.DataFrame) -> list[dict[str, Any]]:
    if (
        not isinstance(calendar, pd.DataFrame)
        or not set(_CALENDAR) <= set(calendar)
        or calendar.columns.duplicated().any()
    ):
        raise ValueError("A phase weekly forecast requires the complete paired fixture calendar.")
    if calendar.duplicated(["fixture", "club"]).any():
        raise ValueError("The phase calendar repeats a fixture side.")
    rows: list[dict[str, Any]] = []
    for raw_row in calendar.loc[:, list(_CALENDAR)].to_dict("records"):
        row: dict[str, Any] = {str(key): value for key, value in raw_row.items()}
        for field in ("GW", "fixture", "club", "opponent"):
            _identity(row[field])
        if row["GW"] > 38 or row["club"] == row["opponent"] or row["home"] not in (0, 1):
            raise ValueError("The phase calendar has invalid fixture context.")
        row["kickoff"] = normalize_utc_timestamp(
            pd.Timestamp(row["kickoff"]).isoformat(), label="calendar kickoff"
        )
        row["decision_at"] = normalize_utc_timestamp(
            row["decision_at"], label="calendar decision_at"
        )
        if as_instant(row["decision_at"]) > as_instant(row["kickoff"]):
            raise ValueError("A phase calendar decision follows kickoff.")
        rows.append(row)
    for fixture in {row["fixture"] for row in rows}:
        pair = [row for row in rows if row["fixture"] == fixture]
        if (
            len(pair) != 2
            or {row["home"] for row in pair} != {0, 1}
            or pair[0]["club"] != pair[1]["opponent"]
            or pair[1]["club"] != pair[0]["opponent"]
            or any(pair[0][name] != pair[1][name] for name in ("GW", "kickoff", "decision_at"))
        ):
            raise ValueError("A phase calendar lacks exactly two mutually consistent sides.")
    return rows


def phase_weekly_forecast(
    roster: pd.DataFrame,
    components: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    gameweek: int,
    eligibility: Mapping[int, float],
) -> pd.DataFrame:
    """Aggregate clipped fixture points, then apply one player-week eligibility."""
    gameweek = _identity(gameweek)
    if (
        gameweek > 38
        or not isinstance(roster, pd.DataFrame)
        or roster.empty
        or not {"player_id", "position", "team_id", "club_code"} <= set(roster)
    ):
        raise ValueError("A phase weekly forecast requires the native roster and requested week.")
    if roster.columns.duplicated().any() or roster.player_id.duplicated().any():
        raise ValueError("A phase weekly roster has ambiguous identities.")
    if any(key in roster.attrs for key in _WEEKLY_RECEIPT_ATTRS):
        raise ValueError("A native roster cannot already carry a phase weekly receipt.")
    native_roster_attributes_sha = _attributes_sha(roster)
    for field in ("team_id", "club_code"):
        for value in roster[field]:
            _identity(value)
    if (roster.groupby("team_id").club_code.nunique() != 1).any() or (
        roster.groupby("club_code").team_id.nunique() != 1
    ).any():
        raise ValueError("Native team identities must map one to one to persistent club codes.")
    codes = {_identity(code) for code in roster.player_id}
    if (
        not isinstance(eligibility, Mapping)
        or any(isinstance(code, bool) or not isinstance(code, Integral) for code in eligibility)
        or set(eligibility) != codes
    ):
        raise ValueError("Eligibility must cover exactly the requested persistent player roster.")
    for value in eligibility.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError("Weekly eligibility must be explicit finite values in [0,1].")
    receipt = _component_receipt(components)
    rows = _calendar_rows(calendar)
    if not any(row["GW"] == gameweek for row in rows):
        raise ValueError("A missing requested calendar week is not a proved blank gameweek.")
    projection_by_side = {(p["fixture"], p["club"]): p for p in receipt["projections"]}
    if {(row["fixture"], row["club"]) for row in rows} != set(projection_by_side):
        raise ValueError("The phase calendar and allocation receipt cover different fixture sides.")
    for row in rows:
        projected = projection_by_side[row["fixture"], row["club"]]
        fields = {
            "GW": "gameweek",
            "fixture": "fixture",
            "club": "club",
            "opponent": "opponent",
            "home": "home",
            "kickoff": "kickoff",
            "decision_at": "decision_at",
        }
        for field, key in fields.items():
            value = projected[key]
            if field in ("kickoff", "decision_at"):
                value = normalize_utc_timestamp(value, label=field)
            if row[field] != value:
                raise ValueError(
                    "The phase calendar changed a recorded decision or fixture identity."
                )
    result = roster.copy(deep=True)
    points, chance, count = [], [], []
    for player in result.to_dict("records"):
        code = _identity(player["player_id"])
        club = _identity(player["club_code"])
        matches = [row for row in rows if row["GW"] == gameweek and row["club"] == club]
        actual = components.loc[components.GW.eq(gameweek) & components.player_code.eq(code)]
        if (
            set(actual.fixture) != {row["fixture"] for row in matches}
            or not actual.club.eq(club).all()
            or not actual.position.eq(player["position"]).all()
        ):
            raise ValueError("Missing player fixture coverage cannot become a blank gameweek.")
        if not matches and club not in {int(p["club"]) for p in receipt["projections"]}:
            raise ValueError("An unknown roster club cannot be called a blank gameweek.")
        if not matches:
            # A prior/future captured side proves this player's club membership.
            known = components.loc[components.player_code.eq(code)]
            if (
                known.empty
                or not known.club.eq(club).all()
                or not known.position.eq(player["position"]).all()
            ):
                raise ValueError("A blank player lacks its immutable captured identity evidence.")
        multiplier = float(eligibility[code])
        points.append(multiplier * math.fsum(actual.expected_points.to_numpy(float)))
        chance.append(
            multiplier * (1 - math.prod(1 - float(q) for q in actual.appearance_probability))
        )
        count.append(len(actual))
    result["expected_points"] = points
    result["appearance_probability"] = chance
    result["fixture_count"] = count
    result["gameweek"] = gameweek
    encoded = _json(
        {
            "contract_version": PHASE_WEEKLY_VERSION,
            "gameweek": gameweek,
            "components_receipt_sha256": components.attrs["phase_receipt_sha256"],
            "native_roster_attributes_sha256": native_roster_attributes_sha,
            "calendar": rows,
            "eligibility": [[code, float(eligibility[code])] for code in sorted(codes)],
            "output_frame_sha256": _frame_sha(result, keys=("player_id",)),
        }
    )
    result.attrs = {
        **deepcopy(roster.attrs),
        "phase_weekly_receipt_json": encoded,
        "phase_weekly_receipt_sha256": _sha(encoded),
    }
    return result


def phase_fixed_fifteen_decision(
    weekly: pd.DataFrame,
    starting_xi: Sequence[object],
    ordered_bench: Sequence[object],
    captain_id: object,
    vice_captain_id: object,
    *,
    chip: str | None = None,
    hit_points: float = 0,
    max_evaluations: int = 128,
    locked_first: bool = False,
) -> ExpectedLineupSearchResult:
    """Optimize roles on the same fifteen without changing resource decisions."""
    if (
        not isinstance(weekly, pd.DataFrame)
        or len(weekly) != 15
        or not {"player_id", "position", "team_id", "club_code"} <= set(weekly)
    ):
        raise ValueError("The private phase decision requires one fixed legal fifteen.")
    encoded = weekly.attrs.get("phase_weekly_receipt_json")
    if not isinstance(encoded, str) or _sha(encoded) != weekly.attrs.get(
        "phase_weekly_receipt_sha256"
    ):
        raise ValueError("A private phase decision lacks its weekly input receipt.")
    receipt = json.loads(encoded)
    if (
        not isinstance(receipt, dict)
        or _json(receipt) != encoded
        or receipt.get("contract_version") != PHASE_WEEKLY_VERSION
        or receipt.get("output_frame_sha256") != _frame_sha(weekly, keys=("player_id",))
    ):
        raise ValueError("The private phase weekly forecast changed after aggregation.")
    if receipt.get("native_roster_attributes_sha256") != _attributes_sha(
        weekly, reserved=_WEEKLY_RECEIPT_ATTRS
    ):
        raise ValueError("The private phase weekly resources or native metadata changed.")
    if (
        weekly.player_id.duplicated().any()
        or weekly.position.value_counts().to_dict() != {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
        or (weekly.groupby("team_id").size() > 3).any()
        or (weekly.groupby("club_code").size() > 3).any()
    ):
        raise ValueError("The private phase fifteen violates native squad constraints.")
    before = _frame_sha(weekly, keys=("player_id",))
    attributes_before = _attributes_sha(weekly)
    result = improve_expected_lineup(
        weekly,
        starting_xi,
        ordered_bench,
        captain_id,
        vice_captain_id,
        chip=chip,
        hit_points=hit_points,
        max_evaluations=max_evaluations,
        locked_first=locked_first,
    )
    if (
        _frame_sha(weekly, keys=("player_id",)) != before
        or _attributes_sha(weekly) != attributes_before
    ):
        raise ValueError("A phase role search changed the native roster or resources.")
    return result
