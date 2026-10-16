"""Invented replay receipts, chronology refusals and legacy likelihood parity."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from tests.unit.test_football_score_state import fixture, observation

from squadopt.features.football_score_replay import (
    REPLAY_FIT_VERSION,
    REQUIRED_SOURCE_HASHES,
    ScoreReplayBasis,
    ScoreReplayObservation,
    ScoreReplayPlayer,
    ScoreReplayProvenance,
    score_replay_basis_digest,
    validate_score_replay_basis,
    validate_score_replay_header,
    validate_score_replay_observation,
)
from squadopt.features.football_score_state_inputs import (
    PhysicalPeriod,
    TrainingScoreFixture,
    read_score_snapshot,
    score_input_digest,
    validate_score_fixture,
)
from squadopt.prediction.football_score_state import (
    ScoreReplayMetadata,
    ScoreStateMetadata,
    ScoreStateModel,
    training_design,
)

CUTOFF = "2026-09-20T00:00:00Z"
HEADER = dict(fit_cutoff=CUTOFF, target_season="2026-27", target_gameweeks=(6, 7))


def replay(
    source: TrainingScoreFixture | None = None, *, released: bool = False
) -> ScoreReplayObservation:
    row = observation() if source is None else source
    original = row.input
    if released:
        original = replace(
            original,
            season="2025-26",
            decision_at=original.decision_at.replace("2024-", "2025-"),
            deadline_at=original.deadline_at.replace("2024-", "2025-"),
            kickoff=original.kickoff.replace("2024-", "2025-"),
        )
        row = replace(row, settled_at=row.settled_at.replace("2024-", "2025-"))
    decision = datetime.fromisoformat(original.decision_at.replace("Z", "+00:00"))

    def before(hours: int) -> str:
        return (decision - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    hashes = {name: hashlib.sha256(name.encode()).hexdigest() for name in REQUIRED_SOURCE_HASHES}
    provenance = ScoreReplayProvenance(
        revision="c" * 40,
        recorded_at=before(3),
        retrieved_at="2026-09-15T00:00:00Z",
        generated_at="2026-09-16T00:00:00Z",
        feature_cutoff=before(1),
        native_fit_information_cutoff=before(2),
        latest_native_history_settled_at=before(24),
        duration_history_latest_settled_at=before(24),
        duration_history_fixtures=(
            ("2022-23", 38, 999, "2023-05-28T15:30:00Z", "2023-05-28T19:00:00Z"),
        ),
        source_hashes=tuple(sorted(hashes.items())),
        native_implementation_sha256="a" * 64,
        duration_implementation_sha256="b" * 64,
        model_use_approved=True,
        model_use_evidence_ref="invented-operator-receipt",
    )
    basis = ScoreReplayBasis(
        original.season,
        original.gameweek,
        original.fixture_id,
        original.decision_at,
        original.kickoff,
        original.kickoff,
        original.home_club_code,
        original.away_club_code,
        original.native_home_goals,
        original.native_away_goals,
        original.forecast_duration,
        original.clock_version,
        tuple(ScoreReplayPlayer(p.player_code, p.club_code, p.position) for p in original.players),
        original.native_model_version,
        hashes["native_baseline.json"],
        hashes["duration_forecast.json"],
        provenance,
    )
    return ScoreReplayObservation(
        basis,
        row.goals,
        row.periods,
        row.actual_duration,
        row.final_home_goals,
        row.final_away_goals,
        row.fpl_credits,
        row.exposures,
        row.settled_at,
        row.outcome_sha256,
        "2026-09-15T00:00:00Z",
        "2026-09-17T00:00:00Z",
        "invented-independent-official-credits",
    )


def provenance(row: ScoreReplayObservation, **changes: Any) -> ScoreReplayObservation:
    return replace(
        row, basis=replace(row.basis, provenance=replace(row.basis.provenance, **changes))
    )


def fit(rows: tuple[Any, ...], **options: Any) -> ScoreStateModel:
    return ScoreStateModel().fit(
        rows,
        cutoff=CUTOFF,
        target_season="2026-27",
        target_gameweeks=(6, 7),
        allowed_seasons=options.pop("allowed_seasons", ("2024-25",)),
        **options,
    )


def test_replay_is_frozen_without_a_synthetic_predecision_player_law() -> None:
    row = replay()
    validate_score_replay_observation(row, **HEADER)
    assert set(asdict(row.basis.players[0])) == {"player_code", "club_code", "position"}
    with pytest.raises(FrozenInstanceError):
        row.basis.native_home_goals = 7  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        row.basis.provenance.revision = "d" * 40  # type: ignore[misc]


def test_likelihood_uses_forecast_denominator_and_actual_exposure_for_both_contracts() -> None:
    legacy = observation(sequence=((10, 1), (32, 2), (80, 1)), actual=104)
    row = replay(legacy)
    validate_score_replay_observation(row, **HEADER)
    design = training_design(row)
    assert design == training_design(legacy)
    assert design.event_log_offsets == pytest.approx((math.log(1 / 96),) * 3)
    assert math.fsum(design.exposure_masses) == pytest.approx(2 * 104 / 96)


def test_equal_realized_and_forecast_duration_is_allowed_with_distinct_prior_history() -> None:
    row = replay()
    assert row.actual_duration == row.basis.forecast_duration
    validate_score_replay_observation(row, **HEADER)


def test_legacy_default_metadata_and_hash_remain_byte_identical() -> None:
    rows = tuple(observation(index) for index in range(3))
    default = fit(rows)
    explicit = fit(rows, allow_released_2025_26=False)
    assert type(default.metadata) is ScoreStateMetadata
    assert default.metadata_json == explicit.metadata_json
    assert default.model_sha256 == explicit.model_sha256
    assert "fit_contract" not in json.loads(default.metadata_json)
    assert default.metadata.training_receipts[0][0] == score_input_digest(rows[0].input)


def test_replay_metadata_serialization_hash_and_predict_reads_are_compatible() -> None:
    legacy_rows = tuple(observation(index) for index in range(3))
    rows = tuple(replay(row) for row in legacy_rows)
    legacy, model = fit(legacy_rows), fit(rows)
    assert type(model.metadata) is ScoreReplayMetadata
    assert model.metadata.coefficients == legacy.metadata.coefficients
    assert model.metadata.objective == legacy.metadata.objective
    data = json.loads(model.metadata_json)
    assert data["fit_contract"] == REPLAY_FIT_VERSION
    assert data["allow_released_2025_26"] is False
    assert data["replay_receipts"][0][0] == score_replay_basis_digest(rows[0].basis)
    assert data["replay_receipts"][0][1]["retrieved_at"] == "2026-09-15T00:00:00Z"
    assert hashlib.sha256(model.metadata_json.encode()).hexdigest() == model.model_sha256
    target = fixture(target=True)
    old, new = legacy.predict(target), model.predict(target)
    assert old.home_physical_goals == new.home_physical_goals
    assert old.away_physical_goals == new.away_physical_goals
    assert old.player_survival == new.player_survival
    assert old.input_sha256 == new.input_sha256
    assert new.model_sha256 == model.model_sha256 != old.model_sha256


def test_mixed_legacy_and_replay_rows_retain_both_training_receipts() -> None:
    first, second = observation(), replay(observation(1))
    model = fit((first, second))
    assert len(model.metadata.training_receipts) == 2
    assert isinstance(model.metadata, ScoreReplayMetadata)
    assert len(model.metadata.replay_receipts) == 1


def test_released_season_requires_explicit_training_opt_in_and_records_it() -> None:
    row = replay(released=True)
    with pytest.raises(ValueError, match="explicit training opt-in"):
        validate_score_replay_observation(row, **HEADER)
    with pytest.raises(ValueError, match="protected"):
        fit((row,), allowed_seasons=("2025-26",))
    model = fit((row,), allowed_seasons=("2025-26",), allow_released_2025_26=True)
    assert isinstance(model.metadata, ScoreReplayMetadata)
    assert model.metadata.allow_released_2025_26 is True
    assert len(model.metadata.replay_receipts) == 1


@pytest.mark.parametrize("option", [1, "true", None])
def test_release_opt_in_is_a_boolean(option: Any) -> None:
    with pytest.raises(ValueError, match="Boolean"):
        fit((replay(),), allow_released_2025_26=option)


def test_replay_opt_in_does_not_relax_live_fixture_or_raw_snapshot_reader() -> None:
    source = replace(fixture(), season="2025-26")
    with pytest.raises(ValueError, match="Protected"):
        validate_score_fixture(source)
    with pytest.raises(ValueError, match="Protected"):
        fit(
            (replace(observation(), input=source),),
            allowed_seasons=("2025-26",),
            allow_released_2025_26=True,
        )
    with pytest.raises(ValueError, match="Protected"):
        read_score_snapshot(
            b"not-json",
            sha256="a" * 64,
            season="2025-26",
            gameweek=1,
            fixture_id=1,
            decision_at=source.decision_at,
            deadline_at=source.deadline_at,
            native_basis_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"recorded_at": "2026-09-15T00:00:00Z"}, "recording"),
        ({"retrieved_at": "2024-01-01T00:00:00Z"}, "recording"),
        ({"generated_at": "2026-09-21T00:00:00Z"}, "precede fitting"),
        ({"latest_native_history_settled_at": "2026-01-01T00:00:00Z"}, "histories"),
        ({"native_fit_information_cutoff": "2026-01-01T00:00:00Z"}, "histories"),
        ({"duration_history_latest_settled_at": "2026-01-01T00:00:00Z"}, "histories"),
        ({"revision": "main"}, "Git revision"),
        ({"native_implementation_sha256": "unknown"}, "SHA256"),
        ({"model_use_approved": False}, "operator"),
    ],
)
def test_all_population_headers_precede_any_labels(change: dict[str, Any], match: str) -> None:
    poisoned = replace(replay(), actual_duration=object())
    second = provenance(replay(observation(1)), **change)
    with pytest.raises(ValueError, match=match):
        fit((poisoned, second))


def test_target_population_and_outcome_source_headers_precede_all_labels() -> None:
    poisoned = replace(replay(), goals=object())
    row = replay(observation(1))
    for changed, match in (
        (replace(row, basis=replace(row.basis, season="2026-27", gameweek=6)), "excluded"),
        (replace(row, outcome_generated_at=CUTOFF), "precede fitting"),
        (replace(row, outcome_sha256="unknown"), "SHA256"),
    ):
        with pytest.raises(ValueError, match=match):
            fit((poisoned, changed))


@pytest.mark.parametrize(
    "inventory",
    [
        (),
        (("2024-25", 1, 1),),
        (("2024-25", 2, 999),),
        (("2025-26", 1, 999),),
        (("2023-24", 1, 999), ("2023-24", 2, 999)),
    ],
)
def test_duration_forecast_refuses_empty_target_future_or_duplicate_history(inventory) -> None:
    inventory = tuple(
        (*item, f"{item[0][:4]}-08-01T12:00:00Z", f"{item[0][:4]}-08-01T15:00:00Z")
        for item in inventory
    )
    with pytest.raises(ValueError, match=r"[Dd]uration"):
        validate_score_replay_basis(provenance(replay(), duration_history_fixtures=inventory).basis)


def test_target_fixture_cannot_be_hidden_under_an_earlier_gameweek() -> None:
    row = replay(observation(3))
    changed = provenance(
        row,
        duration_history_fixtures=(
            ("2024-25", 1, row.basis.fixture_id, "2024-08-01T12:00:00Z", "2024-08-01T15:00:00Z"),
        ),
    )
    with pytest.raises(ValueError, match="target"):
        validate_score_replay_basis(changed.basis)


def test_source_hash_bindings_are_required_unique_and_sealed() -> None:
    row = replay()
    hashes = row.basis.provenance.source_hashes
    for changed, match in (
        (provenance(row, source_hashes=hashes[1:]), "requires original"),
        (provenance(row, source_hashes=(*hashes, hashes[0])), "unique"),
        (replace(row, basis=replace(row.basis, native_basis_sha256="f" * 64)), "bindings"),
        (replace(row, basis=replace(row.basis, duration_forecast_sha256="f" * 64)), "bindings"),
    ):
        with pytest.raises(ValueError, match=match):
            validate_score_replay_basis(changed.basis)
    altered = provenance(row, native_implementation_sha256="f" * 64)
    assert score_replay_basis_digest(altered.basis) != score_replay_basis_digest(row.basis)


@pytest.mark.parametrize("targets", [(), (2, 1), (1, 1), (True,), ("1",), ([],)])
def test_target_inventory_validation_fails_closed(targets: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError):
        validate_score_replay_header(replay(), **{**HEADER, "target_gameweeks": targets})


def test_replay_does_not_change_physical_clock_or_fpl_credit_checks() -> None:
    row = replay()
    invalid = (
        (replace(row, dismissal_events=("red-card",)), "Dismissal"),
        (replace(row, periods=(PhysicalPeriod(1, 45), PhysicalPeriod(2, 45))), "reconcile"),
        (replace(row, goals=(replace(row.goals[0], elapsed=11), *row.goals[1:])), "clock"),
        (replace(row, exposures=row.exposures[:-1]), "complete original"),
        (replace(row, fpl_credits=()), "cover every"),
        (replace(row, basis=replace(row.basis, clock_version="rounded_minutes")), "physical clock"),
    )
    for changed, match in invalid:
        with pytest.raises(ValueError, match=match):
            validate_score_replay_observation(changed, **HEADER)


def test_malformed_model_and_roster_labels_refuse_as_header_errors() -> None:
    row = replay()
    invalid = (
        replace(row.basis, native_model_version=[]),
        replace(
            row.basis,
            players=(replace(row.basis.players[0], position=[]), *row.basis.players[1:]),
        ),
    )
    for basis in invalid:
        with pytest.raises(ValueError, match="nonempty"):
            validate_score_replay_basis(basis)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gameweek_first_kickoff", "2024-08-31T12:00:00Z"),
        ("gameweek_first_kickoff", "2024-09-01T13:00:00Z"),
        ("season", "2023-24"),
    ],
)
def test_each_calendar_clause_refuses_independently(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="calendar disagree"):
        validate_score_replay_basis(replace(replay().basis, **{field: value}))


def test_distinct_clubs_and_each_roster_clause_refuse_independently() -> None:
    basis = replay().basis
    with pytest.raises(ValueError, match="distinct clubs"):
        validate_score_replay_basis(replace(basis, away_club_code=basis.home_club_code))
    first, *rest = basis.players
    for players in (
        (first, first, *rest),
        (replace(first, club_code=999), *rest),
        (replace(first, position="manager"), *rest),
    ):
        with pytest.raises(ValueError, match="contradictory identities"):
            validate_score_replay_basis(replace(basis, players=players))
    with pytest.raises(ValueError, match="both original clubs"):
        validate_score_replay_basis(replace(basis, players=basis.players[:2]))
    with pytest.raises(ValueError, match="supported frozen provenance"):
        validate_score_replay_basis(
            provenance(replay(), version="football_score_public_revision_replay_v1").basis
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"feature_cutoff": "2024-08-31T13:00:00Z"},
        {"generated_at": "2026-09-14T23:59:59Z"},
    ],
)
def test_feature_decision_and_acquisition_generation_clauses_are_independent(changes) -> None:
    with pytest.raises(ValueError, match="recording, reference"):
        validate_score_replay_basis(provenance(replay(), **changes).basis)


@pytest.mark.parametrize(
    "changes",
    [
        {"settled_at": "2024-09-01T12:00:00Z"},
        {"settled_at": "2026-09-15T01:00:00Z"},
        {"outcome_retrieved_at": "2026-09-18T00:00:00Z"},
        {"outcome_generated_at": CUTOFF},
    ],
)
def test_each_outcome_chronology_clause_refuses_before_labels(changes) -> None:
    row = replace(replay(), goals=object(), **changes)
    with pytest.raises(ValueError, match="precede fitting"):
        validate_score_replay_observation(row, **HEADER)


def test_duration_history_requires_actual_clocks_even_for_an_earlier_gameweek() -> None:
    row = replay(observation(19))
    basis = replace(row.basis, gameweek=20)
    for kickoff, completed in (
        (basis.decision_at, basis.kickoff),
        ("2024-08-01T12:00:00Z", "2024-08-01T12:00:00Z"),
        ("2023-08-01T12:00:00Z", "2023-08-01T15:00:00Z"),
    ):
        changed = replace(
            basis.provenance, duration_history_fixtures=(("2024-25", 19, 999, kickoff, completed),)
        )
        with pytest.raises(ValueError, match="chronology"):
            validate_score_replay_basis(replace(basis, provenance=changed))
    with pytest.raises(ValueError, match="completion bound"):
        validate_score_replay_basis(
            replace(
                basis,
                provenance=replace(
                    basis.provenance, duration_history_fixtures=(("2024-25", 19, 999),)
                ),
            )
        )


def test_replay_digest_and_fitted_receipts_canonicalize_equivalent_utc_and_hash_order() -> None:
    row = replay()
    p = row.basis.provenance
    changes = {
        name: getattr(p, name).replace("Z", "+00:00")
        for name in (
            "recorded_at",
            "retrieved_at",
            "generated_at",
            "feature_cutoff",
            "native_fit_information_cutoff",
            "latest_native_history_settled_at",
            "duration_history_latest_settled_at",
        )
    }
    changed = provenance(
        row,
        **changes,
        source_hashes=tuple(reversed(p.source_hashes)),
        duration_history_fixtures=tuple(
            (*item[:3], item[3].replace("Z", "+00:00"), item[4].replace("Z", "+00:00"))
            for item in p.duration_history_fixtures
        ),
    )
    changed = replace(
        changed,
        basis=replace(
            changed.basis,
            decision_at=changed.basis.decision_at.replace("Z", "+00:00"),
            gameweek_first_kickoff=changed.basis.gameweek_first_kickoff.replace("Z", "+00:00"),
            kickoff=changed.basis.kickoff.replace("Z", "+00:00"),
        ),
    )
    assert score_replay_basis_digest(row.basis) == score_replay_basis_digest(changed.basis)
    assert fit((row,)).metadata_json == fit((changed,)).metadata_json
