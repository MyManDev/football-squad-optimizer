"""The opt-in joint team-match sampler: the appearance and the residual from one club block.

Every pool is synthetic and readable, in the block test's encoding: an appeared history row's
points residual encodes its fold (0 or 1000), its source club (0, 100 or 200) and its row within
the fold (the units), and its minutes residual is the same number over 100. Non-appeared rows
carry no target and so no residual. The target roster is the foundation tests' own three
players: two of club 1 (a midfielder and a forward) and one of club 2 (a defender).
"""

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_component_conditional_residuals import _draw as _conditional_draw
from tests.unit.test_component_scenarios import (
    TARGET,
    _fold_block_draw,
    _input_frame,
    _inputs,
    _sample,
    _snapshot,
)
from tests.unit.test_component_team_match_block import FOUNDATION_FINGERPRINTS
from tests.unit.test_component_team_match_block import _draw as _block_draw

from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    TEAM_MATCH_JOINT_CONTRACT_VERSION,
    ComponentScenarioDraw,
    ConditionalResidualConfig,
    TeamMatchBlockConfig,
    TeamMatchJointConfig,
    TeamMatchJointPool,
    paired_conditional_residuals,
    sample_component_scenarios,
    team_match_joint_pool,
)
from squadopt.scenarios.models import ScenarioValidationError

FOLDS = {"2026-27-gw07": 0.0, "2026-27-gw08": 1000.0}
# Source clubs of every history fold: name, fixture count, (position, appeared) of its rows.
CLUBS = (
    ("A", 1, (("GK", 1), ("DEF", 1), ("DEF", 0), ("MID", 1), ("MID", 0), ("FWD", 1))),
    ("B", 2, (("DEF", 1), ("MID", 1), ("FWD", 1))),
    ("C", 1, (("MID", 0), ("MID", 0))),
)
SOURCE_PROBABILITY = 0.5
# The block sampler's identities on its own fixtures, taken at the commit before the joint
# sampler existed. A draw with the joint keyword absent has to reproduce them.
BLOCK_FINGERPRINTS = {
    "block_default": "fd1e33e811745b2b24aff9a5a6411f036a746743c4dc697a764f005a28573c02",
    "block_seed_3": "a4b4224ae78b30a4cc74931c6f13642f514b37e105fb51dead97df4c2b1b963d",
}


def _pool_frame() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold_index, (fold, offset) in enumerate(FOLDS.items()):
        row = 0
        for club_index, (club, fixtures, rows) in enumerate(CLUBS):
            for position, appeared in rows:
                residual = offset + 100.0 * club_index + row
                records.append(
                    {
                        "fold_id": fold,
                        "player_id": 1000 + 100 * fold_index + row,
                        "composition_route": "component_model",
                        "appearance_target": appeared,
                        "appearance_probability": SOURCE_PROBABILITY,
                        "expected_minutes_if_appearance": 45.0,
                        "raw_expected_points_if_appearance": 4.0,
                        "minutes_target": 45.0 + residual / 100.0 if appeared else np.nan,
                        "points_target": 4.0 + residual if appeared else np.nan,
                        "team_id": club,
                        "position": position,
                        "fixture_count": fixtures,
                    }
                )
                row += 1
    return pd.DataFrame(records)


def _draw(
    team_match_joint: TeamMatchJointConfig | None,
    *,
    fixture_counts: tuple[int, int, int] = (2, 2, 1),
    probabilities: tuple[float, float, float] = (0.5, 0.5, 0.5),
    seed: int = 7,
    count: int = 400,
) -> ComponentScenarioDraw:
    frame = _input_frame(appearance_probability=list(probabilities))
    frame["fixture_count"] = list(fixture_counts)
    frame["expected_minutes_if_appearance"] = [45.0 if value else 0.0 for value in fixture_counts]
    pool = (
        team_match_joint_pool(_pool_frame(), target=TARGET)
        if team_match_joint is not None
        else paired_conditional_residuals(
            _pool_frame(), target=TARGET, team_match_block=TeamMatchBlockConfig()
        )
    )
    return sample_component_scenarios(
        _inputs(frame),
        _snapshot(),  # type: ignore[arg-type]
        pool,
        TARGET,
        ScenarioConfig(scenario_count=count, deterministic_seed=seed),
        team_match_joint=team_match_joint,
    )


def _decoded(draw: ComponentScenarioDraw) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per cell: the fold offset, the source club index and the row within the fold."""

    residual = draw.scenarios.scenario_points.to_numpy() - 4.0
    fold = np.where(residual >= 1000.0, 1000.0, 0.0)
    club = ((residual - fold) // 100.0).astype(int)
    row = np.rint(residual - fold - 100.0 * club).astype(int)
    return fold, club, row


def test_the_foundation_and_block_draws_are_unchanged_when_the_keyword_is_absent() -> None:
    assert _fold_block_draw().component_fingerprint == FOUNDATION_FINGERPRINTS["fold_block_draw"]
    assert _sample().component_fingerprint == FOUNDATION_FINGERPRINTS["sample_default"]
    seeded = _sample(config=ScenarioConfig(scenario_count=50, deterministic_seed=3))
    assert seeded.component_fingerprint == FOUNDATION_FINGERPRINTS["sample_seed_3"]
    assert (
        _conditional_draw(None).component_fingerprint
        == FOUNDATION_FINGERPRINTS["conditional_frozen"]
    )
    assert (
        _block_draw(TeamMatchBlockConfig()).component_fingerprint
        == (BLOCK_FINGERPRINTS["block_default"])
    )
    assert (
        _block_draw(TeamMatchBlockConfig(), seed=3).component_fingerprint
        == (BLOCK_FINGERPRINTS["block_seed_3"])
    )


def test_the_pool_keeps_non_appearances_without_a_residual_and_counts_its_refusals() -> None:
    pool = team_match_joint_pool(_pool_frame(), target=TARGET)

    assert isinstance(pool, TeamMatchJointPool)
    assert len(pool) == 22  # eleven rows per fold, appeared and not
    assert pool.history_fold_ids == tuple(FOLDS)
    paired = paired_conditional_residuals(_pool_frame(), target=TARGET)
    assert pool.history_fold_ids == paired.history_fold_ids
    rows = pool.residuals
    missing = rows.loc[rows["appearance_target"] == 0]
    assert len(missing) == 8 and missing["points_residual"].isna().all()
    assert missing["minutes_residual"].isna().all()
    present = rows.loc[rows["appearance_target"] == 1]
    assert len(present) == 14 and np.isfinite(present["points_residual"]).all()
    assert dict(pool.excluded_rows) == {
        "direct_control_rows": 0,
        "appearance_target_not_binary": 0,
        "appearance_probability_outside_unit_interval": 0,
        "block_field_missing": 0,
        "no_fixture": 0,
        "conditional_mean_missing": 0,
        "appeared_target_missing": 0,
        "rows_of_folds_without_appearance": 0,
    }

    frame = _pool_frame()
    frame.loc[0, "composition_route"] = "direct_control"
    frame.loc[1, "appearance_target"] = 2
    frame.loc[2, "appearance_probability"] = 1.5
    frame.loc[3, "team_id"] = None
    frame.loc[4, "fixture_count"] = 0
    frame.loc[5, "minutes_target"] = np.nan  # an appeared row (A's forward) without a target
    refused = team_match_joint_pool(frame, target=TARGET)
    counts = dict(refused.excluded_rows)
    assert (
        counts["direct_control_rows"],
        counts["appearance_target_not_binary"],
        counts["appearance_probability_outside_unit_interval"],
        counts["block_field_missing"],
        counts["no_fixture"],
        counts["appeared_target_missing"],
    ) == (1, 1, 1, 1, 1, 1)
    assert len(refused) == 16

    with pytest.raises(ScenarioValidationError, match="missing"):
        team_match_joint_pool(_pool_frame().drop(columns=["appearance_probability"]), target=TARGET)
    with pytest.raises(ScenarioValidationError, match="own residual history"):
        team_match_joint_pool(_pool_frame().assign(fold_id=TARGET.fold_id), target=TARGET)
    # A fold after the target is refused too, by the zero-padded fold order (gw10 after gw09).
    later = _pool_frame()
    later.loc[later["fold_id"] == "2026-27-gw08", "fold_id"] = "2026-27-gw10"
    with pytest.raises(ScenarioValidationError, match="must precede"):
        team_match_joint_pool(later, target=TARGET)


def test_a_fold_with_no_appearance_leaves_the_history() -> None:
    frame = _pool_frame()
    first = frame["fold_id"] == "2026-27-gw07"
    frame.loc[first, "appearance_target"] = 0
    frame.loc[first, ["minutes_target", "points_target"]] = np.nan

    pool = team_match_joint_pool(frame, target=TARGET)

    assert pool.history_fold_ids == ("2026-27-gw08",)
    assert dict(pool.excluded_rows)["rows_of_folds_without_appearance"] == 11
    with pytest.raises(ScenarioValidationError, match="at least 2"):
        team_match_joint_pool(frame, target=TARGET, min_history_folds=2)


def test_the_joint_sampler_and_its_pool_only_go_together() -> None:
    joint = team_match_joint_pool(_pool_frame(), target=TARGET)
    paired = paired_conditional_residuals(
        _pool_frame(), target=TARGET, team_match_block=TeamMatchBlockConfig()
    )
    frame = _input_frame()
    settings = ScenarioConfig(scenario_count=8)

    with pytest.raises(ScenarioValidationError, match="TeamMatchJointPool"):
        sample_component_scenarios(
            _inputs(frame),
            _snapshot(),
            paired,
            TARGET,
            settings,
            team_match_joint=TeamMatchJointConfig(),  # type: ignore[arg-type]
        )
    with pytest.raises(ScenarioValidationError, match="TeamMatchJointPool"):
        sample_component_scenarios(_inputs(frame), _snapshot(), joint, TARGET, settings)  # type: ignore[arg-type]
    with pytest.raises(ScenarioValidationError, match="TeamMatchJointPool"):
        sample_component_scenarios(
            _inputs(frame),
            _snapshot(),
            joint,
            TARGET,
            settings,
            team_match_block=TeamMatchBlockConfig(),  # type: ignore[arg-type]
        )
    for other in (
        {"team_match_block": TeamMatchBlockConfig()},
        {"conditional_residuals": ConditionalResidualConfig()},
    ):
        with pytest.raises(ScenarioValidationError, match="one candidate"):
            sample_component_scenarios(
                _inputs(frame),
                _snapshot(),  # type: ignore[arg-type]
                joint,
                TARGET,
                settings,
                team_match_joint=TeamMatchJointConfig(),
                **other,  # type: ignore[arg-type]
            )
    with pytest.raises(ScenarioValidationError, match="TeamMatchJointConfig or None"):
        sample_component_scenarios(
            _inputs(frame),
            _snapshot(),
            joint,
            TARGET,
            settings,
            team_match_joint="yes",  # type: ignore[arg-type]
        )
    with pytest.raises(ScenarioValidationError, match="contract_version"):
        TeamMatchJointConfig(contract_version="other")
    assert TeamMatchJointConfig() == TeamMatchJointConfig()
    assert TeamMatchJointConfig().__slots__ == ("contract_version",)  # type: ignore[attr-defined]


def test_source_folds_match_the_foundation_seed_for_seed() -> None:
    foundation = _draw(None)
    candidate = _draw(TeamMatchJointConfig())

    assert foundation.scenarios.source_fold_ids == candidate.scenarios.source_fold_ids
    assert candidate.scenarios.diagnostics["residual_selection"] == "team_match_joint"
    assert candidate.scenarios.diagnostics["component_sampler_contract_version"] == (
        TEAM_MATCH_JOINT_CONTRACT_VERSION
    )
    assert candidate.component_fingerprint != foundation.component_fingerprint


def test_the_appearance_is_inherited_from_the_source_block() -> None:
    """Club 1 (two fixtures) draws B, whose rows all appeared at the players' own probability:
    both players appear in every scenario. Club 2's defender draws A or C: he appears exactly
    when his source row is A's appeared defender, and takes that row's residual."""

    draw = _draw(TeamMatchJointConfig())
    appeared = draw.sampled_appearances.to_numpy()
    fold, club, row = _decoded(draw)

    assert appeared[:, :2].all()
    assert set(club[:, 0].tolist()) == {1} and set(row[:, 0].tolist()) == {7}
    assert set(row[:, 1].tolist()) == {8}
    third = appeared[:, 2]
    assert 0.1 < third.mean() < 0.4  # A half the time, then its appeared defender half the time
    assert set(club[third, 2].tolist()) == {0} and set(row[third, 2].tolist()) == {1}
    assert (draw.scenarios.scenario_points.to_numpy()[~appeared] == 0.0).all()
    named = np.array([FOLDS[fold_id] for fold_id in draw.scenarios.source_fold_ids])
    assert (fold[appeared] == named[:, None].repeat(3, axis=1)[appeared]).all()
    diagnostics = draw.scenarios.diagnostics
    assert diagnostics["team_match_joint_redraw_cells"] == 0
    assert diagnostics["team_match_joint_target_clubs"] == 2
    assert diagnostics["team_match_joint_blocks_per_fold_mean"] == 3.0
    assert diagnostics["team_match_joint_block_appeared_rows_mean"] == pytest.approx(7 / 3)
    assert diagnostics["team_match_joint_position_fallback_cells"] > 0  # C has no defender
    assert diagnostics["team_match_joint_fixture_fallback_cells"] == 0
    assert diagnostics["team_match_joint_pool_excluded_rows"]["no_fixture"] == 0


def test_same_club_players_do_not_appear_when_their_block_rested() -> None:
    """Both of club 1 on one fixture draw A or C. C's rows all sat out, so neither appears
    there; in A the forward always appears and the midfielder only from the appeared row."""

    draw = _draw(TeamMatchJointConfig(), fixture_counts=(1, 1, 1))
    appeared = draw.sampled_appearances.to_numpy()
    _, club, _ = _decoded(draw)

    assert not appeared[~appeared[:, 1], 0].any(), "no midfielder appearance without the forward"
    assert 0.3 < appeared[:, 1].mean() < 0.7  # A is drawn half the time
    assert set(club[appeared[:, 1], 1].tolist()) == {0}
    # The appearances of the two co-move far beyond what independent draws give.
    assert np.corrcoef(appeared[:, 0], appeared[:, 1])[0, 1] > 0.3


def test_a_player_appearing_from_a_rested_row_redraws_an_appeared_residual() -> None:
    """At probability 0.9 the defender appears from A's rested defender and from C's rows
    (latent uniform below 0.9); his residual then comes from an appeared row of the block,
    or of the fold when the block has none, and every appearing cell stays finite and paired."""

    draw = _draw(TeamMatchJointConfig(), probabilities=(0.5, 0.5, 0.9))
    appeared = draw.sampled_appearances.to_numpy()
    _, club, row = _decoded(draw)
    diagnostics = draw.scenarios.diagnostics

    third = appeared[:, 2]
    assert 0.75 < third.mean() < 0.95
    assert diagnostics["team_match_joint_redraw_cells"] > 0
    assert diagnostics["team_match_joint_redraw_fold_fallback_cells"] > 0
    assert diagnostics["team_match_joint_redraw_block_fallback_cells"] == 0
    assert diagnostics["team_match_joint_redraw_rate"] == pytest.approx(
        diagnostics["team_match_joint_redraw_cells"] / appeared.sum()
    )
    points = draw.scenarios.scenario_points.to_numpy()
    minutes = draw.sampled_minutes.to_numpy()
    assert np.isfinite(points).all() and np.isfinite(minutes).all()
    # Every residual is an appeared row's: A's rows 0, 1, 3, 5 or B's 6, 7, 8, never C's. From
    # A's rested defender the re-draw is A's appeared defender (row 1); from C's rows the fold
    # fallback gives any appeared row of the fold, A's or B's.
    drawn = set(zip(club[third, 2].tolist(), row[third, 2].tolist(), strict=True))
    assert drawn <= {(0, 0), (0, 1), (0, 3), (0, 5), (1, 6), (1, 7), (1, 8)}
    assert (0, 1) in drawn and (1, 7) in drawn
    assert (club[third, 2] != 2).all(), "C has no appeared row to give"
    assert np.allclose((minutes[appeared] - 45.0) * 100.0, points[appeared] - 4.0)


def test_certain_impossible_and_blank_appearances_behave_as_the_foundation() -> None:
    certain = _draw(TeamMatchJointConfig(), probabilities=(1.0, 1.0, 1.0), fixture_counts=(1, 1, 1))
    assert certain.sampled_appearances.to_numpy().all()
    never = _draw(TeamMatchJointConfig(), probabilities=(0.0, 0.0, 0.0), fixture_counts=(1, 1, 1))
    assert not never.sampled_appearances.to_numpy().any()
    assert (never.scenarios.scenario_points.to_numpy() == 0.0).all()
    blank = _draw(TeamMatchJointConfig(), fixture_counts=(2, 2, 0))
    assert not blank.sampled_appearances.to_numpy()[:, 2].any()
    assert blank.scenarios.diagnostics["team_match_joint_blank_club_cells"] == 400
    assert blank.scenarios.diagnostics["team_match_joint_fixture_fallback_cells"] == 0


def test_the_same_seed_reproduces_the_draw_and_another_moves_it() -> None:
    first = _draw(TeamMatchJointConfig())
    again = _draw(TeamMatchJointConfig())
    other = _draw(TeamMatchJointConfig(), seed=3)

    assert first.component_fingerprint == again.component_fingerprint
    assert first.scenarios.scenario_fingerprint == again.scenarios.scenario_fingerprint
    assert first.component_fingerprint != other.component_fingerprint
