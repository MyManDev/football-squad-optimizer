"""Tests for portable Sprint 2 JSON and Markdown artifacts."""

import json
from collections.abc import Mapping

import pytest
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_two_season_gameweeks,
)

from squadopt.experiments import (
    FrozenCandidateError,
    PromotionPolicy,
    ScreeningExperimentConfig,
    ScreeningExperimentResult,
    freeze_screening_candidate,
    frozen_candidate_from_dict,
    frozen_candidate_to_dict,
    holdout_result_to_dict,
    holdout_result_to_markdown,
    run_frozen_holdout,
    run_screening_experiment,
    screening_result_to_dict,
    screening_result_to_markdown,
)


@pytest.fixture(scope="module")
def compact_result() -> ScreeningExperimentResult:
    config = ScreeningExperimentConfig(
        development_seasons=(PREVIOUS_SEASON,),
        holdout_seasons=(SEASON,),
        form_windows=(5,),
        bench_weights=(0.1,),
        promotion_policy=PromotionPolicy(bootstrap_resamples=20),
        run_metadata={"nested": {"tags": ["synthetic", "offline"]}},
    )
    return run_screening_experiment(make_two_season_gameweeks(), config)


def test_frozen_candidate_round_trips_through_json(
    compact_result: ScreeningExperimentResult,
) -> None:
    frozen = freeze_screening_candidate(compact_result)
    encoded = json.dumps(frozen_candidate_to_dict(frozen))

    assert frozen_candidate_from_dict(json.loads(encoded)) == frozen


def test_tampered_frozen_candidate_is_rejected(
    compact_result: ScreeningExperimentResult,
) -> None:
    record = frozen_candidate_to_dict(freeze_screening_candidate(compact_result))
    record["screening_fingerprint"] = "z" * 64

    with pytest.raises(FrozenCandidateError, match="SHA-256"):
        frozen_candidate_from_dict(record)


def test_screening_artifacts_are_json_compatible_and_identify_no_holdout_access(
    compact_result: ScreeningExperimentResult,
) -> None:
    record = screening_result_to_dict(compact_result)
    markdown = screening_result_to_markdown(compact_result)

    json.dumps(record)
    assert record["artifact_type"] == "screening_experiment"
    configuration = record["configuration"]
    assert isinstance(configuration, Mapping)
    json.dumps(configuration["run_metadata"])
    diagnostics = record["diagnostics"]
    assert isinstance(diagnostics, Mapping)
    assert diagnostics["holdout_seasons_accessed"] is False
    assert "locked holdout was not accessed" in markdown
    assert compact_result.selected_candidate.candidate_id in markdown


def test_holdout_artifacts_preserve_the_frozen_screening_fingerprint(
    compact_result: ScreeningExperimentResult,
) -> None:
    frozen = freeze_screening_candidate(compact_result)
    holdout = run_frozen_holdout(
        make_two_season_gameweeks(),
        frozen,
        compact_result.config,
    )
    record = holdout_result_to_dict(holdout)
    markdown = holdout_result_to_markdown(holdout)

    json.dumps(record)
    frozen_record = record["frozen_candidate"]
    assert isinstance(frozen_record, Mapping)
    assert frozen_record["screening_fingerprint"] == frozen.screening_fingerprint
    assert frozen.screening_fingerprint in markdown
