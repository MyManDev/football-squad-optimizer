import pytest
from tests.unit.test_phase_c_component_decisions import _control, _handoff

from squadopt.experiments.instrument_replay import replay_covariates


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


def test_projection_covariates_replay_both_recorded_scores() -> None:
    rows = replay_covariates(_handoff(), (_control(),), comparison())
    assert rows[0]["component_projected_xi_captain"] == 48
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
        replay_covariates(_handoff(), (_control(),), report)
