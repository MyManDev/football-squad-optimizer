"""Synthetic fitted components -> handoff -> live rule -> plan -> published official score.

No collaborators in the tested chain are mocked. Prepared synthetic feature rows and
the existing synthetic capture fixture replace archive ingestion; this is a wiring and
arithmetic check, not a real-season forecast or calibration measurement.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.unit.test_component_models import FEATURES, _frame
from tests.unit.test_league_views import _legal_squad, _member_picks, _world_context
from tests.unit.test_live_transfers import _world

from squadopt import FrozenSquadDecision, score_frozen_squad_decision
from squadopt.application.advice import solve_member_control
from squadopt.application.lineup_publication import lineup_fields
from squadopt.live import CONTROL_MODEL_NAME, read_projection_handoff, write_projection_handoff
from squadopt.live.recommendation import InSeasonProjection, project
from squadopt.prediction import PredictionProvenance
from squadopt.prediction.component_dataset import FEATURE_CONTRACT_VERSION
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    fit_component_models,
    predict_components,
)
from squadopt.prediction.components import prepare_component_prediction

world = _world


def test_fitted_component_decision_is_the_decision_that_official_scoring_reads(
    world: dict[str, Any],
    tmp_path: Path,
) -> None:
    inputs, _, rules = _world_context(world)
    features = _frame(16, 24)
    training = features.loc[features["gameweek"] < 16].copy()
    scoring = features.loc[features["gameweek"] == 16].reset_index(drop=True)
    scoring["player_id"] += 1000
    # One row has no model input. It must retain its direct fallback, not acquire a
    # manufactured probability of zero through serialization or availability.
    scoring.loc[1, FEATURES[0]] = float("nan")
    models = fit_component_models(training, feature_columns=FEATURES)
    assert models is not None
    predicted = predict_components(models, scoring, feature_columns=FEATURES)
    components = predicted.loc[
        :,
        [
            "appearance_probability",
            "expected_minutes_if_appearance",
            "expected_points_if_appearance",
            "composition_route",
            "evidence_status",
        ],
    ].copy()
    components["player_id"] = scoring["player_id"]
    components["fixture_count"] = scoring["fixture_count"]
    components["fallback_expected_points"] = pd.Series(float("nan"), index=scoring.index)
    components.loc[1, "fallback_expected_points"] = 2.0
    provenance = PredictionProvenance(
        model_name=CONTROL_MODEL_NAME,
        model_version=COMPONENT_MODEL_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        training_cutoff="2024-25:GW15",
        training_data_fingerprint="a" * 64,
    )
    composed = prepare_component_prediction(
        components,
        provenance,
        decision_timestamp_utc=inputs.captured_at_utc,
    ).table.set_index("player_id")
    handoff = InSeasonProjection(
        season=inputs.season,
        gameweek=inputs.deadline.gameweek,
        source_snapshot_id=inputs.snapshot_id,
        model_name=CONTROL_MODEL_NAME,
        model_version=COMPONENT_MODEL_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        expected_points={int(p): float(v) for p, v in composed["expected_points"].items()},
        appearance_probability={
            int(p): float(v) for p, v in composed["appearance_probability"].dropna().items()
        },
    )
    restored = read_projection_handoff(
        write_projection_handoff(tmp_path / "projection.json", handoff)
    )
    assert restored.fingerprint == handoff.fingerprint
    availability = inputs.availability.copy()
    availability.loc[availability["player_id"].eq(1001), "chance_of_playing"] = 25
    inputs = replace(inputs, availability=availability)
    projection = project(inputs, in_season=restored)
    pool = projection.table.set_index("player_id")
    assert pool.loc[1001, "appearance_probability"] == pytest.approx(
        composed.loc[1001, "appearance_probability"] / 4
    )
    assert pool.loc[1001, "expected_points"] == pytest.approx(
        composed.loc[1001, "expected_points"] / 4
    )
    assert pd.isna(pool.loc[1002, "appearance_probability"])
    assert pool.loc[1002, "expected_points"] == 2.0

    picks = _member_picks(world, 101, _legal_squad(world))
    control = solve_member_control(picks, inputs, projection, rules)
    assert control.plan.has_solution
    week = control.plan.weeks[0]
    published = lineup_fields(week)
    frozen = FrozenSquadDecision(
        squad=week.selected_squad.loc[:, ["player_id", "position"]],
        starting_xi=tuple(row["player_id"] for row in published["starting_xi"]),
        bench=tuple(row["player_id"] for row in published["bench"]),
        captain_id=published["captain"]["player_id"],
        vice_captain_id=published["vice_captain"]["player_id"],
    )
    outcomes = pd.DataFrame(
        {
            "player_id": week.selected_squad["player_id"],
            "minutes": 90,
            "total_points": 1,
        }
    )
    # Everyone plays: eleven + one captain bonus. Then only the captain misses:
    # the published bench replaces him and the published vice receives the bonus.
    ordinary = score_frozen_squad_decision(frozen, outcomes)
    assert ordinary.total_points == 12.0
    outcomes.loc[outcomes["player_id"].eq(frozen.captain_id), ["minutes", "total_points"]] = 0
    fallback = score_frozen_squad_decision(frozen, outcomes)
    assert fallback.total_points == 12.0
    assert len(fallback.autosubs) == 1
    assert fallback.captain_bonus_player_id == frozen.vice_captain_id
    assert frozen.captain_id not in fallback.final_xi
    assert fallback.total_points - control.decision.transfer_hit_points == (
        12.0 - 4 * week.paid_transfer_count
    )
