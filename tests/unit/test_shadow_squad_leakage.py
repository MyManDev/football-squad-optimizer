"""Leakage and provenance attacks on the squad-level shadow calibration.

Every fixture here is synthetic. No archive is read, no binding measurement is run,
and the locked holdout season is only ever *named* — never loaded.

``optimize_squad``, ``generate_scenarios``, ``evaluate_fixed_decision`` and
``score_realized_squad_points`` are replaced on the module under test by
deterministic stand-ins for most cases. What is under attack is the protocol's
population boundaries, not CP-SAT or the residual sampler: the stand-ins record
exactly which residual rows each fold was allowed to see, which is the only way to
observe the frozen-history claim at all. Two tests deliberately keep the real
optimizer and the real scoring function so the stand-ins cannot be hiding a broken
real path, and three call the real ``validate_residual_history`` to show where a
leak that survives this module is caught downstream.
"""

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path

import pandas as pd
import pytest
from tests.fixtures.synthetic_players import make_baseline_players

from squadopt.experiments import shadow_squad_calibration as squad_module
from squadopt.experiments.residual_manifest import (
    DECLARED_PREDICTED_POINTS_DECIMALS,
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_calibration import PREREG_GATES
from squadopt.experiments.shadow_report import (
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    replay_identity_of,
    report_to_dict,
    write_shadow_report_once,
)
from squadopt.experiments.shadow_squad_calibration import (
    EVALUATION_SEASON,
    FIT_SEASONS,
    HISTORY_SEASONS,
    LOCKED_HOLDOUT_SEASON,
    S1_GATE,
    S2_GATE,
    FrozenShift,
    PlayerEvidence,
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
    bootstrap_diagnostics,
    build_squad_folds,
    combine_full_protocol,
    declared_parameters,
    evaluate_squad_gates,
    fit_frozen_shift,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
)
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioTarget,
    ScenarioValidationError,
    validate_residual_history,
)

MODEL_NAME = "squadopt-deterministic-baseline"
CONTROL_MODEL_NAME = "squadopt-deterministic-baseline"
CONTROL_MODEL_VERSION = "form_window_05_v1"
COMMIT = "c" * 40
POSITIONS = ("GK", "DEF", "MID", "FWD")
TEAMS = ("TEAM_1", "TEAM_2", "TEAM_3", "TEAM_4")
PROJECTIONS = make_baseline_players()
RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_shadow_squad_calibration.py"


# --------------------------------------------------------------------------------------
# Synthetic fixtures
# --------------------------------------------------------------------------------------


def _provenance() -> PredictionProvenance:
    return PredictionProvenance(
        model_name=MODEL_NAME,
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        training_cutoff="pre_fold_projection",
        training_data_fingerprint="0" * 64,
    )


def _config(**overrides: object) -> SquadShadowConfig:
    """The run's one legal configuration, and a way to try an illegal override."""

    return SquadShadowConfig(**overrides)  # type: ignore[arg-type]


def _realized_points(value: float) -> pd.DataFrame:
    """Realized points covering every projected player; row zero carries the score.

    The stand-in scorer reads row zero, so one number per fold controls the reading
    while the frame stays legal for the real ``score_realized_squad_points``.
    """

    players = PROJECTIONS["player_id"].tolist()
    totals = [float(value)] + [1.0] * (len(players) - 1)
    return pd.DataFrame({"player_id": players, "total_points": totals})


#: The development folds every synthetic residual table names. The shift fit refuses a
#: fold with fewer than ``min_history_folds`` priors, so a fixture that wants to reach
#: the generator at all has to carry a real history.
DEVELOPMENT_FOLD_IDS: tuple[str, ...] = tuple(
    f"{season}-gw{gameweek:02d}" for season in FIT_SEASONS for gameweek in (2, 3, 4)
)


def _fold(
    season: str,
    gameweek: int,
    *,
    fold_id: str | None = None,
    realized: float = 10.0,
    prior: Sequence[str] = DEVELOPMENT_FOLD_IDS,
) -> SquadFold:
    return SquadFold(
        fold_id=fold_id if fold_id is not None else f"{season}-gw{gameweek:02d}",
        season=season,
        gameweek=gameweek,
        projections=PROJECTIONS,
        realized_points=_realized_points(realized),
        prior_fold_ids=tuple(prior),
    )


def _residuals(
    entries: Sequence[tuple[str, int]] | Sequence[tuple[str, int, str]],
    *,
    player_offset: int = 0,
) -> pd.DataFrame:
    """Build a residual table; a third element overrides the fold_id for that entry."""

    rows: list[dict[str, object]] = []
    for entry in entries:
        season, gameweek = str(entry[0]), int(entry[1])
        fold_id = str(entry[2]) if len(entry) > 2 else f"{season}-gw{gameweek:02d}"
        for index in range(8):
            predicted = 2.0 + index * 0.25
            realized = predicted + (index - 4) * 0.5
            rows.append(
                {
                    "fold_id": fold_id,
                    "season": season,
                    "gameweek": gameweek,
                    "player_id": 1 + index + player_offset,
                    "team_id": TEAMS[index % 4],
                    "position": POSITIONS[index % 4],
                    "predicted_points": predicted,
                    "realized_points": realized,
                    "residual": realized - predicted,
                }
            )
    return pd.DataFrame(rows)


def _development_residuals() -> pd.DataFrame:
    return _residuals([(season, gameweek) for season in FIT_SEASONS for gameweek in (2, 3, 4)])


def _panel(seasons: Sequence[str], gameweeks: Sequence[int] = (1, 2, 3)) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in seasons:
        for gameweek in gameweeks:
            for index in range(8):
                rows.append(
                    {
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": 1 + index,
                        "name": f"Synthetic {index}",
                        "team_id": TEAMS[index % 4],
                        "position": POSITIONS[index % 4],
                        "price_tenths": 45 + index,
                        "minutes": 90,
                        "total_points": 2.0 + index,
                    }
                )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Deterministic stand-ins
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reading:
    """What the stand-in scenario evaluation reports for one fold."""

    raw_mean: float = 10.0
    scores: tuple[float, ...] = (0.0, 10.0, 20.0)
    lower: float = -100.0
    diagnostics: Mapping[str, object] | None = None


@dataclass(frozen=True)
class _Decision:
    has_solution: bool = True


@dataclass(frozen=True)
class _Scenarios:
    fold_id: str


@dataclass(frozen=True)
class _Metrics:
    mean_score: float
    lower_quantile_score: float


@dataclass(frozen=True)
class _Evaluation:
    scenario_scores: tuple[float, ...]
    metrics: _Metrics
    diagnostics: dict[str, object]


class _Recorder:
    """Everything the stand-ins saw, so a leak becomes an assertion."""

    def __init__(self) -> None:
        self.histories: list[pd.DataFrame] = []
        self.targets: list[ScenarioTarget] = []
        self.shifts: list[float] = []
        self.bench_weights: list[float] = []
        self.scenario_configs: list[ScenarioConfig] = []

    def history_fold_ids(self) -> list[frozenset[str]]:
        return [frozenset(str(value) for value in frame["fold_id"]) for frame in self.histories]

    def history_seasons(self) -> list[frozenset[str]]:
        return [frozenset(str(value) for value in frame["season"]) for frame in self.histories]


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readings: Mapping[str, _Reading] | None = None,
    default: _Reading | None = None,
    real_optimizer: bool = False,
) -> _Recorder:
    """Replace the module's imported collaborators with recording stand-ins."""

    recorder = _Recorder()
    plans = dict(readings or {})
    fallback = default if default is not None else _Reading()
    real_optimize = squad_module.optimize_squad

    def fake_optimize(players: pd.DataFrame, config: object) -> object:
        recorder.bench_weights.append(float(config.bench_weight))
        if real_optimizer:
            return real_optimize(players, config)  # type: ignore[arg-type]
        return _Decision()

    def fake_generate(
        snapshot: object,
        history: pd.DataFrame,
        target: ScenarioTarget,
        config: ScenarioConfig | None = None,
        *,
        fixture_counts: object = None,
    ) -> _Scenarios:
        recorder.histories.append(history.copy(deep=True))
        recorder.targets.append(target)
        if config is not None:
            recorder.scenario_configs.append(config)
        return _Scenarios(fold_id=target.fold_id)

    def fake_evaluate(decision: object, scenarios: _Scenarios, config: object) -> _Evaluation:
        shift = float(config.location_shift_points)
        recorder.shifts.append(shift)
        plan = plans.get(scenarios.fold_id, fallback)
        diagnostics = (
            {"mean_score_before_shift": plan.raw_mean}
            if plan.diagnostics is None
            else dict(plan.diagnostics)
        )
        return _Evaluation(
            scenario_scores=plan.scores,
            metrics=_Metrics(mean_score=plan.raw_mean + shift, lower_quantile_score=plan.lower),
            diagnostics=diagnostics,
        )

    monkeypatch.setattr(squad_module, "optimize_squad", fake_optimize)
    monkeypatch.setattr(squad_module, "generate_scenarios", fake_generate)
    monkeypatch.setattr(squad_module, "evaluate_fixed_decision", fake_evaluate)
    if not real_optimizer:
        monkeypatch.setattr(
            squad_module,
            "score_realized_squad_points",
            lambda decision, realized: float(realized["total_points"].iloc[0]),
        )
    return recorder


def _shift(points: float = 0.0) -> FrozenShift:
    return FrozenShift(
        shift_points=points,
        fold_count=9,
        first_fold_id="2021-22-gw02",
        last_fold_id="2023-24-gw04",
        seasons=FIT_SEASONS,
    )


# --------------------------------------------------------------------------------------
# Attack 1 — get an evaluation-season fold into the shift fit
# --------------------------------------------------------------------------------------


def test_a_frozen_evaluation_fold_is_refused_by_the_shift_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    folds = (_fold("2022-23", 5), _fold(EVALUATION_SEASON, 5))
    with pytest.raises(SquadShadowError, match="outside the declared fit seasons"):
        fit_frozen_shift(folds, _development_residuals(), _provenance(), _config())


def test_the_fit_refuses_a_season_outside_the_declared_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    with pytest.raises(SquadShadowError, match="outside the declared fit seasons"):
        fit_frozen_shift((_fold("2020-21", 5),), _development_residuals(), _provenance(), _config())


def test_an_evaluation_season_fold_wearing_a_development_fold_id_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The season field decides, so relabelling the fold_id does not smuggle it in."""

    _install(monkeypatch)
    disguised = _fold(EVALUATION_SEASON, 10, fold_id="2022-23-gw10")
    with pytest.raises(SquadShadowError, match="outside the declared fit seasons"):
        fit_frozen_shift((disguised,), _development_residuals(), _provenance(), _config())


def test_a_fold_id_naming_the_evaluation_season_enters_the_fit_and_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEFECT (provenance): only ``season`` is checked, so the id may say anything.

    The reverse disguise is admitted. Nothing cross-checks ``fold_id`` against
    ``season`` and ``gameweek``, so a fold whose identifier claims the frozen
    evaluation season is fitted and then *recorded* as the fit population's last
    fold. The data pulled is not leaked — ``ScenarioTarget`` is rebuilt from
    ``season``/``gameweek``, as the target assertion below shows — so this is a
    provenance defect, not a data leak.
    """

    recorder = _install(monkeypatch)
    folds = (
        _fold("2021-22", 2, realized=10.0),
        _fold("2022-23", 10, fold_id=f"{EVALUATION_SEASON}-gw10", realized=10.0),
    )
    shift = fit_frozen_shift(folds, _development_residuals(), _provenance(), _config())

    assert shift.last_fold_id == f"{EVALUATION_SEASON}-gw10"
    assert EVALUATION_SEASON not in shift.seasons
    assert [target.fold_id for target in recorder.targets] == ["2021-22-gw02", "2022-23-gw10"]


def test_the_fit_refuses_an_empty_population(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    with pytest.raises(SquadShadowError, match="at least one development fold"):
        fit_frozen_shift((), _development_residuals(), _provenance(), _config())


def test_the_shift_is_fitted_at_zero_shift_and_negates_the_mean_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(
        monkeypatch,
        readings={
            "2021-22-gw02": _Reading(raw_mean=12.0),
            "2022-23-gw03": _Reading(raw_mean=8.0),
        },
    )
    folds = (_fold("2021-22", 2, realized=10.0), _fold("2022-23", 3, realized=8.0))
    shift = fit_frozen_shift(folds, _development_residuals(), _provenance(), _config())

    # Gaps are (12 - 10) and (8 - 8); the shift is the negated mean of the two.
    assert recorder.shifts == [0.0, 0.0]
    assert shift.shift_points == pytest.approx(-1.0)
    assert shift.fold_count == 2
    assert shift.seasons == ("2021-22", "2022-23")


def test_a_development_folds_prior_ids_are_policed_by_the_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fold from the right season can still be handed a history from the wrong one.

    The fit refuses an evaluation-season *fold*, which used to be the only check: a
    development fold's self-declared prior ids went straight to the generator, so the
    evaluation season's rows reached the scenario history during the fit. The real
    generator refuses them on chronology — asserted below, because the layer underneath
    is what actually protects the measurement — but the boundary is now enforced where
    it is claimed, before anything is generated.
    """

    recorder = _install(monkeypatch)
    residuals = pd.concat(
        [_development_residuals(), _residuals([(EVALUATION_SEASON, 5)])], ignore_index=True
    )
    fold = _fold(
        "2022-23",
        10,
        prior=(*DEVELOPMENT_FOLD_IDS, f"{EVALUATION_SEASON}-gw05"),
    )
    with pytest.raises(SquadShadowError, match="outside the declared fit seasons"):
        fit_frozen_shift((fold,), residuals, _provenance(), _config())
    assert recorder.histories == []

    # And the layer underneath still refuses the same history on chronology, so the
    # protection does not depend on this module having remembered to look.
    fit_frozen_shift((_fold("2022-23", 10),), residuals, _provenance(), _config())

    snapshot = prepare_optimizer_projection(
        PROJECTIONS.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        PROJECTIONS.loc[:, ["player_id", "expected_points"]],
        _provenance(),
    )
    with pytest.raises(ScenarioValidationError, match="strictly before the scenario target"):
        validate_residual_history(
            recorder.histories[0],
            snapshot,
            ScenarioTarget("2022-23", 10),
            ScenarioConfig(min_history_folds=2),
        )


# --------------------------------------------------------------------------------------
# Attack 2 and 3 — the frozen residual history
# --------------------------------------------------------------------------------------


def test_frozen_history_keeps_only_the_development_seasons() -> None:
    residuals = pd.concat(
        [_development_residuals(), _residuals([(EVALUATION_SEASON, 2), ("2020-21", 2)])],
        ignore_index=True,
    )
    history = frozen_history_fold_ids(residuals)

    assert all(fold_id.startswith(FIT_SEASONS) for fold_id in history)
    assert f"{EVALUATION_SEASON}-gw02" not in history
    assert "2020-21-gw02" not in history


def test_the_evaluation_pass_ignores_a_folds_own_prior_fold_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distinguishing claim: chronological priority is not what selects history."""

    recorder = _install(monkeypatch)
    residuals = pd.concat(
        [
            _development_residuals(),
            _residuals([(EVALUATION_SEASON, 2), (EVALUATION_SEASON, 3)]),
        ],
        ignore_index=True,
    )
    folds = (
        _fold(
            EVALUATION_SEASON,
            10,
            prior=(
                "2021-22-gw02",
                f"{EVALUATION_SEASON}-gw02",
                f"{EVALUATION_SEASON}-gw03",
            ),
        ),
    )
    evaluate_squad_gates(folds, residuals, _provenance(), _config(), _shift())

    seen = recorder.history_fold_ids()[0]
    assert seen == set(frozen_history_fold_ids(residuals))
    assert f"{EVALUATION_SEASON}-gw02" not in seen
    assert f"{EVALUATION_SEASON}-gw03" not in seen


def test_the_frozen_history_is_byte_identical_for_every_evaluation_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a walk-forward: 37 folds are 37 readings of one calibration."""

    recorder = _install(monkeypatch)
    residuals = pd.concat(
        [
            _development_residuals(),
            _residuals([(EVALUATION_SEASON, gameweek) for gameweek in range(2, 39)]),
        ],
        ignore_index=True,
    )
    folds = tuple(_fold(EVALUATION_SEASON, gameweek) for gameweek in range(2, 39))
    evaluate_squad_gates(folds, residuals, _provenance(), _config(), _shift())

    assert len(recorder.histories) == 37
    first = recorder.histories[0].reset_index(drop=True)
    for frame in recorder.histories[1:]:
        pd.testing.assert_frame_equal(frame.reset_index(drop=True), first)
    assert {len(frame) for frame in recorder.histories} == {len(first)}
    assert recorder.history_seasons() == [frozenset(FIT_SEASONS)] * 37


def test_a_residual_fold_id_claiming_the_evaluation_season_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A residual row whose season column lies about its fold_id prefix is caught."""

    _install(monkeypatch)
    residuals = pd.concat(
        [_development_residuals(), _residuals([("2023-24", 5, f"{EVALUATION_SEASON}-gw05")])],
        ignore_index=True,
    )
    with pytest.raises(SquadShadowError, match="frozen history contains evaluation-season folds"):
        evaluate_squad_gates(
            (_fold(EVALUATION_SEASON, 10),), residuals, _provenance(), _config(), _shift()
        )


def test_an_evaluation_season_row_wearing_a_development_fold_id_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fold id is a label; the season column is what the generator actually reads.

    ``frozen_history_fold_ids`` picks ids from rows whose *season* is a development
    season, and the selection then returns every row carrying one of those ids —
    including a row whose season column says 2024-25. Selecting by one key and checking
    the other is how the evaluation season gets into a history that looks frozen, so
    the rows themselves are checked now, not only the ids.
    """

    recorder = _install(monkeypatch)
    poisoned = _residuals([(EVALUATION_SEASON, 3, "2022-23-gw03")], player_offset=100)
    residuals = pd.concat([_development_residuals(), poisoned], ignore_index=True)

    with pytest.raises(SquadShadowError, match="outside the development population"):
        evaluate_squad_gates(
            (_fold(EVALUATION_SEASON, 10),), residuals, _provenance(), _config(), _shift()
        )
    assert recorder.histories == []

    snapshot = prepare_optimizer_projection(
        PROJECTIONS.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        PROJECTIONS.loc[:, ["player_id", "expected_points"]],
        _provenance(),
    )
    # The layer underneath refuses the same frame on its own fold_id/season rule, so
    # the protection does not rest on this module having remembered to look.
    with pytest.raises(ScenarioValidationError, match="fold_id must match its season"):
        validate_residual_history(
            residuals,
            snapshot,
            ScenarioTarget(EVALUATION_SEASON, 10),
            ScenarioConfig(min_history_folds=2),
        )


def test_an_empty_frozen_history_stops_the_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    residuals = _residuals([(EVALUATION_SEASON, 2), (EVALUATION_SEASON, 3)])
    with pytest.raises(SquadShadowError, match="frozen residual history is empty"):
        evaluate_squad_gates(
            (_fold(EVALUATION_SEASON, 10),), residuals, _provenance(), _config(), _shift()
        )


def test_the_evaluation_pass_refuses_a_development_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    folds = (_fold(EVALUATION_SEASON, 10), _fold("2022-23", 10))
    with pytest.raises(SquadShadowError, match="not in the frozen evaluation season"):
        evaluate_squad_gates(folds, _development_residuals(), _provenance(), _config(), _shift())


def test_the_evaluation_pass_takes_no_history_argument() -> None:
    """A caller cannot hand in its own history; the frozen set is derived internally."""

    parameters = set(evaluate_squad_gates.__code__.co_varnames[:6])
    assert "history" not in parameters
    assert "history_fold_ids" not in parameters


# --------------------------------------------------------------------------------------
# Attack 4 and 5 — model binding, tampering, missing manifest
# --------------------------------------------------------------------------------------


def _export_table(seasons: tuple[str, ...] = ("2021-22", "2022-23")) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in seasons:
        for gameweek in (2, 3, 4):
            for index in range(6):
                predicted = 2.0 + index * 0.5
                realized = predicted + (index - 2)
                rows.append(
                    {
                        "fold_id": f"{season}-gw{gameweek:02d}",
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": 100 + index,
                        "team_id": 1 + index % 3,
                        "position": POSITIONS[index % 4],
                        "predicted_points": predicted,
                        "realized_points": float(realized),
                        "residual": float(realized) - predicted,
                    }
                )
    return pd.DataFrame(rows).loc[:, list(RESIDUAL_EXPORT_COLUMNS)]


def _write_export(
    tmp_path: Path, table: pd.DataFrame | None = None, **overrides: object
) -> tuple[Path, Path]:
    frame = _export_table() if table is None else table
    table_path = tmp_path / "in_season_residuals.csv"
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n")
    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
    document: dict[str, object] = {
        "contract_version": "oos_residual_export_v1",
        "candidate_label": "in_season_carry_over_blend",
        "model_name": MODEL_NAME,
        "model_version": IN_SEASON_MODEL_VERSION,
        "feature_contract_version": IN_SEASON_FEATURE_CONTRACT_VERSION,
        "training_contract_version": IN_SEASON_MODEL_VERSION,
        "evaluation_objective": "single_gameweek_realized_squad_points_v1",
        "development_seasons": sorted({str(season) for season in frame["season"]}),
        "opening_gameweeks_included": bool((frame["gameweek"] <= 1).any()),
        "fold_count": int(frame["fold_id"].nunique()),
        "row_count": len(frame),
        "repository_commit": COMMIT,
        "dataset_snapshot_id": "vaastav-fpl@" + "d" * 40,
        "table_sha256": digest,
        "created_at_utc": "2026-08-29T12:00:00+00:00",
        "locked_holdout_accessed": False,
        "predicted_points_decimals": DECLARED_PREDICTED_POINTS_DECIMALS,
    }
    document.update(overrides)
    manifest_path = tmp_path / "in_season_residuals.manifest.json"
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return table_path, manifest_path


def _bind(table_path: Path, manifest_path: Path) -> object:
    """Bind exactly as the runner does."""

    return load_residual_source_manifest(
        table_path,
        manifest_path,
        expect_model_name=MODEL_NAME,
        expect_model_version=IN_SEASON_MODEL_VERSION,
        expect_feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
    )


def test_the_target_model_export_binds(tmp_path: Path) -> None:
    manifest = _bind(*_write_export(tmp_path))
    assert manifest.model_version == IN_SEASON_MODEL_VERSION  # type: ignore[attr-defined]
    assert LOCKED_HOLDOUT_SEASON not in manifest.source_seasons  # type: ignore[attr-defined]


def test_the_archive_fed_control_export_is_refused(tmp_path: Path) -> None:
    """The control the archive feeds is a different model and may not be substituted."""

    paths = _write_export(
        tmp_path,
        model_name=CONTROL_MODEL_NAME,
        model_version=CONTROL_MODEL_VERSION,
        training_contract_version=CONTROL_MODEL_VERSION,
        candidate_label="deterministic_baseline",
    )
    with pytest.raises(ResidualSourceError, match="may not describe another"):
        _bind(*paths)


def test_a_different_feature_contract_is_refused(tmp_path: Path) -> None:
    paths = _write_export(tmp_path, feature_contract_version="form-window-features-v1")
    with pytest.raises(ResidualSourceError, match="feature contract"):
        _bind(*paths)


def test_one_changed_byte_after_the_manifest_is_refused(tmp_path: Path) -> None:
    table_path, manifest_path = _write_export(tmp_path)
    raw = table_path.read_bytes()
    tampered = raw.replace(b"2.0", b"2.1", 1)
    assert tampered != raw
    table_path.write_bytes(tampered)
    with pytest.raises(ResidualSourceError, match="changed after it was described"):
        _bind(table_path, manifest_path)


def test_a_corrupt_digest_is_refused(tmp_path: Path) -> None:
    table_path, manifest_path = _write_export(tmp_path, table_sha256="not-a-digest")
    with pytest.raises(ResidualSourceError, match="not a 64-hex-character"):
        _bind(table_path, manifest_path)


def test_a_missing_manifest_is_refused(tmp_path: Path) -> None:
    table_path, manifest_path = _write_export(tmp_path)
    manifest_path.unlink()
    with pytest.raises(ResidualSourceError, match="manifest not found"):
        _bind(table_path, manifest_path)


def test_a_residual_export_carrying_the_holdout_is_refused(tmp_path: Path) -> None:
    table = _export_table(("2021-22", "2022-23", LOCKED_HOLDOUT_SEASON))
    with pytest.raises(ResidualSourceError, match="forbidden for this calibration"):
        _bind(*_write_export(tmp_path, table))


def test_a_residual_source_record_refuses_the_holdout_season() -> None:
    with pytest.raises(ShadowReportError, match="locked holdout"):
        ShadowResidualSource(
            export_label="in_season_carry_over_blend",
            model_name=MODEL_NAME,
            model_version=IN_SEASON_MODEL_VERSION,
            feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
            table_sha256="e" * 64,
            seasons=("2023-24", LOCKED_HOLDOUT_SEASON),
            cutoff_fold_id="2023-24-gw38",
        )


# --------------------------------------------------------------------------------------
# Attack 6 — the locked holdout
# --------------------------------------------------------------------------------------


def test_a_holdout_fold_cannot_be_constructed() -> None:
    with pytest.raises(SquadShadowError, match="locked holdout and may not be scored"):
        _fold(LOCKED_HOLDOUT_SEASON, 10)


def test_the_panel_loader_names_its_seasons_instead_of_cutting_afterwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_build_panel(archive_root: Path, seasons: object = None) -> pd.DataFrame:
        seen["root"] = archive_root
        seen["seasons"] = seasons
        return _panel(list(HISTORY_SEASONS))

    monkeypatch.setattr(squad_module, "build_panel", fake_build_panel)
    panel = load_panel_without_the_holdout(Path("does-not-exist"))

    assert seen["seasons"] == HISTORY_SEASONS
    assert LOCKED_HOLDOUT_SEASON not in HISTORY_SEASONS
    assert LOCKED_HOLDOUT_SEASON not in set(panel["season"])


def test_a_panel_carrying_the_holdout_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        squad_module,
        "build_panel",
        lambda root, seasons=None: _panel([*HISTORY_SEASONS, LOCKED_HOLDOUT_SEASON]),
    )
    with pytest.raises(SquadShadowError, match="rows are present in the loaded panel"):
        load_panel_without_the_holdout(Path("does-not-exist"))


def test_a_panel_missing_the_declared_population_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        squad_module, "build_panel", lambda root, seasons=None: _panel(["2021-22", "2022-23"])
    )
    with pytest.raises(SquadShadowError, match="does not cover the declared population"):
        load_panel_without_the_holdout(Path("does-not-exist"))


def test_building_folds_over_the_holdout_season_is_refused() -> None:
    panel = _panel([EVALUATION_SEASON, LOCKED_HOLDOUT_SEASON])
    residuals = _development_residuals()
    with pytest.raises(SquadShadowError, match="locked holdout and may not be scored"):
        build_squad_folds(
            panel,
            residuals,
            lambda decision: PROJECTIONS,
            seasons=(LOCKED_HOLDOUT_SEASON,),
        )


def test_a_frozen_shift_record_refuses_the_locked_holdout_as_its_fit_population() -> None:
    """``FrozenShift`` is checked against the declared fit population, not season by season.

    A shift record that could name ``2025-26`` in ``seasons`` would let a run declare it
    was fitted on the locked holdout and have ``evaluate_squad_gates`` apply it without a
    word — a provenance claim the protocol forbids outright. One subset rule against
    ``FIT_SEASONS`` excludes the locked holdout and the frozen evaluation season alike,
    so neither depends on someone remembering to add a second named check.
    """

    with pytest.raises(SquadShadowError, match="outside the declared fit population"):
        FrozenShift(
            shift_points=-3.5,
            fold_count=4,
            first_fold_id=f"{LOCKED_HOLDOUT_SEASON}-gw02",
            last_fold_id=f"{LOCKED_HOLDOUT_SEASON}-gw05",
            seasons=(LOCKED_HOLDOUT_SEASON,),
        )
    with pytest.raises(SquadShadowError, match="outside the declared fit population"):
        FrozenShift(
            shift_points=-3.5,
            fold_count=4,
            first_fold_id="2021-22-gw02",
            last_fold_id=f"{EVALUATION_SEASON}-gw05",
            seasons=("2021-22", EVALUATION_SEASON),
        )
    # The declared population itself is still a legal record.
    fitted = FrozenShift(
        shift_points=-3.5,
        fold_count=4,
        first_fold_id="2021-22-gw02",
        last_fold_id="2023-24-gw38",
        seasons=FIT_SEASONS,
    )
    assert fitted.seasons == FIT_SEASONS


# --------------------------------------------------------------------------------------
# Attack 7 — missing is never zero
# --------------------------------------------------------------------------------------


def test_an_absent_pre_shift_mean_refuses_the_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, default=_Reading(diagnostics={"scoring_policy": "v1"}))
    with pytest.raises(SquadShadowError, match="reported no pre-shift mean"):
        fit_frozen_shift((_fold("2022-23", 5),), _development_residuals(), _provenance(), _config())


def test_a_none_pre_shift_mean_refuses_the_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, default=_Reading(diagnostics={"mean_score_before_shift": None}))
    with pytest.raises(SquadShadowError, match="reported no pre-shift mean"):
        evaluate_squad_gates(
            (_fold(EVALUATION_SEASON, 5),),
            _development_residuals(),
            _provenance(),
            _config(),
            _shift(),
        )


def test_a_genuine_zero_pre_shift_mean_is_scored_not_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing and zero stay distinct in both directions."""

    _install(
        monkeypatch, default=_Reading(raw_mean=0.0, diagnostics={"mean_score_before_shift": 0.0})
    )
    shift = fit_frozen_shift(
        (_fold("2022-23", 5, realized=4.0),), _development_residuals(), _provenance(), _config()
    )
    assert shift.shift_points == pytest.approx(4.0)


def test_a_non_finite_pre_shift_mean_refuses_the_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, default=_Reading(diagnostics={"mean_score_before_shift": float("nan")}))
    with pytest.raises(SquadShadowError, match="non-finite score cannot enter"):
        fit_frozen_shift((_fold("2022-23", 5),), _development_residuals(), _provenance(), _config())


def test_an_infeasible_decision_refuses_the_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setattr(squad_module, "optimize_squad", lambda players, config: _Decision(False))
    with pytest.raises(SquadShadowError, match="no feasible risk-neutral decision"):
        fit_frozen_shift((_fold("2022-23", 5),), _development_residuals(), _provenance(), _config())


# --------------------------------------------------------------------------------------
# The gates themselves
# --------------------------------------------------------------------------------------


def _population(
    pit_target: float, tail_count: int, folds: int = 50
) -> tuple[tuple[SquadFold, ...], dict[str, _Reading]]:
    """Folds whose stand-in readings land the two gates on an exact rate.

    The scenario scores are ``0..99``, so a realized score of ``k`` gives a PIT of
    ``(k + 1) / 100`` exactly. The gameweek axis runs past 38 only because the
    contract's own rule is ``gameweek >= 2``; nothing here claims a real calendar.
    """

    scores = tuple(float(index) for index in range(100))
    realized = round(pit_target * 100) - 1.0
    built: list[SquadFold] = []
    readings: dict[str, _Reading] = {}
    for index in range(folds):
        gameweek = 2 + index
        fold = _fold(EVALUATION_SEASON, gameweek, realized=realized)
        built.append(fold)
        readings[fold.fold_id] = _Reading(
            raw_mean=50.0, scores=scores, lower=1000.0 if index < tail_count else -1000.0
        )
    return tuple(built), readings


def test_the_gate_bounds_are_inclusive_at_the_lower_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folds, readings = _population(0.43, tail_count=2)
    _install(monkeypatch, readings=readings)
    gates, _, diagnostics = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift()
    )
    assert diagnostics["mean_probability_integral_transform"] == pytest.approx(0.43)
    assert diagnostics["realized_below_lower_quantile_rate"] == pytest.approx(0.04)
    assert {gate.gate: gate.passes for gate in gates} == {S1_GATE: True, S2_GATE: True}


def test_the_gate_bounds_are_inclusive_at_the_upper_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folds, readings = _population(0.57, tail_count=8)
    _install(monkeypatch, readings=readings)
    gates, _, diagnostics = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift()
    )
    assert diagnostics["mean_probability_integral_transform"] == pytest.approx(0.57)
    assert diagnostics["realized_below_lower_quantile_rate"] == pytest.approx(0.16)
    assert all(gate.passes for gate in gates)


def test_a_gate_just_outside_its_bound_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    folds, readings = _population(0.42, tail_count=9)
    _install(monkeypatch, readings=readings)
    gates, _, _ = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift()
    )
    assert {gate.gate: gate.passes for gate in gates} == {S1_GATE: False, S2_GATE: False}


def test_a_thin_evaluation_population_yields_no_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    folds, readings = _population(0.50, tail_count=1, folds=5)
    _install(monkeypatch, readings=readings)
    gates, built, diagnostics = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift()
    )
    assert gates == ()
    assert len(built) == 5
    assert "mean_probability_integral_transform" not in diagnostics


def test_the_fold_level_bootstrap_exists_and_no_gate_can_consult_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The promised interval is now computed — and kept out of the verdict.

    Clause 22 of the second amendment says the bootstrap is diagnostic only: the gate
    is decided on the pre-registered point estimate, and an interval that straddles a
    bound neither rescues a failing estimate nor overturns a passing one. That is
    enforced structurally rather than by intention. ``evaluate_squad_gates``, which
    reads the gates, contains no call to the bootstrap at all — asserted here by
    parsing the module rather than by trusting the reading — and the numbers come back
    from a separate function the gate evaluation never invokes.
    """

    folds, readings = _population(0.50, tail_count=5)
    _install(monkeypatch, readings=readings)
    gates, built, diagnostics = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift()
    )
    assert set(diagnostics) == {
        "evaluation_folds",
        "frozen_shift_points",
        "shift_fit_folds",
        "mean_probability_integral_transform",
        "realized_below_lower_quantile_rate",
        "realized_below_lower_quantile_folds",
    }

    source = ast.parse(Path(squad_module.__file__ or "").read_text(encoding="utf-8"))
    evaluator = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_squad_gates"
    )
    called = {
        node.func.id
        for node in ast.walk(evaluator)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "bootstrap_interval" not in called
    assert "bootstrap_diagnostics" not in called

    intervals = bootstrap_diagnostics(built, _config())
    assert intervals["bootstrap_folds"] == float(len(built))
    assert intervals["bootstrap_resamples"] == 5000.0
    assert intervals["bootstrap_confidence_level"] == 0.90
    for name in ("mean_pit", "below_lower_quantile_rate"):
        low = intervals[f"{name}_bootstrap_low"]
        high = intervals[f"{name}_bootstrap_high"]
        assert low is not None and high is not None and low <= high
    # Deterministic at the pre-registered seed: the same readings give the same bounds.
    assert bootstrap_diagnostics(built, _config()) == intervals
    # And the verdict is unchanged by any of it: the gates were already decided above.
    assert [gate.passes for gate in gates] == [True, True]


# --------------------------------------------------------------------------------------
# Attack 8 — provenance in the report
# --------------------------------------------------------------------------------------


def _execution() -> ShadowExecutionMetadata:
    return ShadowExecutionMetadata(
        started_at_utc="2026-08-29T10:00:00+00:00",
        completed_at_utc="2026-08-29T10:05:00+00:00",
        elapsed_seconds=300.0,
        deterministic_seed=11,
        warnings=(),
    )


def _source() -> ShadowResidualSource:
    return ShadowResidualSource(
        export_label="in_season_carry_over_blend",
        model_name=MODEL_NAME,
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        table_sha256="f" * 64,
        seasons=FIT_SEASONS,
        cutoff_fold_id="2023-24-gw38",
    )


def _fingerprints(**overrides: str) -> dict[str, str]:
    values = {
        "repository_commit": "a" * 40,
        "working_tree_dirty": "false",
        "dataset_snapshot_id": "vaastav-fpl@" + "b" * 40,
        "residual_generation_commit": COMMIT,
        "residual_table_sha256": "f" * 64,
        "model_identity": f"{MODEL_NAME}/{IN_SEASON_MODEL_VERSION}",
        "run_contract_version": squad_module.SQUAD_SHADOW_CONTRACT_VERSION,
    }
    values.update(overrides)
    return values


def _gate(name: str, *, passes: bool = True, observed: float = 0.5) -> ShadowGateResult:
    return ShadowGateResult(gate=name, passes=passes, observed=observed, threshold="pre-registered")


def _player(gates: tuple[ShadowGateResult, ...]) -> PlayerEvidence:
    """A bound player-level record, standing in for the recorded artifact.

    The merge takes evidence rather than a bare gate sequence, so a test cannot
    accidentally reproduce the defect the signature exists to prevent.
    """

    return PlayerEvidence(
        gates=gates,
        calibration_diagnostics={},
        interval_diagnostics={},
        provenance={"player_report_sha256": "e" * 64},
        abstentions=(),
        sample_size=37,
    )


def _combine(**overrides: object) -> object:
    arguments: dict[str, object] = {
        "generated_at_utc": "2026-08-29T10:00:00+00:00",
        "execution": _execution(),
        "residual_source": _source(),
        "player_gates": (_gate("P1_player_coverage"),),
        "squad_gates": (_gate(S1_GATE), _gate(S2_GATE)),
        "calibration_diagnostics": {"evaluation_folds": 37.0},
        "interval_diagnostics": {},
        "evaluation_folds": 37,
        "provenance_fingerprints": _fingerprints(),
        "abstention_reasons": (),
    }
    arguments.update(overrides)
    gates = arguments.pop("player_gates")
    return combine_full_protocol(player=_player(gates), **arguments)  # type: ignore[arg-type]


def test_a_report_cannot_carry_an_empty_provenance_value() -> None:
    with pytest.raises(ShadowReportError, match="must be non-empty strings"):
        _combine(provenance_fingerprints=_fingerprints(model_identity=""))


def test_a_report_cannot_carry_an_empty_provenance_key() -> None:
    fingerprints = _fingerprints()
    fingerprints[""] = "something"
    with pytest.raises(ShadowReportError, match="must be non-empty strings"):
        _combine(provenance_fingerprints=fingerprints)


def test_the_model_identity_travels_into_the_report_document() -> None:
    document = report_to_dict(_combine())  # type: ignore[arg-type]
    fingerprints = document["provenance_fingerprints"]
    assert isinstance(fingerprints, dict)
    assert fingerprints["model_identity"] == f"{MODEL_NAME}/{IN_SEASON_MODEL_VERSION}"
    source = document["residual_source"]
    assert isinstance(source, dict)
    assert source["model_version"] == IN_SEASON_MODEL_VERSION
    assert source["feature_contract_version"] == IN_SEASON_FEATURE_CONTRACT_VERSION
    assert LOCKED_HOLDOUT_SEASON not in source["seasons"]


def _declared_fingerprints(**overrides: str) -> dict[str, str]:
    """The runner's fingerprint set, including every parameter it constructed."""

    values = _fingerprints(**declared_parameters(_config(), shift_points=-3.5))
    values.update(overrides)
    return values


def test_every_constructed_parameter_reaches_the_artifact() -> None:
    """Clause 24: no parameter of any configuration the run built may stay unnamed.

    Three generator knobs used to reach the generator as library defaults and appear
    in no artifact, so two runs taken under different shrinkage would have been
    indistinguishable to a reader — and to ``replay_identity_of``, which would have
    called them one measurement and read the second as an unexplained conflict. The
    parameters are read off the constructed objects, so this also covers the fields
    nobody thought to list: the optimizer's solver time limit is in here too.
    """

    parameters = declared_parameters(_config(), shift_points=-3.5)
    assert parameters["protocol_bench_weight"] == "0.1"
    assert parameters["protocol_decision_universe"] == "full_roster"
    assert parameters["optimizer_bench_weight"] == "0.1"
    assert parameters["generator_min_history_folds"] == "8"
    assert parameters["generator_min_player_observations"] == "8"
    assert parameters["generator_player_scale_shrinkage"] == "10.0"
    assert parameters["generator_player_location_shrinkage"] == "None"
    assert parameters["evaluation_location_shift_points"] == "-3.5"
    assert parameters["optimizer_solver_time_limit_seconds"] == "10.0"

    # Every field of the protocol's own configuration is named, whatever it is called.
    for entry in dataclass_fields(_config()):
        assert f"protocol_{entry.name}" in parameters

    document = report_to_dict(_combine(provenance_fingerprints=_declared_fingerprints()))  # type: ignore[arg-type]
    fingerprints = document["provenance_fingerprints"]
    assert isinstance(fingerprints, dict)
    assert fingerprints["optimizer_bench_weight"] == "0.1"

    # And they are part of the measurement's identity, not commentary beside it: a run
    # under a different weight is a different measurement, not a replay of this one.
    other = report_to_dict(
        _combine(provenance_fingerprints=_declared_fingerprints(optimizer_bench_weight="0.0"))  # type: ignore[arg-type]
    )
    assert replay_identity_of(document) != replay_identity_of(other)


def test_an_unimplemented_decision_universe_is_refused_rather_than_declared_and_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run may not declare a universe it did not use.

    The two universes give different squads and therefore different PIT, which is why
    the first amendment refused to pick one. The second picked the full roster — the
    product's real selection space — and only that one is built: the squad is always
    optimized over the whole projection frame. Accepting ``candidate_pool`` as a name
    while measuring the full roster would put a false control into the artifact, so the
    configuration refuses it, and the universe it does accept is the one the readings
    come from.
    """

    with pytest.raises(SquadShadowError, match="pre-registered at 'full_roster'"):
        _config(decision_universe="candidate_pool")

    recorder = _install(monkeypatch, real_optimizer=True)
    config = _config(decision_universe="full_roster")
    _, built, _ = evaluate_squad_gates(
        (_fold(EVALUATION_SEASON, 10, realized=40.0),),
        _development_residuals(),
        _provenance(),
        config,
        _shift(),
    )
    assert config.decision_universe == "full_roster"
    assert len(recorder.histories) == 1
    assert 0.0 <= built[0].probability_integral_transform <= 1.0


def test_squad_gates_alone_cannot_claim_a_full_pass() -> None:
    report = _combine(player_gates=())
    assert report.shadow_status == "abstained"  # type: ignore[attr-defined]
    assert any("P1_player_coverage" in reason for reason in report.reasons)  # type: ignore[attr-defined]


def test_a_failing_gate_is_the_result() -> None:
    report = _combine(squad_gates=(_gate(S1_GATE), _gate(S2_GATE, passes=False)))
    assert report.shadow_status == "failed"  # type: ignore[attr-defined]
    assert any("thresholds do not move" in reason for reason in report.reasons)  # type: ignore[attr-defined]


def test_a_full_pass_declares_every_pre_registered_family() -> None:
    report = _combine()
    assert report.shadow_status == "calibrated_internal"  # type: ignore[attr-defined]
    assert report.declared_gates == PREREG_GATES  # type: ignore[attr-defined]
    assert report_to_dict(report)["declared_gates"] == list(PREREG_GATES)  # type: ignore[arg-type]


def test_a_gate_outside_the_pre_registered_set_cannot_count_toward_a_pass() -> None:
    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _combine(squad_gates=(_gate(S1_GATE), _gate(S2_GATE), _gate("X_private_gate")))


def test_a_recorded_report_is_not_overwritten_by_a_different_identity(tmp_path: Path) -> None:
    path = tmp_path / "shadow_calibration_squad.json"
    assert write_shadow_report_once(_combine(), path) == "written"  # type: ignore[arg-type]

    replay = _combine(generated_at_utc="2026-08-30T09:00:00+00:00")
    assert write_shadow_report_once(replay, path) == "replay"  # type: ignore[arg-type]

    other = _combine(
        provenance_fingerprints=_fingerprints(
            model_identity=f"{CONTROL_MODEL_NAME}/{CONTROL_MODEL_VERSION}"
        )
    )
    with pytest.raises(ShadowReportError, match="already holds a different measurement"):
        write_shadow_report_once(other, path)  # type: ignore[arg-type]
    assert (
        json.loads(path.read_text(encoding="utf-8"))["provenance_fingerprints"]["model_identity"]
        == f"{MODEL_NAME}/{IN_SEASON_MODEL_VERSION}"
    )


# --------------------------------------------------------------------------------------
# The controls the amendment left unfixed, and the runner's own provenance call
# --------------------------------------------------------------------------------------


def test_the_six_formerly_open_controls_are_now_pinned_not_merely_demanded() -> None:
    """Naming a control with no default has become accepting only one value for it.

    The first amendment refused to choose bench_weight, the decision universe and
    min_history_folds, so the configuration demanded all three and a run that could not
    name them did not start. The second amendment fixed them, along with the three
    generator knobs that had been reaching the generator as library defaults and never
    reaching the artifact. The protection is strictly stronger than it was: the value
    is not merely recorded, it is the only one the configuration accepts.
    """

    settings = SquadShadowConfig()
    assert settings.bench_weight == 0.1
    assert settings.decision_universe == "full_roster"
    assert settings.min_history_folds == 8
    assert settings.min_player_observations == 8
    assert settings.player_scale_shrinkage == 10.0
    assert settings.player_location_shrinkage is None

    for name, other in (
        ("bench_weight", 0.0),
        ("decision_universe", "candidate_pool"),
        ("min_history_folds", 2),
        ("min_player_observations", 4),
        ("player_scale_shrinkage", 5.0),
        ("player_location_shrinkage", 10.0),
    ):
        with pytest.raises(SquadShadowError, match="pre-registered at"):
            _config(**{name: other})


def test_a_pinned_constant_may_not_be_re_chosen_by_a_run() -> None:
    with pytest.raises(SquadShadowError, match="pre-registered at 200"):
        _config(scenario_count=500)
    with pytest.raises(SquadShadowError, match="pre-registered at 11"):
        _config(scenario_seed=0)
    with pytest.raises(SquadShadowError, match=r"pre-registered at 0\.1"):
        _config(lower_quantile=0.05)


def test_the_pinned_history_floor_is_legal_for_the_contract_that_consumes_it() -> None:
    """The pinned number must be one the generator will actually accept.

    ``ScenarioConfig`` requires at least two history folds, and the second amendment
    pins ``min_history_folds`` at the generator's own default of 8, so today the two
    cannot disagree. The assertion is kept anyway: a later amendment that lowered the
    pin below the generator's floor would otherwise be discovered inside the first fold
    of a real run — after the panel and the residual table have been read — rather than
    at configuration time.
    """

    assert SquadShadowConfig().min_history_folds == 8
    assert ScenarioConfig(min_history_folds=8).min_history_folds == 8
    with pytest.raises(SquadShadowError, match="pre-registered at 8"):
        _config(min_history_folds=1)
    with pytest.raises(ScenarioConfigurationError, match="min_history_folds must be at least 2"):
        ScenarioConfig(min_history_folds=1)


def _runner_call(name: str) -> ast.Call:
    """The runner's single call to ``name``, read from its source rather than run.

    Executing the CLI would need the archive; parsing it does not, and the assertion
    still follows the call if it moves inside the module.
    """

    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]
    assert len(calls) == 1
    return calls[0]


def test_the_runner_binds_its_prediction_provenance_to_the_residual_digest() -> None:
    """The CLI constructs the provenance it passes on, and binds it to the export.

    ``PredictionProvenance`` requires ``training_data_fingerprint``; a call that omitted
    it raised ``TypeError`` only after the panel and the residual table had been read,
    which is both a blocking defect and an expensive one. The field is now supplied, and
    supplied as ``manifest.table_sha256`` rather than as a placeholder — so the scenario
    snapshot and the decision are bound to the one residual artifact the run declared,
    and a reader of either can tell which.
    """

    call = _runner_call("PredictionProvenance")
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    assert "training_data_fingerprint" in keywords

    bound = keywords["training_data_fingerprint"]
    assert isinstance(bound, ast.Attribute)
    assert bound.attr == "table_sha256"
    assert isinstance(bound.value, ast.Name)
    # The source record, not the manifest: it is the object the recorded player report
    # was matched against, so the scenarios, the decision and P1 are bound to one thing.
    assert bound.value.id == "residual_source"

    # The keyword set the runner passes is exactly what the dataclass requires, and the
    # bound value is the shape it demands: a lowercase 64-hex digest, as a manifest's is.
    values = dict.fromkeys(sorted(keywords), "pre_fold_projection")
    values["training_data_fingerprint"] = "0" * 64
    provenance = PredictionProvenance(**values)  # type: ignore[arg-type]
    assert provenance.training_data_fingerprint == "0" * 64


def test_the_runner_records_the_shift_fit_and_expands_every_parameter() -> None:
    """The artifact states what produced it, and the runner does not curate that list.

    Clause 18 wants the shift fit's population named — ``min_history_folds`` drops the
    earliest eligible folds, so the season list alone does not say which folds were
    fitted — and clause 24 wants every constructed parameter recorded. The second is
    checked structurally: the runner expands ``declared_parameters`` into its
    fingerprints rather than listing keys of its own, so a parameter cannot be left out
    by forgetting to add it here. The CLI is parsed, not executed, because running it
    needs the archive.
    """

    mapping = _runner_call("_Measurement").keywords
    provenance = {keyword.value for keyword in mapping if keyword.arg == "provenance"}
    assert len(provenance) == 1
    recorded = provenance.pop()
    assert isinstance(recorded, ast.Dict)
    keys = {key.value for key in recorded.keys if isinstance(key, ast.Constant)}
    assert {
        "frozen_shift_points",
        "shift_fit_folds",
        "shift_fit_first_fold",
        "shift_fit_last_fold",
    } <= keys

    # A ``**declared_parameters(...)`` expansion, which argparse-style key lists cannot
    # drift away from: the keys come from the configurations themselves.
    expanded = {
        value.func.id
        for key, value in zip(recorded.keys, recorded.values, strict=True)
        if key is None and isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
    }
    assert "declared_parameters" in expanded


# --------------------------------------------------------------------------------------
# The real optimizer, so the stand-ins cannot be hiding a broken path
# --------------------------------------------------------------------------------------


def test_the_real_optimizer_and_scorer_read_a_fold_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(
        monkeypatch,
        default=_Reading(raw_mean=60.0, scores=(50.0, 60.0, 70.0), lower=55.0),
        real_optimizer=True,
    )
    folds = (_fold(EVALUATION_SEASON, 10, realized=40.0),)
    _, readings, _ = evaluate_squad_gates(
        folds, _development_residuals(), _provenance(), _config(), _shift(-2.0)
    )

    assert recorder.bench_weights == [0.1]
    assert recorder.shifts == [-2.0]
    reading = readings[0]
    # Eleven starters at 1.0 plus the captain counted twice, with row zero at 40.0
    # only if the captain or a starter is player one; either way the score is finite
    # and the tail flag is read strictly below the stand-in quantile.
    assert reading.realized_score > 0.0
    assert reading.below_lower_quantile is (reading.realized_score < 55.0)
    assert 0.0 <= reading.probability_integral_transform <= 1.0


def test_the_scenario_config_pins_every_knob_the_run_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)
    fit_frozen_shift((_fold("2022-23", 5),), _development_residuals(), _provenance(), _config())
    scenario_config = recorder.scenario_configs[0]
    assert scenario_config.scenario_count == 200
    assert scenario_config.deterministic_seed == 11
    assert scenario_config.double_gameweek_scale == 1.0
    assert scenario_config.min_history_folds == 8
    # The three the second amendment named because they were reaching the generator as
    # library defaults. They are asserted here, at the generator's own door, rather than
    # only on the configuration object: that is where an inherited default would show.
    assert scenario_config.min_player_observations == 8
    assert scenario_config.player_scale_shrinkage == 10.0
    assert scenario_config.player_location_shrinkage is None


#: One chronological development chain, long enough to have a burn-in and a remainder.
_CHAIN_GAMEWEEKS = tuple(range(2, 14))
_CHAIN = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in _CHAIN_GAMEWEEKS)


def _chain(*, missing: str | None = None) -> tuple[tuple[SquadFold, ...], pd.DataFrame]:
    """The chain and its residual export, optionally with one fold absent from both.

    Each fold's realized score is chosen so that its gap is 100 while it is burn-in and
    1 once it is eligible, which makes the fitted shift say by itself which folds
    entered the mean.
    """

    present = [fold_id for fold_id in _CHAIN if fold_id != missing]
    residuals = _residuals(
        [("2021-22", gameweek) for gameweek in _CHAIN_GAMEWEEKS if _CHAIN[gameweek - 2] != missing]
    )
    folds = tuple(
        _fold(
            "2021-22",
            gameweek,
            realized=-90.0 if index < 8 else 9.0,
            prior=tuple(fold_id for fold_id in present if fold_id < _CHAIN[index]),
        )
        for index, gameweek in enumerate(_CHAIN_GAMEWEEKS)
    )
    return folds, residuals


def test_the_burn_in_folds_are_excluded_and_the_remainder_is_what_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clause 27, 28 and 30 in one reading.

    The chain's first eight folds carry less history than the declared depth, so they
    are burn-in: their gaps do not enter the mean, and — because eligibility is decided
    before anything is generated rather than by catching the generator's refusal — the
    generator never sees them at all. What the artifact records is the remainder, not
    the population that was handed in.
    """

    recorder = _install(monkeypatch)
    folds, residuals = _chain()

    shift = fit_frozen_shift(folds, residuals, _provenance(), _config())

    # Every burn-in gap is 100 and every eligible gap is 1, so the fitted shift is the
    # negated mean over the remainder alone.
    assert shift.shift_points == pytest.approx(-1.0)
    assert shift.fold_count == 4
    assert shift.first_fold_id == "2021-22-gw10"
    assert shift.last_fold_id == "2021-22-gw13"
    assert len(recorder.histories) == 4


def test_a_population_that_is_all_burn_in_is_refused_rather_than_averaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mean of nothing is not a shift."""

    _install(monkeypatch)
    folds, residuals = _chain()
    with pytest.raises(SquadShadowError, match="mean of nothing"):
        fit_frozen_shift(folds[:8], residuals, _provenance(), _config())


def test_a_residual_export_missing_a_fold_stops_the_run_instead_of_dropping_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clause 29: a longer burn-in is a gap in the export, not a smaller fit.

    With one fold absent from the export every later fold's history is one shorter, so
    the ninth fold of the chain no longer qualifies. Quietly fitting on three folds
    instead of four would be dropping a fold nobody declared.
    """

    _install(monkeypatch)
    folds, residuals = _chain(missing="2021-22-gw04")
    with pytest.raises(SquadShadowError, match="missing folds this population expected"):
        fit_frozen_shift(folds, residuals, _provenance(), _config())


def test_a_fold_with_exactly_the_pinned_history_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor is the generator's own, so the boundary is where it says it is."""

    recorder = _install(monkeypatch)
    fold = _fold("2022-23", 10, prior=DEVELOPMENT_FOLD_IDS[:8])
    shift = fit_frozen_shift((fold,), _development_residuals(), _provenance(), _config())
    assert shift.fold_count == 1
    assert len(recorder.histories) == 1
