"""Pure fixture composition over retained sources and compact fitted models.

The caller verifies complete weekly laws and source bytes. This module binds their
identities, preserves final minute atoms, and never fits, fetches or clips rates.
Its point XI, score intervals and phase coupling are distinct stated approximations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from functools import partial
from typing import Any, Protocol

from scipy.stats import nbinom

from squadopt.features.football_observed_tactical_inputs import (
    ObservedTacticalProjection,
    ObservedTacticalSide,
)
from squadopt.features.football_observed_tactical_inputs import (
    validate_projection as validate_tactical_projection,
)
from squadopt.features.football_phase_coupling import (
    PhaseMinuteMarginal,
    couple_phase_minutes,
)
from squadopt.features.football_phase_inputs import PhaseDutyCapture, PhaseProjection, PhaseSource
from squadopt.features.football_score_projection import (
    ScoreDurationForecast,
    ScoreNativePlayer,
    project_score_intervals,
)
from squadopt.features.football_score_state_inputs import (
    COMPOSITE_OFFSET_VERSION,
    NATIVE_MODEL_VERSIONS,
    ScoreFixture,
)
from squadopt.features.football_unit_inputs import (
    ClubUnit,
    ProjectedUnitState,
    UnitInputCatalog,
    UnitPlayer,
    UnitProjection,
)
from squadopt.features.football_unit_point import UnitStarterProbability, project_unit_point
from squadopt.prediction.football_components import role_component_record
from squadopt.prediction.football_observed_tactical import ObservedTacticalRecipientSide
from squadopt.prediction.football_phase_serving import PhaseServingModel
from squadopt.prediction.football_score_serving import ScoreServingModel
from squadopt.prediction.football_unit_serving import UnitServingModel

CORE_VERSION = "football_composite_fixture_core_v1"
OUTPUT_MODEL_VERSION = "football_composite_v1"
MAX_NATIVE_BYTES = 2 * 1024 * 1024
_BINS = (0, 1, 2, 3, 1, 2, 3)


class RecipientReceipt(Protocol):
    @property
    def artifact_sha256(self) -> str: ...

    @property
    def original_metadata_sha256(self) -> str: ...


class RecipientResult(Protocol):
    @property
    def home(self) -> ObservedTacticalRecipientSide: ...

    @property
    def away(self) -> ObservedTacticalRecipientSide: ...

    @property
    def projection_sha256(self) -> str: ...

    @property
    def control(self) -> bool: ...

    @property
    def serving_receipt(self) -> RecipientReceipt: ...


class RecipientModel(Protocol):
    """The concrete compact reader is owned by the tactical serving module."""

    @property
    def artifact_sha256(self) -> str: ...

    def predict_recipients(
        self, p: ObservedTacticalProjection, *, control: bool = False
    ) -> RecipientResult: ...


@dataclass(frozen=True)
class FinalMinuteMarginal:
    player_code: int
    probabilities: tuple[float, ...]
    minutes: tuple[float, ...]
    final_week_law_sha256: str


@dataclass(frozen=True)
class CompositeUnitContext:
    season: str
    gameweek: int
    fixture_id: int
    decision_cutoff: datetime
    kickoff: datetime
    captured_at: datetime
    catalog: UnitInputCatalog
    reference_own: ClubUnit
    reference_opponent: ClubUnit
    causal_baseline_own_goal_rate: float
    causal_baseline_opponent_goal_rate: float


@dataclass(frozen=True)
class CompositeScoreContext:
    season: str
    gameweek: int
    fixture_id: int
    decision_at: str
    deadline_at: str
    kickoff: str
    home_club_code: int
    away_club_code: int
    native_home_goals: float
    native_away_goals: float
    clock_version: str
    native_basis_sha256: str
    native_model_version: str
    native_basis_kind: str
    native_basis_fit_cutoff: str
    native_basis_evidence_ref: str
    source_sha256: str
    coverage_evidence_ref: str
    calendar_evidence_ref: str


@dataclass(frozen=True)
class CompositePhaseContext:
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    home: bool
    kickoff: str
    decision_at: str
    duties: PhaseDutyCapture
    source: PhaseSource


@dataclass(frozen=True)
class CompositeFixtureInput:
    native_rows_json: str
    native_basis_sha256: str
    source_manifest_sha256: str
    final_minutes: tuple[FinalMinuteMarginal, ...]
    unit: CompositeUnitContext
    score: CompositeScoreContext
    duration: ScoreDurationForecast
    tactical: ObservedTacticalProjection
    phase: tuple[CompositePhaseContext, CompositePhaseContext]
    generated_at: str


@dataclass(frozen=True)
class CompositeModels:
    unit: UnitServingModel
    score: ScoreServingModel
    tactical: RecipientModel
    phase: PhaseServingModel


@dataclass(frozen=True)
class CompositeStage:
    name: str
    input_sha256: str
    result_sha256: str
    artifact_sha256: str | None
    original_fit_sha256: str | None
    payload_json: str | None


@dataclass(frozen=True)
class CompositeReceipt:
    version: str
    input_sha256: str
    original_native_basis_sha256: str
    original_native_rows_sha256: str
    source_manifest_sha256: str
    final_week_laws: tuple[tuple[int, str], ...]
    generated_at: str
    decision_at: str
    active_heads: tuple[str, ...]
    stages: tuple[CompositeStage, ...]
    bypass: bool
    final_rows_sha256: str
    interpretation: str = "separate_point_XI_score_intervals_and_imposed_phase_coupling"
    eligibility_application: str = "already_in_final_joint_week_law_no_extra_multiplier"
    tactical_rate_head: str = "not_evaluated"
    phase_zero_identity: str = "not_claimed_state_normalization_changes_marginal_shares"


@dataclass(frozen=True)
class CompositeFixtureResult:
    rows_json: str
    receipt: CompositeReceipt


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("Only closed dataclass values and explicit timestamps can be encoded.")


def composite_bytes(value: object) -> bytes:
    """Canonical encoding of declared DTOs, not a polymorphic object deserializer."""
    return json.dumps(
        value, default=_json_default, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def composite_input_digest(value: CompositeFixtureInput) -> str:
    return _digest(value)


def _digest(value: object) -> str:
    return hashlib.sha256(composite_bytes(value)).hexdigest()


def _sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Composite provenance requires exact lowercase SHA256 identities.")
    return value


def _clock(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Composite clocks require explicit offsets.")
    return result


def _number(value: object, *, nonnegative: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Composite numeric fields must be real numbers.")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("Composite number exceeds finite support.") from error
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("Composite numeric support is invalid.")
    return result


def _close(a: float, b: float, label: str) -> None:
    if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("Composite source binding differs: " + label)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(dict(items)) != len(items):
        raise ValueError("Native component JSON contains duplicate keys.")
    return dict(items)


def _rows(raw: str) -> list[dict[str, Any]]:
    if not isinstance(raw, str) or len(raw.encode()) > MAX_NATIVE_BYTES:
        raise ValueError("Native component JSON exceeds its explicit bound.")
    rows = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(rows, list) or not 22 <= len(rows) <= 128:
        raise ValueError("Composite requires the complete bounded paired native roster.")
    for row in rows:
        if not isinstance(row, dict) or any(
            not isinstance(k, str)
            or (v is not None and type(v) not in (str, int, float, bool))
            or (isinstance(v, float) and not math.isfinite(v))
            for k, v in row.items()
        ):
            raise ValueError("Native component rows must contain finite flat JSON values.")
        role_component_record(row)
        if row["minute_role_status"] != "fitted_known_start_labels":
            raise ValueError("Composite cannot invent unknown starting roles.")
    return rows


def _atoms(row: dict[str, Any], field: str) -> tuple[float, ...]:
    return (
        _number(row["zero_probability"]) if field == "probability" else 0.0,
        *(
            _number(row[f"{role}_minute_{field}_{b}"])
            for role in ("start", "cameo")
            for b in (1, 2, 3)
        ),
    )


def _validate(
    x: CompositeFixtureInput,
) -> tuple[list[dict[str, Any]], dict[int, FinalMinuteMarginal]]:
    if type(x) is not CompositeFixtureInput:
        raise ValueError("Composite requires its typed input.")
    _sha(x.native_basis_sha256)
    _sha(x.source_manifest_sha256)
    rows = _rows(x.native_rows_json)
    unit, score, tactical = x.unit, x.score, x.tactical
    if (
        type(unit) is not CompositeUnitContext
        or type(score) is not CompositeScoreContext
        or score.native_model_version not in NATIVE_MODEL_VERSIONS
        or score.native_basis_kind != "prospective"
    ):
        raise ValueError("Composite requires explicit original prospective source contexts.")
    for digest in (score.native_basis_sha256, score.source_sha256):
        _sha(digest)
    validate_tactical_projection(tactical)
    if not x.native_basis_sha256 == score.native_basis_sha256 == tactical.native_source.sha256:
        raise ValueError("Composite original native artifact identities differ.")
    if tactical.replay is not None or unit.catalog.replay is not None:
        raise ValueError("Composite needs home-oriented current source templates without replay.")
    scope = (score.season, score.gameweek, score.fixture_id)
    clubs = (score.home_club_code, score.away_club_code)
    decision, generated = _clock(score.decision_at), _clock(x.generated_at)
    if (
        generated > decision
        or unit.captured_at > generated
        or _clock(x.duration.generated_at) > generated
        or _clock(x.duration.source_captured_at) > generated
        or _clock(score.native_basis_fit_cutoff) >= decision
        or not decision < _clock(score.deadline_at) < _clock(score.kickoff)
    ):
        raise ValueError("Composite assembly cannot precede its sources or follow its decision.")
    if (
        (unit.season, unit.gameweek, unit.fixture_id) != scope
        or (tactical.season, tactical.gameweek, tactical.fixture) != scope
        or (x.duration.target_season, x.duration.target_gameweek, x.duration.target_fixture_id)
        != scope
        or (unit.reference_own.club, unit.reference_opponent.club) != clubs
        or (tactical.home.club, tactical.away.club) != clubs
        or unit.decision_cutoff != decision
        or _clock(tactical.decision_at) != decision
        or unit.kickoff != _clock(score.kickoff)
        or _clock(tactical.kickoff) != unit.kickoff
        or _clock(tactical.generated_at) > generated
        or any(s.captured_at > generated for s in unit.catalog.sources)
    ):
        raise ValueError("Composite family source scope or chronology differs.")
    tactical_sources = [tactical.native_source, tactical.roster_source]
    for side in (tactical.home, tactical.away):
        tactical_sources.extend(f.source for f in side.observed_fixtures)
        for player in side.players:
            profile = player.profile
            if profile.trait_source is not None:
                tactical_sources.append(profile.trait_source)
            tactical_sources.extend(role.source for role in profile.role_history)
    if any(_clock(source.retrieved_at) > generated for source in tactical_sources):
        raise ValueError("Composite assembly precedes a tactical source acquisition.")
    if type(x.phase) is not tuple or len(x.phase) != 2:
        raise ValueError("Composite phase sources must cover both oriented sides.")
    for i, phase in enumerate(x.phase):
        if (
            type(phase) is not CompositePhaseContext
            or (phase.season, phase.gameweek, phase.fixture) != scope
            or (phase.club, phase.opponent) != (clubs[i], clubs[1 - i])
            or phase.home is not (i == 0)
            or _clock(phase.decision_at) != decision
            or _clock(phase.kickoff) != unit.kickoff
            or _clock(phase.source.captured_at) > generated
            or _clock(phase.duties.captured_at) > generated
        ):
            raise ValueError("Composite phase source scope or chronology differs.")
    if type(x.final_minutes) is not tuple or any(
        type(p) is not FinalMinuteMarginal or type(p.player_code) is not int
        for p in x.final_minutes
    ):
        raise ValueError("Composite final marginals must be immutable.")
    final = {p.player_code: p for p in x.final_minutes}
    codes = [row["player_code"] for row in rows]
    identities = tuple(sorted((row["player_code"], row["club"], row["position"]) for row in rows))
    if (
        any(type(code) is not int or code <= 0 for code in codes)
        or len(set(codes)) != len(codes)
        or len(final) != len(x.final_minutes)
        or set(final) != set(codes)
        or tactical.roster != identities
    ):
        raise ValueError("Composite complete player/club/position identities differ.")
    active_clubs = {
        mapping.player_id: mapping.club
        for mapping in unit.catalog.mappings
        if mapping.valid_from <= decision <= mapping.valid_until and mapping.club in clubs
    }
    if active_clubs != {row["player_code"]: row["club"] for row in rows}:
        raise ValueError("Unit source mappings differ from the complete paired current roster.")
    for row in rows:
        p = final[row["player_code"]]
        if type(p) is not FinalMinuteMarginal or any(
            type(v) is not tuple or len(v) != 7 for v in (p.probabilities, p.minutes)
        ):
            raise ValueError("Composite final support must contain exactly seven immutable atoms.")
        _sha(p.final_week_law_sha256)
        if any(_number(v) > 1 for v in p.probabilities):
            raise ValueError("Composite probability exceeds one.")
        _close(math.fsum(p.probabilities), 1, "final atom mass")
        if p.minutes != _atoms(row, "value"):
            raise ValueError("Composite cannot alter original credited-minute representatives.")
        if any(
            current > 0 and original == 0
            for current, original in zip(
                p.probabilities[1:], _atoms(row, "probability")[1:], strict=True
            )
        ):
            raise ValueError("Composite cannot create unsupported native minute-state mass.")
        if (
            row["fixture"] != score.fixture_id
            or row["GW"] != score.gameweek
            or row.get("model_version", score.native_model_version) != score.native_model_version
            or row["club"] not in clubs
            or row["opponent"] != clubs[1 - clubs.index(row["club"])]
            or row["home"] != int(row["club"] == clubs[0])
            or _clock(row["kickoff"]) != unit.kickoff
        ):
            raise ValueError("Native component fixture scope differs.")
    for i, side in enumerate((tactical.home, tactical.away)):
        selected = [row for row in rows if row["club"] == side.club]
        rate = (score.native_home_goals, score.native_away_goals)[i]
        _close(rate, side.base_goal_rate, "tactical original whole-fixture rate")
        _close(
            rate,
            (unit.causal_baseline_own_goal_rate, unit.causal_baseline_opponent_goal_rate)[i],
            "unit original rate",
        )
        goal, assist = (
            math.fsum(_number(r["goals"]) for r in selected),
            math.fsum(_number(r["assists"]) for r in selected),
        )
        if rate <= 0 or not 0 <= assist <= goal <= rate:
            raise ValueError("Composite requires supported original physical-to-credit fractions.")
        _close(side.scored_fraction, goal / rate, "scored fraction")
        _close(side.assist_fraction, assist / goal if goal else 0, "conditional assist fraction")
        original = {p.profile.player_code: p for p in side.players}
        for row in selected:
            _close(_number(row["team_goal_rate"]), rate, "native paired rate")
            _close(
                original[row["player_code"]].minutes,
                _number(row["expected_minutes"]),
                "native exposure",
            )
            for head in ("goal", "assist"):
                _close(
                    getattr(original[row["player_code"]], "native_" + head + "_share"),
                    _number(row[head + "s_share"]),
                    "native recipient share",
                )
                _close(
                    _number(row[head + "s"]),
                    (goal if head == "goal" else assist) * _number(row[head + "s_share"]),
                    "original credited allocation",
                )
    return rows, final


def _stage(
    name: str,
    source: object,
    result: object,
    artifact: str | None = None,
    fit: str | None = None,
    *,
    include_payload: bool = False,
) -> CompositeStage:
    payload = (
        composite_bytes({"input": source, "result": result}).decode() if include_payload else None
    )
    return CompositeStage(name, _digest(source), _digest(result), artifact, fit, payload)


def _mean(p: FinalMinuteMarginal) -> float:
    return math.fsum(a * b for a, b in zip(p.probabilities, p.minutes, strict=True))


def _tactical_side(
    side: ObservedTacticalSide, final: dict[int, FinalMinuteMarginal]
) -> ObservedTacticalSide:
    means = [_mean(final[p.profile.player_code]) for p in side.players]
    shares = []
    for head in ("native_goal_share", "native_assist_share"):
        weights = []
        for p, minutes in zip(side.players, means, strict=True):
            if p.minutes == 0 and minutes > 0:
                raise ValueError("Final law cannot revive unsupported native recipient exposure.")
            weights.append(getattr(p, head) * minutes / p.minutes if p.minutes else 0.0)
        total = math.fsum(weights)
        if total <= 0:
            raise ValueError("Final law leaves no supported complete-club recipient allocation.")
        shares.append(tuple(w / total for w in weights))
    return replace(
        side,
        players=tuple(
            replace(p, minutes=m, native_goal_share=g, native_assist_share=a)
            for p, m, g, a in zip(side.players, means, shares[0], shares[1], strict=True)
        ),
    )


def _score_row(
    row: dict[str, Any],
    p: FinalMinuteMarginal,
    survival: tuple[float, ...],
    *,
    goals: float,
    assists: float,
    goal_share: float,
    assist_share: float,
    physical: float,
    opposing: float,
    season: str,
) -> dict[str, Any]:
    result = dict(row)
    probabilities, minutes = p.probabilities, p.minutes
    q, expected = math.fsum(probabilities[1:]), _mean(p)
    p60 = math.fsum(v for v, b in zip(probabilities, _BINS, strict=True) if b >= 2)
    if len(survival) != 7 or any(_number(s) > 1 for s in survival):
        raise ValueError("Score process must supply seven bounded survival moments.")
    cs = math.fsum(
        v * s for v, m, s in zip(probabilities, minutes, survival, strict=True) if m >= 60
    )
    if (
        cs > p60 + 1e-12
        or goals + assists > physical + 1e-12
        or (expected == 0 and goals + assists != 0)
    ):
        raise ValueError("Composite player physical or exposure support is violated.")
    rate, dispersion = _number(row["defcon_rate90"]), _number(row["defcon_dispersion"])
    if dispersion <= 0:
        raise ValueError("Native defensive dispersion must be positive.")
    threshold = 10 if row["position"] == "DEF" else 12
    dc = (
        0.0
        if row["position"] == "GK"
        else math.fsum(
            v
            * float(nbinom.sf(threshold - 1, dispersion, dispersion / (dispersion + rate * m / 90)))
            for v, m in zip(probabilities[1:], minutes[1:], strict=True)
        )
    )
    goal_points = {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}[
        row["position"]
    ]
    cs_points = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row["position"]]
    raw = math.fsum(
        (
            q,
            p60,
            goal_points * goals,
            3 * assists,
            cs_points * cs,
            q * _number(row["residual_if_appearance"], nonnegative=False),
            2 * dc if season >= "2025-26" else 0,
        )
    )
    _number(raw, nonnegative=False)
    result.update(
        model_version=OUTPUT_MODEL_VERSION,
        expected_minutes=expected,
        appearance_probability=q,
        p60=p60,
        zero_probability=probabilities[0],
        start_probability=math.fsum(probabilities[1:4]),
        cameo_probability=math.fsum(probabilities[4:]),
        unknown_role_probability=0.0,
        expected_minutes_if_appearance=expected / q if q else 0.0,
        goals=goals,
        assists=assists,
        goals_share=goal_share,
        assists_share=assist_share,
        clean_sheet_probability=cs,
        defcon_probability=dc,
        team_goal_rate=physical,
        opponent_goal_rate=opposing,
        raw_expected_points=raw,
        expected_points=max(0.0, raw),
        availability_multiplier=1.0,
        composite_final_week_law_sha256=p.final_week_law_sha256,
    )
    for i, s in enumerate(survival):
        result[f"score_survival_{i}"] = s
    for role, offset in (("start", 0), ("cameo", 3)):
        for b in (1, 2, 3):
            result[f"{role}_minute_probability_{b}"] = probabilities[offset + b]
            result[f"{role}_minute_value_{b}"] = minutes[offset + b]
    for b in range(4):
        mass = math.fsum(v for v, bin_id in zip(probabilities, _BINS, strict=True) if bin_id == b)
        weighted = math.fsum(
            v * m for v, m, bin_id in zip(probabilities, minutes, _BINS, strict=True) if bin_id == b
        )
        result[f"minute_probability_{b}"] = mass
        result[f"minute_value_{b}"] = weighted / mass if mass else (0, 30, 75, 90)[b]
    role_component_record(result)
    return result


def compose_fixture(
    x: CompositeFixtureInput,
    models: CompositeModels | None,
    *,
    bypass: bool = False,
    include_stage_payloads: bool = False,
) -> CompositeFixtureResult:
    """Compose one complete paired fixture; full bypass executes no family stage."""
    if type(bypass) is not bool or type(include_stage_payloads) is not bool:
        raise ValueError("Composite bypass and payload selection must be Boolean.")
    input_sha = composite_input_digest(x)
    original_rows_sha = hashlib.sha256(x.native_rows_json.encode()).hexdigest()
    if bypass:
        return CompositeFixtureResult(
            x.native_rows_json,
            CompositeReceipt(
                CORE_VERSION,
                input_sha,
                x.native_basis_sha256,
                original_rows_sha,
                x.source_manifest_sha256,
                (),
                x.generated_at,
                x.score.decision_at,
                (),
                (),
                True,
                original_rows_sha,
                eligibility_application="original_native_control_unchanged",
            ),
        )
    if type(models) is not CompositeModels:
        raise ValueError("Active composition requires all compact model artifacts.")
    if (
        type(models.unit) is not UnitServingModel
        or type(models.score) is not ScoreServingModel
        or type(models.phase) is not PhaseServingModel
    ):
        raise ValueError("Composite family models require their compact serving types.")
    rows, final = _validate(x)
    generated = _clock(x.generated_at)
    laws = tuple(sorted((p.player_code, p.final_week_law_sha256) for p in x.final_minutes))
    final_sha = _digest(
        {"original_native": x.native_basis_sha256, "final_minutes": x.final_minutes}
    )
    stages = []
    stage = partial(_stage, include_payload=include_stage_payloads)
    points = tuple(
        project_unit_point(
            club=club,
            roster=tuple(
                UnitPlayer(r["player_code"], r["position"]) for r in rows if r["club"] == club
            ),
            starter_probabilities=tuple(
                UnitStarterProbability(
                    r["player_code"], math.fsum(final[r["player_code"]].probabilities[1:4])
                )
                for r in rows
                if r["club"] == club
            ),
            native_basis_sha256=final_sha,
        )
        for club in (x.score.home_club_code, x.score.away_club_code)
    )
    stages.append(
        stage(
            "final_law_point_units",
            {"final_minutes": x.final_minutes, "original_native": x.native_basis_sha256},
            points,
        )
    )
    point_sha = _digest(points)
    catalog = x.unit.catalog
    previous = next(s for s in catalog.sources if s.source_id == catalog.projection_source_id)
    derived = replace(
        previous,
        source_id="composite-point:" + point_sha,
        provider="squadopt",
        version=CORE_VERSION,
        sha256=point_sha,
        published_at=generated,
        captured_at=generated,
        effective_at=generated,
    )
    catalog = replace(
        catalog,
        sources=(*catalog.sources, derived),
        projection_source_id=derived.source_id,
    )
    unit_input = UnitProjection(
        **{k: v for k, v in vars(x.unit).items() if k not in ("catalog", "captured_at")},
        catalog=catalog,
        captured_at=generated,
        home=True,
        states=(ProjectedUnitState(1.0, points[0].unit, points[1].unit),),
    )
    unit = models.unit.predict(unit_input)
    stages.append(
        stage(
            "unit_paired_whole_fixture_means",
            unit_input,
            unit,
            models.unit.artifact_sha256,
            unit.serving_receipt.original_fit_sha256,
        )
    )
    intervals = project_score_intervals(
        tuple(
            ScoreNativePlayer(
                r["player_code"],
                r["club"],
                r["position"],
                final[r["player_code"]].probabilities,
                final[r["player_code"]].minutes,
            )
            for r in rows
        ),
        x.duration,
        native_basis_sha256=final_sha,
        decision_at=x.score.decision_at,
        generated_at=x.generated_at,
    )
    stages.append(
        stage(
            "uniform_physical_atom_intervals",
            {"final_minutes": x.final_minutes, "duration": x.duration},
            intervals,
        )
    )
    score_input = ScoreFixture(
        **{
            k: v
            for k, v in vars(x.score).items()
            if k
            not in (
                "native_home_goals",
                "native_away_goals",
                "native_basis_sha256",
                "native_model_version",
                "native_basis_kind",
                "native_basis_fit_cutoff",
                "native_basis_evidence_ref",
                "source_sha256",
            )
        },
        players=intervals.players,
        forecast_duration=intervals.receipt.forecast_duration,
        native_home_goals=unit.own_goal_rate,
        native_away_goals=unit.opponent_goal_rate,
        native_basis_sha256=_digest(unit),
        native_model_version=COMPOSITE_OFFSET_VERSION,
        native_basis_kind="prospective",
        native_basis_fit_cutoff=max(
            (x.score.native_basis_fit_cutoff, models.unit.metadata.cutoff), key=_clock
        ),
        native_basis_evidence_ref="composite:unit-result:" + _digest(unit),
        source_sha256=_digest(intervals),
    )
    score = models.score.predict(score_input)
    stages.append(
        stage(
            "score_process_on_unit_means",
            score_input,
            score,
            models.score.artifact_sha256,
            score.serving_receipt.original_metadata_sha256,
        )
    )
    home_context = _tactical_side(x.tactical.home, final)
    away_context = _tactical_side(x.tactical.away, final)
    context_sha = _digest(
        {
            "policy": CORE_VERSION,
            "original_source": x.tactical.native_source,
            "final_minutes_sha256": final_sha,
            "home": home_context,
            "away": away_context,
        }
    )
    native_source = replace(
        x.tactical.native_source,
        source_id="composite-context:" + context_sha,
        provider="squadopt",
        version=CORE_VERSION,
        sha256=context_sha,
        published_at=x.generated_at,
        retrieved_at=x.generated_at,
    )
    tactical_input = replace(
        x.tactical,
        home=home_context,
        away=away_context,
        native_source=native_source,
        generated_at=x.generated_at,
    )
    validate_tactical_projection(tactical_input)
    tactical = models.tactical.predict_recipients(tactical_input)
    if (
        tactical.control
        or tactical.serving_receipt.artifact_sha256 != models.tactical.artifact_sha256
        or tactical.projection_sha256 != _digest(tactical_input)
    ):
        raise ValueError("Composite requires the actual compact tactical recipient heads.")
    stages.append(
        stage(
            "tactical_recipient_heads_only",
            tactical_input,
            tactical,
            models.tactical.artifact_sha256,
            tactical.serving_receipt.original_metadata_sha256,
        )
    )
    physical = (score.prediction.home_physical_goals, score.prediction.away_physical_goals)
    allocated = {}
    for i, (side, recipient, template) in enumerate(
        zip(
            (tactical_input.home, tactical_input.away),
            (tactical.home, tactical.away),
            x.phase,
            strict=True,
        )
    ):
        if (
            recipient.club != side.club
            or {p.player_code for p in recipient.players}
            != {p.profile.player_code for p in side.players}
            or len(recipient.players) != len(side.players)
        ):
            raise ValueError("Tactical recipients differ from the complete current club roster.")
        for head in ("goal_share", "assist_share"):
            if any(_number(getattr(p, head)) > 1 for p in recipient.players):
                raise ValueError("Tactical recipient probability exceeds one.")
            _close(math.fsum(getattr(p, head) for p in recipient.players), 1, "tactical share mass")
        lookup = {p.player_code: p for p in recipient.players}
        marginals = []
        for p in side.players:
            identity = p.profile.player_code
            r = lookup[identity]
            if (r.club, r.position) != (side.club, p.profile.fpl_position):
                raise ValueError("Tactical recipient club or position differs.")
            if p.minutes == 0 and (r.goal_share != 0 or r.assist_share != 0):
                raise ValueError("Zero exposure has positive tactical recipient mass.")
            marginals.append(
                PhaseMinuteMarginal(
                    identity,
                    p.profile.fpl_position,
                    final[identity].probabilities,
                    final[identity].minutes,
                    90 * r.goal_share / p.minutes if p.minutes else 0.0,
                    90 * r.assist_share / p.minutes if p.minutes else 0.0,
                )
            )
        goals = physical[i] * side.scored_fraction
        assists = goals * side.assist_fraction
        coupling = couple_phase_minutes(
            tuple(marginals),
            roster=tuple(p.profile.player_code for p in side.players),
            native_basis_sha256=final_sha,
            goal_mass=goals,
            assist_mass=assists,
            physical_goal_mass=physical[i],
        )
        derived_sha = _digest(
            {"coupling": coupling, "score": _digest(score), "tactical": _digest(tactical)}
        )
        source = replace(
            template.source,
            source_id="composite-phase:" + derived_sha,
            provider="squadopt",
            version=CORE_VERSION,
            raw_sha256=derived_sha,
            published_at=x.generated_at,
            captured_at=x.generated_at,
        )
        projection = PhaseProjection(
            **{k: v for k, v in vars(template).items() if k != "source"},
            states=coupling.states,
            source=source,
        )
        phase = models.phase.predict(projection)
        _close(phase.total_goals, goals, "final club goals")
        _close(phase.total_assists, assists, "final club assists")
        _close(phase.physical_goal_mass, physical[i], "final physical mass")
        stages.append(
            stage(
                "phase_coupling_" + str(side.club),
                {"coupling": coupling, "projection": projection},
                phase,
                models.phase.artifact_sha256,
                phase.serving_receipt.original_metadata_sha256,
            )
        )
        for phase_player in phase.players:
            if phase_player.player_code in allocated:
                raise ValueError("Phase allocation repeats a player identity.")
            allocated[phase_player.player_code] = phase_player
    if set(allocated) != set(final):
        raise ValueError("Phase output lacks the complete paired roster.")
    survival = {p.player_code: p.survival for p in score.prediction.player_survival}
    if set(survival) != set(final):
        raise ValueError("Score survival output lacks the complete paired roster.")
    output = []
    for row in rows:
        identity = row["player_code"]
        a = allocated[identity]
        i = int(row["club"] != x.score.home_club_code)
        output.append(
            _score_row(
                row,
                final[identity],
                survival[identity],
                goals=a.goals,
                assists=a.assists,
                goal_share=a.goals_share,
                assist_share=a.assists_share,
                physical=physical[i],
                opposing=physical[1 - i],
                season=x.score.season,
            )
        )
    raw = composite_bytes(output).decode()
    return CompositeFixtureResult(
        raw,
        CompositeReceipt(
            CORE_VERSION,
            input_sha,
            x.native_basis_sha256,
            original_rows_sha,
            x.source_manifest_sha256,
            laws,
            x.generated_at,
            x.score.decision_at,
            (
                "unit_pooled_v4",
                "score_process",
                "tactical_goals_recipients",
                "tactical_assists_recipients",
                "phase_duties",
            ),
            tuple(stages),
            False,
            hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
