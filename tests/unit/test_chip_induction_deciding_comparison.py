"""Which comparison decides stage 2 is read from the record, never fixed in the runner.

Two protocols chain here. `chip_forecast_prereg.md`'s amendment keeps the reservation when
`decaying - threshold_only` is positive and drops it otherwise;
`chip_threshold_induction_prereg.md` says the dropped case makes `induction - threshold_only`
the comparison that decides. The runner used to name `induction_minus_decaying` as a constant,
which is the branch the committed record does **not** take.
"""

import json
from pathlib import Path

import pytest
from scripts.measure_chip_threshold_induction import deciding_comparison

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORECAST_RECORD = REPOSITORY_ROOT / "docs" / "chip_forecast_rule.json"


def _document(difference: float) -> dict[str, object]:
    return {
        "comparisons": [
            {"variant": "decaying", "baseline": "fixed", "mean_weekly_advantage_points": 9.0},
            {
                "variant": "decaying",
                "baseline": "threshold_only",
                "mean_weekly_advantage_points": difference,
            },
        ]
    }


def test_a_negative_difference_drops_the_reservation_and_moves_what_decides() -> None:
    assert deciding_comparison(_document(-0.15)) == "induction_minus_threshold_only"
    assert deciding_comparison(_document(0.15)) == "induction_minus_decaying"
    # "Positive" is strict: exactly zero is not positive, so the reservation drops.
    assert deciding_comparison(_document(0.0)) == "induction_minus_threshold_only"


def test_a_record_without_that_comparison_is_refused_rather_than_defaulted() -> None:
    """Defaulting would name a deciding comparison nobody derived."""

    with pytest.raises(SystemExit, match="cannot be named"):
        deciding_comparison({"comparisons": [{"variant": "decaying", "baseline": "off"}]})


def test_the_committed_forecast_record_takes_the_dropped_branch() -> None:
    """Pinned against the real record, so a future re-measure that flips it is visible here."""

    document = json.loads(FORECAST_RECORD.read_text(encoding="utf-8"))
    (pair,) = [
        comparison
        for comparison in document["comparisons"]
        if comparison["variant"] == "decaying" and comparison["baseline"] == "threshold_only"
    ]
    assert float(pair["mean_weekly_advantage_points"]) < 0.0
    assert deciding_comparison(document) == "induction_minus_threshold_only"
