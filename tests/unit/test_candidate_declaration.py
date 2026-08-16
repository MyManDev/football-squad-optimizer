"""Tests for the Issue #43 declaration that Stage A freezes.

A pre-registration is only worth the discipline if the recorded fingerprint actually
binds the thing that runs. So these tests check the declaration matches the candidate's
own constants, that the fingerprint moves when any declared input moves, and that it does
not move for reasons nobody decided.
"""

import pytest
from scripts.freeze_candidate_declaration import (
    CANDIDATE_ID,
    FROZEN_COMPONENTS,
    WINDOW,
    benchmark_config,
    declaration,
    document,
    markdown,
)

from squadopt.backtest.learned_candidate import (
    LEARNED_RATE_FEATURE_CONTRACT_VERSION,
    LEARNED_RATE_MODEL_NAME,
    LEARNED_RATE_MODEL_VERSION,
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
)
from squadopt.backtest.production_benchmark import (
    PRODUCTION_LABEL,
    CandidateDeclaration,
    _validate_candidate_provenance,
)
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.prediction.learned_rate import rate_input_columns

# --- the declaration describes the candidate that will run ------------------


def test_the_declared_identity_is_the_candidate_builder_s_own() -> None:
    """A transcribed identity is exactly how a declaration and a run drift apart."""

    declared = declaration()

    assert declared.model_name == LEARNED_RATE_MODEL_NAME
    assert declared.model_version == LEARNED_RATE_MODEL_VERSION
    assert declared.feature_contract_version == LEARNED_RATE_FEATURE_CONTRACT_VERSION


def test_the_changed_component_is_singular() -> None:
    assert declaration().changed_component == "expected_points_rate"


def test_the_changed_component_is_not_also_claimed_frozen() -> None:
    assert declaration().changed_component not in FROZEN_COMPONENTS


def test_the_frozen_set_names_every_component_the_checklist_pins() -> None:
    required = {
        "expected_minutes_stage",
        "cold_start_ladder",
        "availability_post_processing",
        "two_stage_combination",
        "feature_window_mapping",
        "opening_price_prior",
        "optimization_contract",
        "promotion_gates",
        "evaluation_objective",
    }

    assert required <= set(declaration().frozen_components)


def test_the_evaluation_objective_is_the_frozen_single_gameweek_one() -> None:
    assert declaration().evaluation_objective == "single_gameweek_realized_squad_points_v1"


def test_the_benchmark_config_carries_this_declaration() -> None:
    assert benchmark_config().candidate_declaration == declaration()


def test_the_development_seasons_exclude_the_locked_holdout() -> None:
    assert "2025-26" not in benchmark_config().seasons


# --- the fingerprints bind what they claim to bind --------------------------


def test_the_declaration_fingerprint_is_stable_across_calls() -> None:
    assert declaration().declaration_fingerprint == declaration().declaration_fingerprint


def test_the_configuration_fingerprint_is_stable_across_calls() -> None:
    assert benchmark_config().configuration_fingerprint == (
        benchmark_config().configuration_fingerprint
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("candidate_id", "something_else"),
        ("model_version", "learned-rate-v99"),
        ("feature_contract_version", "other-features-v1"),
        ("changed_component", "expected_minutes"),
        ("change_summary", "a different summary"),
    ],
)
def test_changing_any_declared_field_moves_the_fingerprint(field: str, value: str) -> None:
    """Without this, a freeze could be edited after review and still look honoured."""

    original = declaration()
    altered = CandidateDeclaration(
        **{
            **{
                name: getattr(original, name)
                for name in original.__dataclass_fields__
                if name != "contract_version"
            },
            field: value,
        }
    )

    assert altered.declaration_fingerprint != original.declaration_fingerprint


def test_changing_the_rate_window_moves_the_configuration_fingerprint() -> None:
    from dataclasses import replace

    from squadopt.prediction.production import ProductionProjectionConfig

    original = benchmark_config()
    altered = replace(
        original,
        production_config=ProductionProjectionConfig(
            rate_window=WINDOW + 1, minutes=original.production_config.minutes
        ),
    )

    assert altered.configuration_fingerprint != original.configuration_fingerprint


# --- the provenance check the benchmark will apply --------------------------


class _Fold:
    def __init__(self, metadata: dict[str, object]) -> None:
        self.fold_id = "2021-22-gw02"
        self.metadata = metadata


def _fold(**overrides: object) -> _Fold:
    declared = declaration()
    return _Fold(
        {
            "prediction_model_name": declared.model_name,
            "prediction_model_version": declared.model_version,
            "prediction_feature_contract_version": declared.feature_contract_version,
            **overrides,
        }
    )


def test_a_snapshot_matching_the_declaration_passes_the_benchmark_check() -> None:
    _validate_candidate_provenance((_fold(),), declaration())  # type: ignore[arg-type]


def test_a_snapshot_naming_another_model_stops_the_run() -> None:
    with pytest.raises(BacktestConfigurationError, match="does not match its declaration"):
        _validate_candidate_provenance(
            (_fold(prediction_model_version="learned-rate-v9"),),  # type: ignore[arg-type]
            declaration(),
        )


def test_the_challenger_still_occupies_the_production_report_slot() -> None:
    """Backward compatibility the benchmark relies on; a rename would break the report."""

    assert PRODUCTION_LABEL == "production"


# --- the reviewable record --------------------------------------------------


def test_the_record_states_no_formal_run_has_happened() -> None:
    record = document()

    assert record["formal_run_completed"] is False
    assert record["locked_holdout_accessed"] is False


def test_the_record_lists_the_declared_rate_inputs() -> None:
    assert document()["rate_inputs"] == list(rate_input_columns(WINDOW))


def test_the_record_carries_the_training_contract_the_manifests_will_name() -> None:
    declared = document()["declaration"]
    assert isinstance(declared, dict)

    assert declared["training_contract_version"] == LEARNED_RATE_TRAINING_CONTRACT_VERSION


def test_the_markdown_surfaces_the_reading_this_declaration_assumes() -> None:
    """The one interpretation a reviewer must confirm has to be visible, not buried."""

    text = markdown(document())

    assert "must be reissued" in text
    assert CANDIDATE_ID in text


def test_the_markdown_publishes_both_fingerprints() -> None:
    record = document()

    text = markdown(record)

    assert str(record["declaration_fingerprint"]) in text
    assert str(record["benchmark_configuration_fingerprint"]) in text
