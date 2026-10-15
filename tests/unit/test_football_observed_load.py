"""Independent arithmetic and chronology checks for observed-record workload."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from squadopt.data.errors import DataError
from squadopt.features.football_load_inputs import (
    LoadFixture,
    native_joint_law_digest,
    validate_load_week,
)
from squadopt.features.football_observed_load import (
    FEATURE_NAMES,
    ObservedLoadCapturedNativeBasis,
    ObservedLoadNativeBasis,
    ObservedLoadOutcome,
    ObservedLoadProvenance,
    ObservedLoadRecord,
    ObservedLoadWeek,
    observed_load_digest,
    observed_load_features,
    read_observed_load_outcome,
    read_observed_load_snapshot,
    validate_observed_load_week,
)
from squadopt.prediction import football_observed_load as module
from squadopt.prediction.football_observed_load import (
    ObservedLoadExample,
    ObservedLoadModel,
    export_observed_load_serving_result,
    objective_gradient,
    read_observed_load_serving_result,
)

CUTOFF = "2026-10-02T00:00:00Z"


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def week(
    player: int = 1,
    *,
    target: bool = False,
    season: str | None = None,
    count: int = 1,
    missing: bool = False,
    minutes: float = 80,
) -> ObservedLoadWeek:
    decision = (
        datetime(2026, 10, 3, 9, tzinfo=UTC) if target else datetime(2024, 11, 1, 9, tzinfo=UTC)
    )
    if season == "2025-26":
        decision = decision.replace(year=2025)
    season = season or ("2026-27" if target else "2024-25")
    states = tuple(itertools.product(range(7), repeat=count))
    if count == 0:
        joint = (1.0,)
    elif count == 1:
        joint = (0.2, 0.1, 0.2, 0.2, 0.1, 0.1, 0.1)
    else:
        mass = {(0, 0): 0.2, (3, 3): 0.5, (4, 0): 0.2, (0, 4): 0.1}
        joint = tuple(mass.get(state, 0.0) for state in states)
    fixtures = tuple(
        LoadFixture(
            100 + i,
            stamp(decision + timedelta(hours=6, days=i)),
            10,
            20 + i,
            i % 2,
            tuple(
                math.fsum(p for state, p in zip(states, joint, strict=True) if state[i] == k)
                for k in range(7)
            ),
            (0, 30, 75, 90, 20, 65, 90),
        )
        for i in range(count)
    )
    source_recorded = stamp(decision - timedelta(hours=1)) if target else "2026-09-01T00:00:00Z"
    retrieved = stamp(decision - timedelta(minutes=45)) if target else "2026-09-02T00:00:00Z"
    generated = stamp(decision - timedelta(minutes=30)) if target else "2026-09-03T00:00:00Z"
    feature = stamp(decision - timedelta(minutes=15)) if target else stamp(decision)
    provenance = ObservedLoadProvenance(
        "prospective" if target else "public_revision_replay",
        "a" * 40,
        source_recorded,
        retrieved,
        generated,
        feature,
        (
            ("reported.csv", "a" * 64),
            ("original_finished.csv", "b" * 64),
            ("native.json", "c" * 64),
            ("calendar.csv", "d" * 64),
        ),
        "e" * 64,
        True,
        "operator private-use receipt",
    )
    native = ObservedLoadNativeBasis(
        fixtures,
        states,
        joint,
        native_joint_law_digest(fixtures, states, joint),
        "c" * 64,
        "native_minute_v1",
        stamp(decision - timedelta(hours=12)),
        stamp(decision - timedelta(days=2)),
        "f" * 40,
        stamp(decision - timedelta(days=1)),
        retrieved,
        True,
        (1,),
        "d" * 64,
        "original complete PL fixture calendar and native fit",
    )
    record = ObservedLoadRecord(
        "cup-1",
        "efl-cup",
        player,
        stamp(decision - timedelta(days=3)),
        None if missing else minutes,
        None if missing else minutes > 0,
        stamp(decision - timedelta(days=2)),
        "b" * 40,
        "b" * 64,
        "original fixture finished=True row",
        "a" * 64,
        2,
    )
    return ObservedLoadWeek(
        season,
        1,
        player,
        "MID",
        stamp(decision),
        stamp(decision + timedelta(hours=2)),
        ("efl-cup",),
        (record,),
        native,
        provenance,
    )


def outcome(source: ObservedLoadWeek, state: tuple[int, ...] | None = None) -> ObservedLoadOutcome:
    state = state if state is not None else (3,) * len(source.native.fixtures)
    minutes = tuple((0, 30, 75, 90, 20, 65, 90)[s] for s in state)
    starts = tuple(int(1 <= s <= 3) for s in state)
    settled = datetime.fromisoformat(source.decision_at.replace("Z", "+00:00")) + timedelta(days=3)
    return ObservedLoadOutcome(
        source,
        observed_load_digest(source),
        state,
        minutes,
        starts,
        stamp(settled),
        "2026-09-04T00:00:00Z",
        "2026-09-05T00:00:00Z",
        "9" * 64,
        "independent final FPL minutes and starts",
    )


def fit(rows: tuple[ObservedLoadOutcome, ...] | None = None, **options: Any) -> ObservedLoadModel:
    return ObservedLoadModel().fit(
        rows
        or (
            outcome(week()),
            outcome(week(2, minutes=0), (0,)),
            outcome(week(3, missing=True), (4,)),
        ),
        cutoff=CUTOFF,
        target_season="2026-27",
        target_gameweeks=(1,),
        **options,
    )


def test_exact_feature_inventory_keeps_unknown_and_zero_distinct() -> None:
    missing = observed_load_features(week(missing=True))
    zero = observed_load_features(week(minutes=0))
    assert len(FEATURE_NAMES) == 24
    assert missing[:8] == (1, 0, 1, None, 0, 1, None, None)
    assert zero[:8] == (1, 1, 0, 0, 1, 0, 0, None)
    assert observed_load_features(week())[:8] == (1, 1, 0, 80, 1, 0, 1, 72)
    empty = observed_load_features(replace(week(), records=()))
    assert empty[:8] == (0, 0, 0, None, 0, 0, None, None)


def test_windows_aggregate_only_named_records_without_imputing_missing() -> None:
    source = week()
    older = replace(
        source.records[0],
        fixture="cup-2",
        kickoff="2024-10-20T09:00:00Z",
        completed_by="2024-10-21T09:00:00Z",
        reported_minutes=None,
        confirmed_start=None,
    )
    oldest = replace(
        older,
        fixture="cup-3",
        kickoff="2024-10-10T09:00:00Z",
        completed_by="2024-10-11T09:00:00Z",
        reported_minutes=20,
        confirmed_start=False,
    )
    source = replace(source, records=(source.records[0], older, oldest))
    validate_observed_load_week(source)
    values = observed_load_features(source)
    assert values[:7] == (1, 1, 0, 80, 1, 0, 1)
    assert values[8:15] == (2, 1, 1, 80, 1, 1, 1)
    assert values[16:23] == (3, 2, 1, 100, 2, 1, 1)


def test_replay_provenance_does_not_claim_original_capture() -> None:
    source = week()
    validate_observed_load_week(source)
    assert source.provenance.source_recorded_at > source.decision_at
    assert source.native.recorded_at < source.decision_at
    with pytest.raises((ValueError, DataError), match="Prospective"):
        validate_observed_load_week(
            replace(source, provenance=replace(source.provenance, kind="prospective"))
        )


@pytest.mark.parametrize(
    "change",
    [
        {"reported_minutes": -1},
        {"reported_minutes": float("nan")},
        {"reported_minutes": True},
        {"confirmed_start": 1},
        {"player_code": 999},
        {"is_premier_league": True},
        {"competition": "unknown"},
        {"completed_by": "2024-11-01T09:00:00Z"},
        {"completed_by": "2024-10-28T09:00:00Z"},
        {"completion_revision": "invented"},
        {"completion_sha256": "7" * 64},
        {"source_sha256": "7" * 64},
        {"source_line": 0},
    ],
)
def test_bad_record_refuses(change: dict[str, Any]) -> None:
    source = week()
    with pytest.raises((ValueError, DataError)):
        validate_observed_load_week(
            replace(source, records=(replace(source.records[0], **change),))
        )


def test_duplicate_and_scope_and_complete_native_calendar_refuse() -> None:
    source = week()
    for changed in (
        replace(source, records=source.records * 2),
        replace(source, competitions=("prem",)),
        replace(source, coverage_kind="all_competitions_complete"),
        replace(source, minute_definition="physical_minutes"),
        replace(source, native=replace(source.native, calendar_complete=False)),
        replace(source, native=replace(source.native, law_sha256="0" * 64)),
    ):
        with pytest.raises((ValueError, DataError)):
            validate_observed_load_week(changed)
    with pytest.raises(DataError, match="frozen LoadWeek"):
        validate_load_week(source)  # type: ignore[arg-type]


def test_season_release_is_explicit_and_recorded() -> None:
    source = week(season="2025-26")
    with pytest.raises(ValueError, match="explicit released-season"):
        fit((outcome(source),))
    model = fit((outcome(source),), allow_released_2025_26=True)
    assert model.metadata.allow_released_2025_26 is True
    assert model.metadata.training_seasons == ("2025-26",)
    with pytest.raises(ValueError, match="Boolean"):
        fit((outcome(source),), allow_released_2025_26=1)


def test_snapshot_and_outcome_bytes_roundtrip_and_hash_check() -> None:
    source = week()
    raw = json.dumps(asdict(source)).encode()
    decoded = read_observed_load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest())
    assert decoded == source
    with pytest.raises(DataError, match="SHA256 mismatch"):
        read_observed_load_snapshot(raw + b" ", sha256=hashlib.sha256(raw).hexdigest())
    row = outcome(source)
    document = asdict(row)
    del document["week"]
    raw = json.dumps(document).encode()
    assert (
        read_observed_load_outcome(
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            week=source,
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweeks=(1,),
        )
        == row
    )


def test_target_header_refuses_before_outcome_byte_decode() -> None:
    source = week(target=True)
    with pytest.raises(ValueError, match="target and later outcome bytes"):
        read_observed_load_outcome(
            b"invalid JSON",
            sha256="0" * 64,
            week=source,
            cutoff="2026-11-01T00:00:00Z",
            target_season="2026-27",
            target_gameweeks=(1,),
        )


def test_all_headers_precede_any_labels() -> None:
    first = replace(outcome(week()), observed_states=object())  # type: ignore[arg-type]
    later = replace(week(), season="2026-27", gameweek=2)
    second = replace(outcome(week(2)), week=later)
    with pytest.raises(ValueError, match="target and later training"):
        fit((first, second))


def test_observed_label_must_match_fpl_minutes_and_native_support() -> None:
    row = outcome(week())
    for changed in (
        replace(row, credited_minutes=(59,)),
        replace(row, starts=(0,)),
        replace(row, input_sha256="8" * 64),
    ):
        with pytest.raises((ValueError, DataError)):
            fit((changed,))
    with pytest.raises(ValueError, match="no native support"):
        fit((outcome(week(count=2), (1, 1)),))


def test_objective_matches_independent_dense_softmax_and_numerical_gradient() -> None:
    context = np.array([1.0, -0.4])
    counts = np.array(
        [[0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 2, 0, 0, 0], [1, 0, 0, 0, 1, 0, 0]], dtype=float
    )
    native = np.array([0.3, 0.7, 0.0])
    example = ObservedLoadExample(context, counts, native, 1)
    beta = np.linspace(-0.3, 0.3, 14)
    matrix = np.array([np.concatenate([n * context for n in row]) for row in counts])
    weights = native * np.exp(matrix @ beta)
    expected = -math.log(weights[1] / sum(weights)) + 0.35 * float(beta @ beta)
    loss, gradient = objective_gradient(beta, (example,), 0.7)
    assert loss == pytest.approx(expected, abs=1e-14)
    for j in range(14):
        step = np.zeros(14)
        step[j] = 1e-6
        numerical = (
            objective_gradient(beta + step, (example,), 0.7)[0]
            - objective_gradient(beta - step, (example,), 0.7)[0]
        ) / 2e-6
        assert gradient[j] == pytest.approx(numerical, abs=2e-9)


def test_sparse_week_tilt_preserves_zeros_and_coherent_marginals() -> None:
    model = fit((outcome(week(count=2)), outcome(week(2, count=2, minutes=0), (0, 0))))
    source = week(target=True, count=2)
    predicted = model.predict(source)
    assert sum(predicted.probabilities) == pytest.approx(1)
    assert any(
        abs(p - q) > 1e-6
        for p, q in zip(predicted.probabilities, source.native.probabilities, strict=True)
    )
    for _state, old, new in zip(
        source.native.states, source.native.probabilities, predicted.probabilities, strict=True
    ):
        assert (old == 0) == (new == 0)
        if old:
            assert new > 0
    assert predicted.weekly_appearance == pytest.approx(1 - predicted.probabilities[0])
    for j in range(2):
        for k in range(7):
            assert predicted.fixture_probabilities[j][k] == pytest.approx(
                sum(
                    p
                    for state, p in zip(predicted.states, predicted.probabilities, strict=True)
                    if state[j] == k
                )
            )
    # Correlation survives; the result is not the product of separately tilted marginals.
    assert predicted.probabilities[3 * 7] == 0
    assert predicted.fixture_probabilities[0][3] * predicted.fixture_probabilities[1][0] > 0
    zero = model.predict(source, zero_coefficients=True)
    assert zero.probabilities == pytest.approx(source.native.probabilities, abs=1e-15)


def test_blank_week_stays_one_empty_state() -> None:
    model = fit((outcome(week(count=0)),))
    result = model.predict(week(target=True, count=0))
    assert result.states == ((),)
    assert result.probabilities == (1,)
    assert result.weekly_appearance == 0
    assert result.fixture_probabilities == ()


def test_transform_uses_training_only_and_unknown_is_not_zero() -> None:
    model = fit()
    index = FEATURE_NAMES.index("observed_non_pl_known_reported_minute_sum_7d")
    assert model.metadata.transform.known_counts[index] == 2
    assert model.metadata.transform.means[index] == 40
    before = model.metadata_json
    model.predict(week(target=True, minutes=200))
    assert model.metadata_json == before
    unsupported = fit((outcome(week(missing=True)),))
    with pytest.raises(ValueError, match="no observed training support"):
        unsupported.predict(week(target=True))
    assert unsupported.predict(
        week(target=True), zero_coefficients=True
    ).probabilities == pytest.approx(week(target=True).native.probabilities)


def test_failed_refit_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    model = fit()
    before = model.metadata_json
    prediction = model.predict(week(target=True))
    monkeypatch.setattr(
        module,
        "minimize",
        lambda *a, **kw: SimpleNamespace(
            success=False, x=np.zeros(len(module.DESIGN_NAMES)), nit=1
        ),
    )
    with pytest.raises(ValueError, match="optimizer"):
        model.fit((outcome(week()),), cutoff=CUTOFF, target_season="2026-27", target_gameweeks=(1,))
    assert model.metadata_json == before
    assert model.predict(week(target=True)) == prediction


def test_receipt_and_fitted_values_are_immutable() -> None:
    model = fit()
    assert hashlib.sha256(model.metadata_json.encode()).hexdigest() == model.model_sha256
    with pytest.raises(FrozenInstanceError):
        model.metadata.cutoff = "changed"  # type: ignore[misc]
    assert model._fitted is not None
    with pytest.raises(ValueError):
        model._fitted.coefficients.setflags(write=True)
    model._fitted = replace(model._fitted, metadata=replace(model.metadata, cutoff="changed"))
    with pytest.raises(ValueError, match="integrity"):
        model.predict(week(target=True))


@pytest.mark.parametrize(
    "options",
    [
        {"l2": True},
        {"l2": -1},
        {"l2": math.inf},
        {"max_iterations": 0},
        {"max_iterations": True},
        {"max_iterations": 1001},
    ],
)
def test_bad_optimizer_settings_refuse(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        fit(**options)


def test_prediction_requires_prospective_target_and_trained_scope() -> None:
    model = fit()
    with pytest.raises(ValueError, match="prospective"):
        model.predict(week())
    changed = replace(week(target=True), competitions=("efl-cup", "champions-league"))
    with pytest.raises(ValueError, match="trained competition scope"):
        model.predict(changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("history_completed_by", "2024-11-01T09:00:00Z"),
        ("recorded_at", "2024-11-01T10:00:00Z"),
        ("retrieved_at", "2024-10-31T09:00:00Z"),
        ("covered_gameweeks", (2,)),
        ("basis_sha256", "7" * 64),
        ("probabilities", (1.0,)),
        ("states", ((0,),)),
    ],
)
def test_native_basis_cannot_relax_original_calendar_or_information_clocks(
    field: str, value: Any
) -> None:
    source = week()
    with pytest.raises((ValueError, DataError)):
        validate_observed_load_week(
            replace(source, native=replace(source.native, **{field: value}))
        )


def test_source_completion_bound_must_precede_source_recording() -> None:
    source = week(target=True)
    earlier = replace(source.provenance, source_recorded_at="2026-09-29T09:00:00Z")
    with pytest.raises(ValueError, match="prior completed"):
        validate_observed_load_week(replace(source, provenance=earlier))


def test_reader_refuses_duplicate_fields_and_nonarray_source_inventory() -> None:
    raw = b'{"season":"2024-25","season":"2025-26"}'
    with pytest.raises(DataError):
        read_observed_load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest())
    document = asdict(week())
    document["records"] = {"unexpected": "mapping"}
    raw = json.dumps(document).encode()
    with pytest.raises(DataError, match="JSON array"):
        read_observed_load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest())


def test_duplicate_player_week_and_inconsistent_original_decision_refuse() -> None:
    first = outcome(week())
    with pytest.raises(ValueError, match="Duplicate"):
        fit((first, first))
    second = week(2)
    second = replace(second, decision_at="2024-11-01T09:15:00Z")
    with pytest.raises(ValueError, match="one original decision"):
        fit((first, outcome(second)))


def test_reported_zero_does_not_claim_zero_physical_time_or_infer_start_status() -> None:
    source = week(minutes=0)
    source = replace(source, records=(replace(source.records[0], confirmed_start=True),))
    validate_observed_load_week(source)
    assert observed_load_features(source)[:8] == (1, 1, 0, 0, 1, 0, 1, None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("success", None),
        ("success", 1),
        ("success", "true"),
        ("success", np.bool_(True)),
        ("status", None),
        ("status", True),
        ("status", 1),
        ("status", np.int64(0)),
        ("nit", None),
        ("nit", True),
        ("nit", -1),
        ("nit", 1001),
        ("nit", 1.5),
        ("nit", np.int64(1)),
        ("x", None),
        ("x", [0]),
        ("x", [[0] * len(module.DESIGN_NAMES)]),
        ("x", [math.nan] * len(module.DESIGN_NAMES)),
        ("x", [math.inf] * len(module.DESIGN_NAMES)),
        ("x", [21] * len(module.DESIGN_NAMES)),
        ("x", [True] + [0.0] * (len(module.DESIGN_NAMES) - 1)),
        ("x", [0j] * len(module.DESIGN_NAMES)),
        ("x", ["0"] * len(module.DESIGN_NAMES)),
        ("x", [object()] * len(module.DESIGN_NAMES)),
    ],
)
def test_malformed_optimizer_receipt_cannot_replace_model(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    model = fit()
    before = model.metadata_json, model.model_sha256, model.predict(week(target=True))
    result = {"success": True, "status": 0, "nit": 1, "x": np.zeros(len(module.DESIGN_NAMES))}
    if value is None:
        result.pop(field)
    else:
        result[field] = value
    monkeypatch.setattr(module, "minimize", lambda *a, **kw: SimpleNamespace(**result))
    with pytest.raises(ValueError, match="optimizer"):
        model.fit((outcome(week()),), cutoff=CUTOFF, target_season="2026-27", target_gameweeks=(1,))
    assert (model.metadata_json, model.model_sha256, model.predict(week(target=True))) == before


@pytest.mark.parametrize("season", ["2023-24", "2026-27"])
def test_blank_week_cannot_hide_decision_from_another_season(season: str) -> None:
    with pytest.raises(ValueError, match="decision/deadline"):
        validate_observed_load_week(replace(week(count=0), season=season))


@pytest.mark.parametrize(
    "decision,valid",
    [
        ("2024-07-01T00:00:00Z", True),
        ("2024-06-30T23:59:59Z", False),
        ("2025-06-30T21:59:59Z", True),
        ("2025-06-30T22:00:00Z", False),
        ("2025-07-01T00:00:00Z", False),
    ],
)
def test_season_boundary_is_july_first_inclusive_next_july_exclusive(
    decision: str, valid: bool
) -> None:
    source = week(count=0)
    clock = datetime.fromisoformat(decision.replace("Z", "+00:00"))
    source = replace(
        source,
        decision_at=decision,
        deadline_at=stamp(clock + timedelta(hours=2)),
        records=(),
        provenance=replace(source.provenance, feature_cutoff=decision),
        native=replace(
            source.native,
            recorded_at=stamp(clock - timedelta(days=1)),
            fit_information_cutoff=stamp(clock - timedelta(hours=12)),
            history_completed_by=stamp(clock - timedelta(days=2)),
        ),
    )
    if valid:
        validate_observed_load_week(source)
    else:
        with pytest.raises(ValueError, match="decision/deadline"):
            validate_observed_load_week(source)


def test_outcome_header_clocks_precede_label_array_conversion() -> None:
    source = week()
    document = asdict(outcome(source))
    document.pop("week")
    document["settled_at"] = "2024-01-01T00:00:00Z"
    document["credited_minutes"] = "invalid label array"
    raw = json.dumps(document).encode()
    with pytest.raises(ValueError, match="outcome chronology"):
        read_observed_load_outcome(
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            week=source,
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweeks=(1,),
        )


def captured_week(*, count: int = 1) -> ObservedLoadWeek:
    source = week(target=True, count=count)
    values = asdict(source.native)
    values.pop("original_revision")
    values["fixtures"] = source.native.fixtures
    native = ObservedLoadCapturedNativeBasis(
        **values,
        source_snapshot_id="fpl-live-20261002T090000Z-ffffffffffff",
        source_fingerprint="f" * 64,
        native_generated_at="2026-10-03T08:20:00Z",
    )
    return replace(
        source,
        native=native,
        provenance=replace(
            source.provenance,
            source_hashes=(*source.provenance.source_hashes, ("snapshot_fingerprint", "f" * 64)),
        ),
    )


def test_captured_native_roundtrip_and_legacy_law_equivalence() -> None:
    source = captured_week(count=2)
    raw = json.dumps(asdict(source)).encode()
    assert read_observed_load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest()) == source
    assert "original_revision" not in asdict(source.native)
    model = fit((outcome(week(count=2)),))
    legacy = model.predict(week(target=True, count=2))
    captured = model.predict(source)
    assert captured.probabilities == legacy.probabilities
    assert captured.fixture_probabilities == legacy.fixture_probabilities
    assert captured.input_sha256 != legacy.input_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "captured_snapshot_v2"),
        ("source_snapshot_id", "fpl-live-20261003T090000Z-ffffffffffff"),
        ("source_snapshot_id", "fpl-live-20261002T090000Z-aaaaaaaaaaaa"),
        ("source_fingerprint", "f" * 12),
        ("source_fingerprint", "8" * 64),
        ("recorded_at", "2026-10-03T08:16:00Z"),
        ("retrieved_at", "2026-10-03T08:21:00Z"),
        ("native_generated_at", "2026-10-03T08:14:00Z"),
        ("native_generated_at", "2026-10-03T08:31:00Z"),
        ("fit_information_cutoff", "2026-10-03T08:21:00Z"),
    ],
)
def test_captured_native_identity_and_declared_clocks_refuse(field: str, value: Any) -> None:
    source = captured_week()
    with pytest.raises((ValueError, DataError)):
        validate_observed_load_week(
            replace(source, native=replace(source.native, **{field: value}))
        )


def test_captured_is_prospective_only_and_disjoint_from_git_schema() -> None:
    source = captured_week()
    replay = replace(
        source,
        provenance=replace(
            source.provenance,
            kind="public_revision_replay",
            retrieved_at="2026-10-04T00:00:00Z",
            generated_at="2026-10-05T00:00:00Z",
        ),
    )
    with pytest.raises(ValueError, match="prospective source variant"):
        validate_observed_load_week(replay)
    for base, extra in ((source, {"original_revision": "a" * 40}), (week(), {"version": "x"})):
        document = asdict(base)
        document["native"].update(extra)
        raw = json.dumps(document).encode()
        with pytest.raises((ValueError, DataError)):
            read_observed_load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("count", [0, 1, 2])
def test_compact_serving_preserves_fitted_predictions_without_fitting(
    count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fit((outcome(week(count=count)),))
    before = model.metadata_json
    raw = export_observed_load_serving_result(model).encode()
    document = json.loads(raw)
    assert "training_receipts" not in document
    assert "optimizer_iterations" not in document
    assert document["model_sha256"] == hashlib.sha256(before.encode()).hexdigest()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Serving cannot fit.")

    monkeypatch.setattr(module, "minimize", forbidden)
    serving = read_observed_load_serving_result(raw, sha256=hashlib.sha256(raw).hexdigest())
    assert not hasattr(serving, "fit")
    for source in (week(target=True, count=count), captured_week(count=count)):
        assert serving.predict(source) == model.predict(source)
        assert serving.predict(source, zero_coefficients=True) == model.predict(
            source, zero_coefficients=True
        )
    assert model.metadata_json == before
    with pytest.raises(FrozenInstanceError):
        serving.parameters.cutoff = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError):
        serving._coefficients.setflags(write=True)
    with pytest.raises(ValueError, match="integrity"):
        replace(serving, result_json=serving.result_json + " ").predict(captured_week(count=count))


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "unexpected_v1"),
        ("model_sha256", "a" * 63),
        ("target_gameweeks", [True]),
        ("allow_released_2025_26", 1),
        ("coefficients", [0.0]),
        ("coefficients", [True] * len(module.DESIGN_NAMES)),
        ("coefficients", [float("nan")] * len(module.DESIGN_NAMES)),
        ("coefficients", [21.0] * len(module.DESIGN_NAMES)),
        ("coefficients", [10**400] + [0.0] * (len(module.DESIGN_NAMES) - 1)),
        ("observed_competition_scopes", []),
        ("observed_competition_scopes", [["efl-cup", "efl-cup"]]),
        ("observed_competition_scopes", [["efl-cup"], ["efl-cup"]]),
        ("observed_competition_scopes", [["z", "a"]]),
    ],
)
def test_serving_reader_refuses_malformed_parameters(field: str, value: Any) -> None:
    document = json.loads(export_observed_load_serving_result(fit()))
    document[field] = value
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises((ValueError, DataError)):
        read_observed_load_serving_result(raw, sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "field,value",
    [
        ("means", []),
        ("means", [-1.0] * 24),
        ("scales", [0.0] * 24),
        ("known_counts", [True] * 24),
        ("known_counts", [-1] * 24),
        ("known_counts", [0] * 24),
    ],
)
def test_serving_reader_refuses_invalid_transform(field: str, value: Any) -> None:
    document = json.loads(export_observed_load_serving_result(fit()))
    document["transform"][field] = value
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError):
        read_observed_load_serving_result(raw, sha256=hashlib.sha256(raw).hexdigest())


def test_serving_bytes_inventory_digest_and_canonical_identity() -> None:
    raw = export_observed_load_serving_result(fit()).encode()
    with pytest.raises(ValueError, match="digest"):
        read_observed_load_serving_result(raw + b" ", sha256=hashlib.sha256(raw).hexdigest())
    for bad in (
        raw + b" ",
        raw.replace(b"{", b'{"version":"duplicate",', 1),
        raw.replace(b"{", b'{"unexpected":0,', 1),
        b"null",
        b"not JSON",
    ):
        with pytest.raises(ValueError):
            read_observed_load_serving_result(bad, sha256=hashlib.sha256(bad).hexdigest())


def test_serving_retains_prediction_target_scope_and_support_guards() -> None:
    raw = export_observed_load_serving_result(fit((outcome(week(missing=True)),))).encode()
    serving = read_observed_load_serving_result(raw, sha256=hashlib.sha256(raw).hexdigest())
    for source, message in (
        (week(), "prospective"),
        (replace(captured_week(), gameweek=2), "calendar"),
        (replace(captured_week(), competitions=("efl-cup", "cup")), "scope"),
        (captured_week(), "training support"),
    ):
        with pytest.raises(ValueError, match=message):
            serving.predict(source)
