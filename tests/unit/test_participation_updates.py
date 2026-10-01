"""Synthetic, source-timed participation updates; no historical/news provider access."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.participation_updates import (
    DispositionCalibration,
    ParticipationEvidence,
    apply_participation_updates,
)

AS_OF = pd.Timestamp("2026-10-01T10:00:00Z")
DEADLINE = pd.Timestamp("2026-10-02T10:00:00Z")
DEADLINES = {6: DEADLINE, 7: DEADLINE + pd.Timedelta(days=7)}


def _base() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 1, 2],
            "gameweek": [6, 7, 6],
            "expected_points": [4.8, 4.8, 6.0],
            "appearance_probability": [0.6, 0.6, 1.0],
            "availability_multiplier": [0.75, 0.75, 1.0],
        },
        index=[10, 10, 40],  # Positional writes must not affect duplicate-index rows.
    )


def _evidence(**changes: object) -> ParticipationEvidence:
    item = ParticipationEvidence(
        evidence_id="captured-1",
        player_id=1,
        season="2026-27",
        gameweek=6,
        deadline=DEADLINE,
        published_at=AS_OF - pd.Timedelta(hours=2),
        captured_at=AS_OF - pd.Timedelta(hours=1),
        valid_until=DEADLINE,
        source_id="official-feed-capture-1",
        source_url="https://example.test/official-player-status",
        kind="captured_source_percentage",
        source_percentage=50.0,
    )
    return replace(item, **changes)


def _apply(
    evidence: list[ParticipationEvidence],
    base: pd.DataFrame | None = None,
    calibrations: dict[str, DispositionCalibration] | None = None,
):
    return apply_participation_updates(
        _base() if base is None else base,
        evidence,
        season="2026-27",
        as_of=AS_OF,
        deadlines=DEADLINES,
        base_revision="forecast-capture-v7",
        calibrations=calibrations,
    )


def _scenario(**changes: object) -> ParticipationEvidence:
    return _evidence(
        kind="scenario_assumption",
        source_percentage=None,
        probability=0.3,
        target="appearance",
        assumption="User scenario: explicitly assume a 30% appearance chance.",
        source_url=None,
        **changes,
    )


def _calibration() -> DispositionCalibration:
    return DispositionCalibration(
        calibration_id="external-table-1",
        reference="https://example.test/calibration/report-1",
        published_at=AS_OF - pd.Timedelta(days=1),
        observations_through=AS_OF - pd.Timedelta(days=2),
        sample_count=120,
        target="appearance",
        probabilities={"stated_rotation_risk": 0.4},
    )


def test_source_percentage_replaces_eligibility_once_without_becoming_start_chance():
    base = _base()
    before = base.copy(deep=True)
    result = _apply([_evidence()], base)
    # Prior learned conditional appearance is .6/.75=.8; 50% eligibility gives q=.4.
    row = result.table.iloc[0]
    assert row.appearance_probability == pytest.approx(0.4)
    assert row.expected_points == pytest.approx(3.2)
    assert row.expected_points / row.appearance_probability == pytest.approx(8.0)
    assert row.availability_multiplier == 0.5
    assert "start_probability" not in result.table
    assert result.diagnostics[0]["start_and_minutes_reestimated"] is False
    assert_frame_equal(base, before)
    assert_frame_equal(result.table.iloc[1:], base.iloc[1:])


def test_same_source_percentage_already_in_baseline_is_not_multiplied_twice():
    result = _apply([_evidence(source_percentage=75.0)])
    assert_frame_equal(result.table, _base())


def test_output_refuses_reapplication_but_pristine_basis_is_deterministic():
    item = _evidence()
    first = _apply([item])
    repeated = _apply([item])
    assert_frame_equal(first.table, repeated.table)
    assert first.diagnostics == repeated.diagnostics
    with pytest.raises(PredictionConfigurationError, match="fresh base revision"):
        _apply([item], first.table)


def test_explicit_scenario_keeps_assumption_separate_from_source_probability():
    result = _apply([_scenario()])
    row = result.table.iloc[0]
    assert row.appearance_probability == 0.3
    assert row.expected_points == pytest.approx(2.4)
    record = result.diagnostics[0]["evidence"][0]
    assert record["kind"] == "scenario_assumption"
    assert "30%" in record["assumption"]
    assert record["source_percentage"] is None
    assert record["calibration_verified_here"] is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"published_at": AS_OF + pd.Timedelta(hours=1)}, "invalid_source_timing"),
        ({"captured_at": AS_OF + pd.Timedelta(hours=1)}, "future_evidence"),
        ({"published_at": AS_OF - pd.Timedelta(days=8)}, "expired_evidence"),
        ({"valid_until": AS_OF - pd.Timedelta(seconds=1)}, "expired_evidence"),
        ({"published_at": AS_OF.tz_localize(None)}, "invalid_source_timing"),
        ({"deadline": DEADLINE + pd.Timedelta(seconds=1)}, "deadline_mismatch"),
        ({"season": "2027-28"}, "season_mismatch"),
        ({"source_id": ""}, "missing_source_identity"),
        ({"source_url": None}, "missing_source_citation"),
        ({"source_percentage": float("nan")}, "invalid_source_percentage"),
        ({"source_percentage": float("inf")}, "invalid_source_percentage"),
        ({"source_percentage": -1.0}, "invalid_source_percentage"),
        ({"source_percentage": 101.0}, "invalid_source_percentage"),
        ({"source_percentage": True}, "invalid_source_percentage"),
        ({"target": "appearance"}, "source_percentage_is_eligibility"),
        ({"probability": 0.9}, "source_percentage_is_eligibility"),
    ],
)
def test_ineligible_or_invalid_source_leaves_basis_unchanged(changes, reason):
    result = _apply([_evidence(**changes)])
    assert_frame_equal(result.table, _base())
    assert result.diagnostics[0]["status"] == "unchanged"
    assert result.diagnostics[0]["reason"] == reason


@pytest.mark.parametrize("disposition", ["no_statement", "ambiguous", "not_addressed"])
def test_uninformative_statement_does_not_produce_probability(disposition):
    result = _apply(
        [_evidence(kind="source_statement", source_percentage=None, disposition=disposition)]
    )
    assert_frame_equal(result.table, _base())
    assert result.diagnostics[0]["reason"] == disposition


@pytest.mark.parametrize(
    "disposition",
    [
        "stated_rotation_risk",
        "stated_minutes_limited",
        "stated_expected_to_start",
        "stated_returning_from_injury",
    ],
)
def test_categorical_manager_words_never_get_invented_default(disposition):
    result = _apply(
        [_evidence(kind="source_statement", source_percentage=None, disposition=disposition)]
    )
    assert_frame_equal(result.table, _base())
    assert result.diagnostics[0]["reason"] == "categorical_statement_has_no_probability"


def test_valid_cited_absence_zeroes_appearance_for_only_its_bound_week():
    result = _apply(
        [
            _evidence(
                kind="source_statement",
                source_percentage=None,
                disposition="stated_expected_absent",
            )
        ]
    )
    assert result.table.iloc[0].appearance_probability == 0
    assert result.table.iloc[0].expected_points == 0
    assert_frame_equal(result.table.iloc[1:], _base().iloc[1:])


@pytest.mark.parametrize("same_id", [True, False])
def test_duplicate_identifier_or_same_source_does_not_count_twice(same_id):
    first = _evidence()
    second = first if same_id else replace(first, evidence_id="other-capture")
    result = _apply([first, second])
    assert_frame_equal(result.table, _base())
    assert result.diagnostics[0]["reason"] == "duplicate_evidence_or_source"


def test_conflicting_sources_leave_prior_unchanged_in_either_order():
    first = _evidence()
    second = _evidence(evidence_id="other", source_id="other-source", source_percentage=25.0)
    for items in ([first, second], [second, first]):
        result = _apply(items)
        assert_frame_equal(result.table, _base())
        assert result.diagnostics[0]["reason"] == "conflicting_sources"


def test_independent_agreeing_sources_apply_exactly_once():
    first = _evidence()
    second = replace(first, evidence_id="other", source_id="other-source")
    assert_frame_equal(_apply([first, second]).table, _apply([first]).table)


def test_source_percentage_needs_actual_eligibility_basis():
    base = _base().drop(columns="availability_multiplier")
    result = _apply([_evidence()], base)
    assert_frame_equal(result.table, base)
    assert result.diagnostics[0]["reason"] == "eligibility_basis_missing"


def test_zero_prior_does_not_invent_recovery_or_conditional_mean():
    base = _base()
    base.iloc[0, base.columns.get_indexer(["expected_points", "appearance_probability"])] = 0.0
    result = _apply([_scenario()], base)
    assert_frame_equal(result.table, base)
    assert result.diagnostics[0]["reason"] == "zero_prior_without_conditional_mean"
    base["points_if_appearance"] = 8.0
    restored = _apply([_scenario()], base)
    assert restored.table.iloc[0].expected_points == pytest.approx(2.4)


def test_zero_eligibility_does_not_invent_conditional_appearance():
    base = _base()
    base.iloc[
        0,
        base.columns.get_indexer(
            ["expected_points", "appearance_probability", "availability_multiplier"]
        ),
    ] = 0.0
    result = _apply([_evidence()], base)
    assert_frame_equal(result.table, base)
    assert result.diagnostics[0]["reason"] == "zero_eligibility_basis"


def test_zero_eligibility_with_positive_prior_appearance_is_inconsistent():
    base = _base()
    base.iloc[0, base.columns.get_loc("availability_multiplier")] = 0.0
    result = _apply([_evidence(source_percentage=0.0)], base)
    assert_frame_equal(result.table, base)
    assert result.diagnostics[0]["reason"] == "inconsistent_eligibility_basis"


@pytest.mark.parametrize("positive", ["stated_expected_to_start", "stated_minutes_limited"])
def test_categorical_conflict_cannot_be_discarded_merely_for_lacking_a_number(positive):
    absence = _evidence(
        kind="source_statement", source_percentage=None, disposition="stated_expected_absent"
    )
    playing = replace(
        absence, evidence_id="positive", source_id="another-source", disposition=positive
    )
    for items in ([absence, playing], [playing, absence]):
        result = _apply(items)
        assert_frame_equal(result.table, _base())
        assert result.diagnostics[0]["reason"] == "conflicting_sources"


def test_future_categorical_claim_does_not_block_eligible_cited_absence():
    absence = _evidence(
        kind="source_statement", source_percentage=None, disposition="stated_expected_absent"
    )
    future = replace(
        absence,
        evidence_id="positive",
        source_id="another-source",
        disposition="stated_expected_to_start",
        captured_at=AS_OF + pd.Timedelta(hours=1),
    )
    result = _apply([absence, future])
    assert result.table.iloc[0].appearance_probability == 0
    assert result.diagnostics[0]["status"] == "applied"


def test_external_calibration_uses_supplied_disposition_table_and_reports_reference():
    item = _evidence(
        kind="external_calibration",
        source_percentage=None,
        disposition="stated_rotation_risk",
        target="appearance",
        calibration_id="external-table-1",
    )
    result = _apply([item], calibrations={"external-table-1": _calibration()})
    assert result.table.iloc[0].appearance_probability == 0.4
    assert result.table.iloc[0].expected_points == pytest.approx(3.2)
    record = result.diagnostics[0]["evidence"][0]
    assert record["calibration_reference"] == _calibration().reference
    assert record["calibration_verified_here"] is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"sample_count": 0}, "invalid_calibration_sample_count"),
        ({"sample_count": True}, "invalid_calibration_sample_count"),
        ({"reference": ""}, "missing_calibration_provenance"),
        ({"published_at": AS_OF + pd.Timedelta(hours=1)}, "ineligible_calibration_timing"),
        ({"observations_through": AS_OF}, "ineligible_calibration_timing"),
        ({"probabilities": {"stated_rotation_risk": 1.1}}, "invalid_calibration_probability"),
        (
            {"probabilities": {"stated_rotation_risk": float("nan")}},
            "invalid_calibration_probability",
        ),
    ],
)
def test_calibration_metadata_is_checked_without_claiming_accuracy(changes, reason):
    item = _evidence(
        kind="external_calibration",
        source_percentage=None,
        disposition="stated_rotation_risk",
        target="appearance",
        calibration_id="external-table-1",
    )
    result = _apply([item], calibrations={"external-table-1": replace(_calibration(), **changes)})
    assert_frame_equal(result.table, _base())
    assert result.diagnostics[0]["reason"] == reason


def test_horizon_and_base_revision_require_explicit_identification():
    with pytest.raises(PredictionConfigurationError, match="Every projected gameweek"):
        apply_participation_updates(
            _base(),
            [],
            season="2026-27",
            as_of=AS_OF,
            deadlines={6: DEADLINE},
            base_revision="forecast-v1",
        )
    with pytest.raises(PredictionConfigurationError, match="base revision"):
        apply_participation_updates(
            _base(),
            [],
            season="2026-27",
            as_of=AS_OF,
            deadlines=DEADLINES,
            base_revision="",
        )


@pytest.mark.parametrize("invalid_q", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_base_probability_is_refused(invalid_q):
    base = _base()
    base.iloc[0, base.columns.get_loc("appearance_probability")] = invalid_q
    with pytest.raises(PredictionConfigurationError, match="basis"):
        _apply([_evidence()], base)
