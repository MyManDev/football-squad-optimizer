import pytest
from tests.unit.test_phase_c_component_decisions import _control, _handoff

from squadopt.experiments.instrument_replay import projection_covariates


def comparison():
    return {
        "source": {"table_sha256": "a" * 64, "roster_sha256": "b" * 64},
        "scoring_policy": "official_autosub_captain_v2",
        "folds": [
            {
                "fold_id": "2022-23-gw02",
                "component_realized_score": 24.0,
                "control_realized_score": 24.0,
                "difference": 0.0,
            }
        ],
    }


def test_projection_covariates_keep_the_recorded_difference() -> None:
    rows = projection_covariates(_handoff(), (_control(),), comparison())
    assert rows[0]["component_projected_pool_total"] > 0
    assert rows[0]["component_projected_pool_mean"] > 0
    assert rows[0]["difference"] == 0


@pytest.mark.parametrize("error", ["digest", "score", "population", "nan"])
def test_source_or_result_disagreement_refuses_measurement(error) -> None:
    report = comparison()
    if error == "digest":
        report["source"]["table_sha256"] = "bad"
    elif error == "population":
        report["folds"] = []
    else:
        report["folds"][0]["component_realized_score"] = float("nan") if error == "nan" else 999
    with pytest.raises(ValueError):
        projection_covariates(_handoff(), (_control(),), report)


def test_historical_scores_are_not_replaced_by_new_optimization() -> None:
    report = comparison()
    report["folds"][0].update(component_realized_score=29, difference=5)
    rows = projection_covariates(_handoff(), (_control(),), report)
    assert rows[0]["difference"] == 5
