"""Explicit private unit experiment over retained conditional fixture components.

No caller, public artifact, default model, network access or filesystem side effect
is installed here. Unit states and native player minutes remain independent in
this version. Availability is applied only after conditional fixture aggregation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

from squadopt.features.football_unit_inputs import (
    UNIT_INPUT_VERSION,
    UNIT_PREFIX_CLOCK_VERSION,
    NumericAttributeSpec,
    SourceRecord,
    UnitExposureClock,
    UnitHistoricalReplay,
    scope,
    utc_time,
)
from squadopt.live.minute_evidence import COMPONENT_COLUMNS, IDENTITY_COLUMNS, _validate_components
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_unit_strength import (
    UNIT_ALL_UNOBSERVED_SEMANTICS,
    UNIT_FEATURE_VERSION,
    UNIT_MODEL_VERSION,
    UNIT_REPLAY_FIT_VERSION,
    UNIT_RESIDUAL_MISSINGNESS_SEMANTICS,
    UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION,
    UNIT_SOURCE_MISSINGNESS_MODEL_VERSION,
    UNIT_SOURCE_MISSINGNESS_POLICY,
    UnitStrengthResult,
    source_attribute_groups,
    source_missingness_base_columns,
)
from squadopt.scenarios.expected_lineup import ExpectedLineupSearchResult, improve_expected_lineup

UNIT_COMPONENT_VERSION = "private_unit_state_fixture_components_v1"
UNIT_WEEKLY_VERSION = "private_unit_state_weekly_v1"


def _positive_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError("Unit experiment identities must be positive integers.")
    return int(value)


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError("Unit experiment numeric inputs must be finite real values.")
    return float(value)


def _same(actual: ArrayLike, expected: ArrayLike) -> None:
    if not np.allclose(actual, expected, rtol=1e-10, atol=1e-10):
        raise ValueError("Unit experiment receipts do not match their retained component basis.")


def _replay_fit_receipts(
    metadata: Mapping[str, object],
    training_cutoff: datetime,
    sources: tuple[Any, ...],
    *,
    target_season: str,
    target_gameweek: int,
) -> None:
    contract = metadata.get("fit_contract")
    replay_keys = {
        "training_exposure_clock",
        "training_selection",
        "training_replay_receipts",
        "training_exposure_receipts",
        "exposure_semantics",
        "projection_extrapolation",
        "fm_game_vintage",
        "fm_effective_semantics",
    }
    if contract is None:
        if (replay_keys | {"allow_released_2025_26"}) & metadata.keys():
            raise ValueError("Replay evidence requires its explicit fitting contract.")
        return
    released = metadata.get("allow_released_2025_26")
    if type(released) is not bool:
        raise ValueError("Unit result requires its explicit released-season policy.")
    if contract == "football_unit_explicit_release_fit_v1":
        if released is not True or replay_keys & metadata.keys():
            raise ValueError("Explicit release contract has inconsistent replay evidence.")
        return
    if (
        contract != UNIT_REPLAY_FIT_VERSION
        or metadata.get("training_exposure_clock") != UNIT_PREFIX_CLOCK_VERSION
        or metadata.get("fm_game_vintage") != "unknown"
        or not replay_keys <= metadata.keys()
    ):
        raise ValueError("Unit result requires its declared replay and quantized clock contract.")
    replays, exposures = (
        metadata.get("training_replay_receipts"),
        metadata.get("training_exposure_receipts"),
    )
    if (
        not isinstance(replays, tuple)
        or not isinstance(exposures, tuple)
        or not replays
        or len(replays) != len(exposures)
        or len(replays) != len(sources)
        or metadata.get("training_rows") != 2 * len(replays)
    ):
        raise ValueError(
            "Unit replay result requires one source and exposure receipt per interval."
        )

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(dict(items)) != len(items):
            raise ValueError("Duplicate replay receipt fields are refused.")
        return dict(items)

    def document(value: object) -> dict[str, Any]:
        if not isinstance(value, str):
            raise ValueError("Unit replay receipt must be immutable JSON text.")
        parsed = json.loads(value, object_pairs_hook=pairs)
        if not isinstance(parsed, dict):
            raise ValueError("Unit replay receipt must be an object.")
        return parsed

    def instant(value: Any) -> datetime:
        return utc_time(datetime.fromisoformat(value), "replay receipt time")

    seen = set()
    spans: dict[tuple[str, int], list[tuple[float, float]]] = {}
    week_cutoffs: dict[tuple[str, int], datetime] = {}
    fixture_bases: dict[tuple[str, int], tuple[object, ...]] = {}
    try:
        for replay_text, exposure_text, group in zip(replays, exposures, sources, strict=True):
            envelope, exposure = document(replay_text), document(exposure_text)
            if set(envelope) != {
                "replay",
                "decision_cutoff",
                "baseline_source_id",
                "reference_source_id",
            }:
                raise ValueError("Unit replay envelope fields are invalid.")
            raw = envelope["replay"]
            replay = UnitHistoricalReplay(
                **{
                    **raw,
                    **{
                        key: instant(raw[key])
                        for key in (
                            "recorded_at",
                            "retrieved_at",
                            "feature_cutoff",
                            "latest_history_kickoff",
                            "generated_at",
                        )
                    },
                    "source_hashes": tuple(tuple(item) for item in raw["source_hashes"]),
                }
            )
            records = {
                row[0]: SourceRecord(
                    row[0],
                    row[1],
                    row[3],
                    row[2],
                    row[4],
                    instant(row[5]),
                    instant(row[6]),
                    instant(row[7]),
                    instant(row[8]),
                    row[9],
                    True,
                )
                for row in group
            }
            decision = instant(envelope["decision_cutoff"])
            replay.validate_sources(
                records,
                decision=decision,
                baseline_source_id=envelope["baseline_source_id"],
                reference_source_id=envelope["reference_source_id"],
            )
            if replay.generated_at >= training_cutoff:
                raise ValueError("Replayed features were generated after fitting.")
            if set(exposure) != {
                "clock",
                "season",
                "gameweek",
                "fixture_id",
                "start_minute",
                "minutes",
                "kickoff",
                "outcome_source",
                "outcome_available_at",
            }:
                raise ValueError("Unit exposure envelope fields are invalid.")
            clock = UnitExposureClock(**exposure["clock"])
            source_raw = exposure["outcome_source"]
            source = SourceRecord(
                **{
                    **source_raw,
                    **{
                        key: instant(source_raw[key])
                        for key in ("published_at", "captured_at", "effective_at", "valid_until")
                    },
                }
            )
            available, kickoff = (
                instant(exposure["outcome_available_at"]),
                instant(exposure["kickoff"]),
            )
            source.available_at(available)
            start, minutes = _finite(exposure["start_minute"]), _finite(exposure["minutes"])
            scope(exposure["season"], exposure["gameweek"], exposure["fixture_id"])
            season, gameweek = exposure["season"], exposure["gameweek"]
            identity = clock.source_sha256, clock.interval_id
            if (
                clock.source_sha256 != source.sha256
                or identity in seen
                or not start.is_integer()
                or not minutes.is_integer()
                or start < 0
                or minutes <= 0
                or start + minutes > 40
                or not decision < kickoff
                or available < kickoff + timedelta(hours=3)
                or available >= training_cutoff
                or (exposure["season"] == "2025-26" and released is not True)
                or season > target_season
                or (season == target_season and gameweek >= target_gameweek)
            ):
                raise ValueError(
                    "Unit result exposure disagrees with its source or fitting policy."
                )
            seen.add(identity)
            week_key = season, gameweek
            if week_cutoffs.setdefault(week_key, decision) != decision:
                raise ValueError(
                    "Unit replay fixtures in one gameweek require one decision cutoff."
                )
            fixture_key = season, exposure["fixture_id"]
            basis = (gameweek, decision, kickoff, replay_text, group)
            if fixture_bases.setdefault(fixture_key, basis) != basis:
                raise ValueError("Unit replay fixture intervals must retain one historical basis.")
            end = start + minutes
            for previous in spans.setdefault(fixture_key, []):
                if max(start, previous[0]) < min(end, previous[1]):
                    raise ValueError("Unit replay exposure intervals overlap.")
            spans[fixture_key].append((start, end))
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Malformed unit replay or exposure receipt.") from error


def _missingness_feature_receipt(result: UnitStrengthResult) -> None:
    metadata = result.metadata
    keys = {
        "missingness_policy",
        "source_attribute_groups",
        "all_unobserved_semantics",
        "residual_missingness_semantics",
    }
    if result.model_version == UNIT_MODEL_VERSION:
        if (
            metadata.get("feature_version") != UNIT_FEATURE_VERSION
            or keys & metadata.keys()
            or any(name.endswith(":all_attributes_unobserved") for name in result.feature_contract)
        ):
            raise ValueError("Legacy unit results cannot claim source missingness features.")
        return
    if (
        result.model_version != UNIT_SOURCE_MISSINGNESS_MODEL_VERSION
        or metadata.get("feature_version") != UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION
        or metadata.get("missingness_policy") != UNIT_SOURCE_MISSINGNESS_POLICY
        or metadata.get("all_unobserved_semantics") != UNIT_ALL_UNOBSERVED_SEMANTICS
        or metadata.get("residual_missingness_semantics") != UNIT_RESIDUAL_MISSINGNESS_SEMANTICS
        or metadata.get("regularization") != 0.1
    ):
        raise ValueError("Unit source missingness requires its exact version and policy.")
    vocabulary, contract = metadata.get("player_vocabulary"), metadata.get("attribute_contract")
    if (
        not isinstance(vocabulary, tuple)
        or not vocabulary
        or tuple(sorted({_positive_id(x) for x in vocabulary})) != vocabulary
        or not isinstance(contract, tuple)
    ):
        raise ValueError("Source missingness requires its fitted identity and attribute contract.")
    specs = []
    for item in contract:
        if (
            not isinstance(item, tuple)
            or len(item) != 8
            or not isinstance(item[6], str)
            or not item[6]
            or item[7] not in ("synthetic", "provider", "fm")
        ):
            raise ValueError("Malformed source attribute contract.")
        source_id, name, minimum, maximum, unit, definition, _, _ = item
        specs.append(NumericAttributeSpec(name, source_id, minimum, maximum, unit, definition))
    if len({(s.source_id, s.name) for s in specs}) != len(specs):
        raise ValueError("Source attribute contract contains duplicated definitions.")
    attributes = tuple(specs)
    groups = tuple(
        (identity, tuple(spec.name for spec in group))
        for identity, group in source_attribute_groups(attributes)
    )
    base = source_missingness_base_columns(vocabulary, attributes)
    expected = base + tuple(f"home_interaction:{column}" for column in base)
    if metadata.get("source_attribute_groups") != groups or result.feature_contract != expected:
        raise ValueError("Source missingness features disagree with their declared source groups.")


def _result_receipt(result: UnitStrengthResult) -> str:
    metadata = result.metadata
    if (
        not isinstance(metadata, MappingProxyType)
        or metadata.get("input_version") != UNIT_INPUT_VERSION
        or not result.feature_contract
        or len(set(result.feature_contract)) != len(result.feature_contract)
        or any(not isinstance(x, str) or not x for x in result.feature_contract)
        or metadata.get("feature_columns") != result.feature_contract
    ):
        raise ValueError("Unit results require their immutable declared feature contract.")
    _missingness_feature_receipt(result)
    try:
        training_cutoff = datetime.fromisoformat(str(metadata["training_cutoff"]))
    except (KeyError, ValueError) as error:
        raise ValueError("Unit result requires its fitting cutoff receipt.") from error
    if training_cutoff.tzinfo is None or training_cutoff > result.decision_cutoff:
        raise ValueError("Unit fitting must be known by the common decision cutoff.")
    _positive_id(metadata.get("training_rows"))
    for name in ("training_catalog_sha256", "training_observation_sha256"):
        values = metadata.get(name)
        if (
            not isinstance(values, tuple)
            or not values
            or any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}", x) for x in values)
        ):
            raise ValueError("Unit results require their historical source fingerprints.")
    for name in ("projection_catalog_sha256", "projection_sha256"):
        if not isinstance(metadata.get(name), str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(metadata[name])
        ):
            raise ValueError("Unit results require their full projection fingerprints.")
    reference = metadata.get("reference_unit_identity")
    if not isinstance(reference, tuple) or len(reference) != 2:
        raise ValueError("Unit results require the exact paired reference identities.")
    for expected_club, item in zip((result.club, result.opponent), reference, strict=True):
        if not isinstance(item, tuple) or len(item) != 2 or item[0] != expected_club:
            raise ValueError("Reference unit clubs must match result identities.")
        _positive_id(item[0])
        players = item[1]
        if (
            not isinstance(players, tuple)
            or len(players) != 11
            or any(
                not isinstance(p, tuple) or len(p) != 2 or p[1] not in ("GK", "DEF", "MID", "FWD")
                for p in players
            )
        ):
            raise ValueError("Reference units require eleven declared FPL scoring positions.")
        ids = [_positive_id(p[0]) for p in players]
        if len(set(ids)) != 11 or sum(p[1] == "GK" for p in players) != 1:
            raise ValueError("Reference units require distinct players and one keeper.")

    def source_group(value: object, limit: datetime, *, current: bool) -> set[str]:
        if not isinstance(value, tuple) or not value:
            raise ValueError("Unit results require source and rights receipts.")
        identities = set()
        for row in value:
            if (
                not isinstance(row, tuple)
                or len(row) != 10
                or any(not isinstance(x, str) or not x for x in row)
            ):
                raise ValueError("Unit source receipts require their exact declared fields.")
            identity, _, kind, _, digest, published, captured, effective, expiry, rights = row
            if (
                identity in identities
                or kind not in ("synthetic", "provider", "fm")
                or not (re.fullmatch(r"[0-9a-f]{64}", digest))
                or ((kind == "synthetic") != rights.startswith("synthetic:"))
            ):
                raise ValueError("Invalid source identity, provenance or rights receipt.")
            identities.add(identity)
            try:
                times = [
                    datetime.fromisoformat(t) for t in (published, captured, effective, expiry)
                ]
            except ValueError as error:
                raise ValueError("Source receipt timestamps must be ISO dates.") from error
            if (
                any(t.tzinfo is None for t in times)
                or times[0] > times[1]
                or times[2] > times[3]
                or any(t > limit for t in times[:3])
                or (current and times[3] < limit)
            ):
                raise ValueError("Source receipts must be known and effective before decision.")
        return identities

    training_sources = metadata.get("training_source_receipts")
    if not isinstance(training_sources, tuple) or not training_sources:
        raise ValueError("Historical source receipt groups are required.")
    for group in training_sources:
        source_group(group, training_cutoff, current=False)
    _replay_fit_receipts(
        metadata,
        training_cutoff,
        training_sources,
        target_season=result.season,
        target_gameweek=result.gameweek,
    )
    projection_ids = source_group(
        metadata.get("projection_source_receipts"), result.decision_cutoff, current=True
    )
    if result.model_version == UNIT_SOURCE_MISSINGNESS_MODEL_VERSION:
        attribute_contract = metadata["attribute_contract"]
        assert isinstance(attribute_contract, tuple)
        families = {(row[0], row[6], row[7]) for row in attribute_contract}
        for group in (*training_sources, metadata["projection_source_receipts"]):
            assert isinstance(group, tuple)
            actual_families = {(row[0], row[1], row[2]) for row in group}
            if not families <= actual_families:
                raise ValueError("Attribute source families must match every source receipt group.")
    for name in ("baseline_source_id", "reference_source_id", "projection_source_id"):
        if not isinstance(metadata.get(name), str) or not metadata[name]:
            raise ValueError("Unit results require named source families.")
        if metadata[name] not in projection_ids:
            raise ValueError("Named projection sources must exist in their source receipts.")
    payload = {
        "metadata": dict(metadata),
        "fixture": result.fixture_id,
        "season": result.season,
        "gameweek": result.gameweek,
        "decision_cutoff": result.decision_cutoff.isoformat(),
        "kickoff": result.kickoff.isoformat(),
        "club": result.club,
        "opponent": result.opponent,
        "home": result.home,
        "states": [
            (
                s.probability,
                s.own_goal_rate,
                s.opponent_goal_rate,
                [(p.player_id, p.position) for p in s.own.players],
                [(p.player_id, p.position) for p in s.opponent.players],
            )
            for s in result.state_rates
        ],
    }
    if result.model_version == UNIT_SOURCE_MISSINGNESS_MODEL_VERSION:
        payload["model_version"] = result.model_version
    return json.dumps(payload, sort_keys=True, allow_nan=False)


def _component_digest(frame: pd.DataFrame) -> str:
    columns = [*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, "model_version"]
    return hashlib.sha256(
        frame[columns].to_json(orient="split", date_format="iso", double_precision=15).encode()
    ).hexdigest()


def _weekly_digest(frame: pd.DataFrame) -> str:
    provenance = {
        name: frame.attrs.get(name)
        for name in (
            "decision_cutoffs",
            "unit_result_receipts",
            "eligibility_receipt",
            "weekly_version",
        )
    }
    return hashlib.sha256(
        (
            frame.to_json(orient="split", double_precision=15)
            + json.dumps(provenance, sort_keys=True, default=str)
        ).encode()
    ).hexdigest()


def unit_fixture_components(
    baseline: pd.DataFrame, results: Sequence[UnitStrengthResult], *, season: str
) -> pd.DataFrame:
    """Learned club rates, retained player shares and state-integrated clean sheets.

    The private mixture contract is deliberately distinct from v1: exp(-mean rate)
    is not the expectation of exp(-state rate). Native residual, DEFCON and minute
    heads stay fixed. Inputs describe conditional fixtures before eligibility.
    """
    required = {
        "GW",
        "fixture",
        "kickoff",
        "club",
        "opponent",
        "home",
        "player_code",
        "position",
        "model_version",
    }
    if not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError("An explicit season identity is required.")
    if baseline.empty or not required <= set(baseline):
        raise ValueError("A complete native fixture component basis is required.")
    if not baseline.model_version.eq(FOOTBALL_MODEL_VERSION).all():
        raise ValueError("This private adapter requires the retained native v1 basis.")
    out = baseline.copy(deep=True).reset_index(drop=True)
    for name in ("GW", "fixture", "club", "opponent", "player_code"):
        for value in out[name]:
            _positive_id(value)
    if not out.home.isin((0, 1)).all() or any(isinstance(x, bool) for x in out.home):
        raise ValueError("Native home identities must be numeric zero or one.")
    _validate_components(out, season)
    by_fixture = {}
    cutoffs: dict[int, datetime] = {}
    receipts = []
    model_versions = set()
    for result in results:
        if not isinstance(result, UnitStrengthResult) or result.model_version not in (
            UNIT_MODEL_VERSION,
            UNIT_SOURCE_MISSINGNESS_MODEL_VERSION,
        ):
            raise ValueError("An explicitly identified unit-strength result is required.")
        model_versions.add(result.model_version)
        _positive_id(result.fixture_id)
        for identity in (result.gameweek, result.club, result.opponent):
            _positive_id(identity)
        if not isinstance(result.home, bool):
            raise ValueError("A unit result home identity must be boolean.")
        if (
            not isinstance(result.decision_cutoff, datetime)
            or not isinstance(result.kickoff, datetime)
            or result.decision_cutoff.tzinfo is None
            or result.kickoff.tzinfo is None
        ):
            raise ValueError("Unit result times require an explicit timezone.")
        if cutoffs.setdefault(result.gameweek, result.decision_cutoff) != result.decision_cutoff:
            raise ValueError("All fixtures in a gameweek require one common decision cutoff.")
        receipts.append(_result_receipt(result))
        if result.fixture_id in by_fixture:
            raise ValueError("Only one paired unit result per fixture is permitted.")
        by_fixture[result.fixture_id] = result
    if len(model_versions) != 1:
        raise ValueError("One component artifact requires one declared unit model version.")
    if set(by_fixture) != set(out.fixture):
        raise ValueError("Every retained fixture requires exactly one paired unit result.")
    for fixture, rows in out.groupby("fixture", sort=False):
        result = by_fixture[_positive_id(fixture)]
        if (
            result.season != season
            or not rows.GW.eq(result.gameweek).all()
            or set(rows.club) != {result.club, result.opponent}
            or not rows.loc[rows.club.eq(result.club), "home"].eq(int(result.home)).all()
        ):
            raise ValueError("Unit result season, week and opposing identities must agree.")
        if not result.decision_cutoff < result.kickoff:
            raise ValueError("Unit result requires a predecision cutoff.")
        if any(pd.Timestamp(x) != result.kickoff for x in rows.kickoff):
            raise ValueError("Unit result kickoff does not match retained fixtures.")
        if not result.state_rates:
            raise ValueError("Unit results require their complete joint state rates.")
        weights = [_finite(s.probability) for s in result.state_rates]
        if any(x <= 0 for x in weights) or not math.isclose(
            math.fsum(weights), 1, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("Joint unit state weights must have unit mass.")
        for state in result.state_rates:
            if state.own.club != result.club or state.opponent.club != result.opponent:
                raise ValueError("State unit identities must match paired result clubs.")
            if min(_finite(state.own_goal_rate), _finite(state.opponent_goal_rate)) <= 0:
                raise ValueError("Unit state goal rates must be positive.")
            for unit in (state.own, state.opponent):
                positions = dict(
                    zip(
                        rows.loc[rows.club.eq(unit.club), "player_code"],
                        rows.loc[rows.club.eq(unit.club), "position"],
                        strict=True,
                    )
                )
                if any(positions.get(p.player_id) != p.position for p in unit.players):
                    raise ValueError(
                        "Projected unit players must exist in their retained club pool."
                    )
        _same(
            result.own_goal_rate,
            math.fsum(
                w * s.own_goal_rate for w, s in zip(weights, result.state_rates, strict=True)
            ),
        )
        _same(
            result.opponent_goal_rate,
            math.fsum(
                w * s.opponent_goal_rate for w, s in zip(weights, result.state_rates, strict=True)
            ),
        )
        for club, own_rate, opponent_rate, old_rate, old_opponent in (
            (
                result.club,
                result.own_goal_rate,
                result.opponent_goal_rate,
                result.causal_baseline_own_goal_rate,
                result.causal_baseline_opponent_goal_rate,
            ),
            (
                result.opponent,
                result.opponent_goal_rate,
                result.own_goal_rate,
                result.causal_baseline_opponent_goal_rate,
                result.causal_baseline_own_goal_rate,
            ),
        ):
            index = rows.index[rows.club.eq(club)]
            side = out.loc[index]
            if min(_finite(old_rate), _finite(old_opponent)) <= 0:
                raise ValueError("Unit adjustments require positive causal baseline rates.")
            _same(side.team_goal_rate, old_rate)
            _same(side.opponent_goal_rate, old_opponent)
            out.loc[index, "team_goal_rate"] = own_rate
            out.loc[index, "opponent_goal_rate"] = opponent_rate
            for head in ("goals", "assists"):
                out.loc[index, head] = side[head].to_numpy(float) * own_rate / old_rate
            clean = np.zeros(len(side))
            for b in (2, 3):
                means = side[f"minute_value_{b}"].to_numpy(float)
                clean += side[f"minute_probability_{b}"].to_numpy(float) * sum(
                    w
                    * np.exp(
                        -(s.opponent_goal_rate if club == result.club else s.own_goal_rate)
                        * means
                        / 90
                    )
                    for w, s in zip(weights, result.state_rates, strict=True)
                )
            out.loc[index, "clean_sheet_probability"] = clean
    goal = out.position.map(
        {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    ).to_numpy(float)
    clean_weight = out.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
    raw = (
        out.appearance_probability
        + out.p60
        + goal * out.goals
        + 3 * out.assists
        + clean_weight * out.clean_sheet_probability
        + out.appearance_probability * out.residual_if_appearance
    )
    if season >= "2025-26":
        raw = raw + 2 * out.defcon_probability
    out["raw_expected_points"] = raw
    out["expected_points"] = np.maximum(raw, 0)
    if not np.isfinite(out[["goals", "assists", "raw_expected_points"]]).all().all():
        raise ValueError("Adjusted component calculations must remain finite.")
    out["model_version"] = next(iter(model_versions))
    out.attrs["component_version"] = UNIT_COMPONENT_VERSION
    out.attrs["minute_state_relation"] = "retained native minutes independent of unit states"
    out.attrs["decision_cutoffs"] = tuple(sorted(cutoffs.items()))
    out.attrs["unit_result_documents"] = tuple(receipts)
    out.attrs["unit_result_receipts"] = tuple(
        hashlib.sha256(x.encode()).hexdigest() for x in receipts
    )
    out.attrs["component_digest"] = _component_digest(out)
    return out


def unit_weekly_forecast(
    roster: pd.DataFrame,
    components: pd.DataFrame,
    fixture_calendar: pd.DataFrame,
    *,
    gameweek: int,
    eligibility: Mapping[int, float],
) -> pd.DataFrame:
    """Explicit calendar coverage distinguishes blanks from missing forecast rows."""
    _positive_id(gameweek)
    if not {"player_id", "position", "club"} <= set(roster) or roster.player_id.duplicated().any():
        raise ValueError("A unique persistent fixed-roster identity and club are required.")
    for name in ("player_id", "club"):
        for identity in roster[name]:
            _positive_id(identity)
    if components.attrs.get("component_version") != UNIT_COMPONENT_VERSION:
        raise ValueError("Weekly aggregation requires the private unit component contract.")
    cutoffs = components.attrs.get("decision_cutoffs")
    if not isinstance(cutoffs, tuple) or not any(w == gameweek for w, _ in cutoffs):
        raise ValueError("The requested gameweek requires its declared decision cutoff.")
    if not {"GW", "fixture", "club"} <= set(fixture_calendar):
        raise ValueError("A declared paired fixture calendar is required.")
    if fixture_calendar.duplicated(["GW", "fixture", "club"]).any():
        raise ValueError("Fixture calendar side identities must be unique.")
    week = fixture_calendar.loc[fixture_calendar.GW.eq(gameweek)]
    rows = components.loc[components.GW.eq(gameweek)]
    if rows.duplicated(["fixture", "player_code"]).any():
        raise ValueError("Repeated player-fixture component rows are refused.")
    for name in ("GW", "fixture", "club"):
        for identity in fixture_calendar[name]:
            _positive_id(identity)
    if any(group.club.nunique() != 2 for _, group in week.groupby("fixture")):
        raise ValueError("Calendar fixtures require two distinct opposing clubs.")
    for player in roster.itertuples():
        group = rows.loc[rows.player_code.eq(player.player_id)]
        if not group.club.eq(player.club).all() or not group.position.eq(player.position).all():
            raise ValueError("Roster identity and position must match fixture components.")
    for row in rows.itertuples():
        mu, q = _finite(row.expected_points), _finite(row.appearance_probability)
        if mu < 0 or not 0 <= q <= 1 or (q == 0 and mu != 0):
            raise ValueError("Conditional fixture points and participation must be coherent.")
    if set(zip(week.fixture, week.club, strict=True)) != set(
        zip(rows.fixture, rows.club, strict=True)
    ):
        raise ValueError("Calendar and retained component fixture coverage must agree.")
    expected = {
        (_positive_id(p.player_id), _positive_id(f))
        for p in roster.itertuples()
        for f in week.loc[week.club.eq(p.club), "fixture"]
    }
    actual = {
        (_positive_id(r.player_code), _positive_id(r.fixture))
        for r in rows.itertuples()
        if r.player_code in set(roster.player_id)
    }
    if actual != expected:
        raise ValueError("Scheduled roster players require complete player-fixture coverage.")
    documents = components.attrs.get("unit_result_documents")
    if (
        not isinstance(documents, tuple)
        or not documents
        or any(not isinstance(x, str) for x in documents)
    ):
        raise ValueError("Immutable private unit receipt documents are required.")
    try:
        document_cutoffs = tuple(
            sorted(
                {
                    r["gameweek"]: datetime.fromisoformat(r["decision_cutoff"])
                    for r in map(json.loads, documents)
                }.items()
            )
        )
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("Private unit receipt documents changed.") from error
    if (
        not isinstance(documents, tuple)
        or not documents
        or (
            tuple(hashlib.sha256(x.encode()).hexdigest() for x in documents)
            != components.attrs.get("unit_result_receipts")
            or _component_digest(components) != components.attrs.get("component_digest")
            or document_cutoffs != components.attrs.get("decision_cutoffs")
        )
    ):
        raise ValueError("Private components or their immutable result receipts changed.")
    if set(eligibility) != set(roster.player_id):
        raise ValueError("Every roster player requires one explicit weekly eligibility value.")
    for identity in eligibility:
        _positive_id(identity)
    out = roster.copy(deep=True)
    points, chances = [], []
    for player in out.player_id:
        _positive_id(player)
        a = _finite(eligibility[player])
        if not 0 <= a <= 1:
            raise ValueError("Weekly eligibility must lie in [0, 1].")
        group = rows.loc[rows.player_code.eq(player)]
        points.append(a * math.fsum(group.expected_points))
        chances.append(a * (1 - math.prod(1 - x for x in group.appearance_probability)))
    out["gameweek"] = gameweek
    out["expected_points"] = points
    out["appearance_probability"] = chances
    out.attrs["weekly_version"] = UNIT_WEEKLY_VERSION
    out.attrs["decision_cutoffs"] = components.attrs["decision_cutoffs"]
    out.attrs["unit_result_receipts"] = components.attrs["unit_result_receipts"]
    out.attrs["eligibility_receipt"] = tuple(
        sorted((int(p), float(a)) for p, a in eligibility.items())
    )
    out.attrs["weekly_digest"] = _weekly_digest(out)
    return out


def unit_fixed_fifteen_decision(
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
    """Existing bounded role search over one legal frozen fifteen, with no transfers."""
    if weekly.attrs.get("weekly_version") != UNIT_WEEKLY_VERSION:
        raise ValueError("The decision requires explicitly identified unit weekly inputs.")
    if (
        weekly.attrs.get("weekly_digest") != _weekly_digest(weekly)
        or not weekly.attrs.get("unit_result_receipts")
        or not weekly.attrs.get("decision_cutoffs")
    ):
        raise ValueError("Private weekly rows or their provenance changed before role selection.")
    if len(weekly) != 15 or weekly.groupby("club").size().gt(3).any():
        raise ValueError("The frozen fifteen requires at most three players per club.")
    if weekly.position.value_counts().to_dict() != {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}:
        raise ValueError("The frozen fifteen requires its legal position counts.")
    return improve_expected_lineup(
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
