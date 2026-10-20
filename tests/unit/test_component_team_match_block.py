"""The opt-in team-match block: a club-week block inside the scenario's source fold.

Every pool is synthetic and readable. A history row's points residual encodes its fold (0 or
1000), its source club (0, 100 or 200) and its row within the fold (the units), and its minutes
residual is the same number over 100, so a sampled cell names its fold, its club, its row and
its pairing at once. The target roster is the foundation tests' own three players: two of club
1 (a midfielder and a forward) and one of club 2 (a defender).
"""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_component_conditional_residuals import _draw as _conditional_draw
from tests.unit.test_component_scenarios import (
    TARGET,
    _fold_block_draw,
    _input_frame,
    _inputs,
    _oof,
    _sample,
    _snapshot,
)

from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    TEAM_MATCH_BLOCK_CONTRACT_VERSION,
    TEAM_MATCH_BLOCK_SOURCE_COLUMNS,
    ComponentScenarioDraw,
    ConditionalResidualConfig,
    TeamMatchBlockConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)
from squadopt.scenarios.models import ScenarioValidationError

FOLDS = {"2026-27-gw07": 0.0, "2026-27-gw08": 1000.0}
# Source clubs of every history fold: name, fixture count, the positions of its rows.
CLUBS = (
    ("A", 1, ("GK", "DEF", "DEF", "MID", "MID", "FWD")),
    ("B", 2, ("DEF", "MID", "FWD")),
    ("C", 1, ("MID", "MID")),
)
# The pinned identities of the foundation draws on the existing synthetic fixtures, taken at
# the commit before this candidate existed. A draw with the keyword absent has to reproduce
# them fingerprint for fingerprint; that is the proof the foundation sampler is unchanged.
FOUNDATION_FINGERPRINTS = {
    "fold_block_draw": "0ba919f03ed77ccf399a57cd4d8617328b93aa54dfbee1d9ebd79eea294a93cf",
    "sample_default": "b7815e9a409828fa97aaaefa096ec9b49f034231fbcb4d0e2915b39c73172508",
    "sample_seed_3": "369d1068ac06094f40f5439c799661447c4ff5e1fec4b1a228738f7c4e4b668a",
    "conditional_frozen": "cc89ddbecee54874b9630bd9077eb116c492ca1a139eed0d7a315ef317bcdfb9",
}


def _pool_frame() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold_index, (fold, offset) in enumerate(FOLDS.items()):
        row = 0
        for club_index, (club, fixtures, positions) in enumerate(CLUBS):
            for position in positions:
                residual = offset + 100.0 * club_index + row
                records.append(
                    {
                        "fold_id": fold,
                        "player_id": 1000 + 100 * fold_index + row,
                        "composition_route": "component_model",
                        "appearance_target": 1,
                        "expected_minutes_if_appearance": 45.0,
                        "raw_expected_points_if_appearance": 4.0,
                        "minutes_target": 45.0 + residual / 100.0,
                        "points_target": 4.0 + residual,
                        "team_id": club,
                        "position": position,
                        "fixture_count": fixtures,
                    }
                )
                row += 1
    return pd.DataFrame(records)


def _draw(
    team_match_block: TeamMatchBlockConfig | None,
    *,
    fixture_counts: tuple[int, int, int] = (2, 2, 1),
    seed: int = 7,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> ComponentScenarioDraw:
    frame = _input_frame(appearance_probability=1.0)
    frame["fixture_count"] = list(fixture_counts)
    # A blank club carries no minutes expectation, as the input contract requires.
    frame["expected_minutes_if_appearance"] = [45.0 if count else 0.0 for count in fixture_counts]
    pool = paired_conditional_residuals(
        _pool_frame(), target=TARGET, team_match_block=TeamMatchBlockConfig()
    )
    return sample_component_scenarios(
        _inputs(frame),
        _snapshot(),  # type: ignore[arg-type]
        pool,
        TARGET,
        ScenarioConfig(scenario_count=400, deterministic_seed=seed),
        conditional_residuals=conditional_residuals,
        team_match_block=team_match_block,
    )


def _decoded(draw: ComponentScenarioDraw) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per cell: the fold offset, the source club index and the row within the fold."""

    residual = draw.scenarios.scenario_points.to_numpy() - 4.0
    fold = np.where(residual >= 1000.0, 1000.0, 0.0)
    club = ((residual - fold) // 100.0).astype(int)
    row = np.rint(residual - fold - 100.0 * club).astype(int)
    return fold, club, row


def test_the_foundation_draw_is_unchanged_when_the_keyword_is_absent() -> None:
    """Fingerprint for fingerprint against the parent commit, on the existing fixtures."""

    assert _fold_block_draw().component_fingerprint == FOUNDATION_FINGERPRINTS["fold_block_draw"]
    assert _sample().component_fingerprint == FOUNDATION_FINGERPRINTS["sample_default"]
    seeded = _sample(config=ScenarioConfig(scenario_count=50, deterministic_seed=3))
    assert seeded.component_fingerprint == FOUNDATION_FINGERPRINTS["sample_seed_3"]
    assert (
        _conditional_draw(None).component_fingerprint
        == (FOUNDATION_FINGERPRINTS["conditional_frozen"])
    )


def test_the_pool_keeps_the_block_fields_only_when_asked_and_refuses_a_frame_without_them() -> None:
    plain = paired_conditional_residuals(_pool_frame(), target=TARGET)
    blocked = paired_conditional_residuals(
        _pool_frame(), target=TARGET, team_match_block=TeamMatchBlockConfig()
    )

    assert not set(TEAM_MATCH_BLOCK_SOURCE_COLUMNS) & set(plain.residuals.columns)
    assert set(TEAM_MATCH_BLOCK_SOURCE_COLUMNS) <= set(blocked.residuals.columns)
    assert_frame_equal(plain.residuals, blocked.residuals.loc[:, plain.residuals.columns])
    assert plain.fold_blocks() == blocked.fold_blocks()
    with pytest.raises(ScenarioValidationError, match="missing"):
        paired_conditional_residuals(_oof(), target=TARGET, team_match_block=TeamMatchBlockConfig())
    with pytest.raises(ScenarioValidationError, match="TeamMatchBlockConfig"):
        paired_conditional_residuals(_pool_frame(), target=TARGET, team_match_block="yes")  # type: ignore[arg-type]
    incomplete = _pool_frame()
    incomplete.loc[0, "team_id"] = None
    with pytest.raises(ScenarioValidationError, match="missing value"):
        paired_conditional_residuals(
            incomplete, target=TARGET, team_match_block=TeamMatchBlockConfig()
        )


def test_the_candidate_refuses_a_pool_built_without_the_block_fields() -> None:
    pool = paired_conditional_residuals(_pool_frame(), target=TARGET)
    with pytest.raises(ScenarioValidationError, match="build it with team_match_block"):
        sample_component_scenarios(
            _inputs(_input_frame(appearance_probability=1.0)),
            _snapshot(),  # type: ignore[arg-type]
            pool,
            TARGET,
            ScenarioConfig(scenario_count=10),
            team_match_block=TeamMatchBlockConfig(),
        )


def test_appearances_and_source_folds_match_the_foundation_seed_for_seed() -> None:
    """Only the row within the fold changes; the appearance and fold streams are shared."""

    foundation = _draw(None)
    candidate = _draw(TeamMatchBlockConfig())

    assert_frame_equal(foundation.sampled_appearances, candidate.sampled_appearances)
    assert foundation.scenarios.source_fold_ids == candidate.scenarios.source_fold_ids
    assert not foundation.scenarios.scenario_points.equals(candidate.scenarios.scenario_points)
    assert foundation.component_fingerprint != candidate.component_fingerprint
    assert foundation.scenarios.diagnostics["residual_selection"] == "fold_uniform"


def test_every_player_of_a_target_club_draws_from_one_source_club_in_one_fold() -> None:
    draw = _draw(TeamMatchBlockConfig())

    fold, club, row = _decoded(draw)
    named = np.array([FOLDS[fold_id] for fold_id in draw.scenarios.source_fold_ids])
    assert (fold == named[:, None]).all(), "every cell is inside its scenario's fold"
    assert (club[:, 0] == club[:, 1]).all(), "the two players of club 1 share a source club"
    # Club 1 has two fixtures, and B is the only source club with two: it is drawn every time.
    assert set(club[:, 0].tolist()) == {1}
    # Club 2 has one fixture and draws among A and C, independently of club 1's block.
    assert set(club[:, 2].tolist()) == {0, 2}
    # The midfielder takes B's midfielder (row 7), the forward B's forward (row 8).
    assert set(row[:, 0].tolist()) == {7}
    assert set(row[:, 1].tolist()) == {8}
    # Minutes and points come from one row: the pairing survives the block draw.
    pool = paired_conditional_residuals(
        _pool_frame(), target=TARGET, team_match_block=TeamMatchBlockConfig()
    )
    club_b = pool.residuals.query("fold_id == '2026-27-gw07' and team_id == 'B'")
    assert club_b.loc[club_b["position"] == "MID", "points_residual"].tolist() == [107.0]
    minutes_residual = draw.sampled_minutes.to_numpy() - 45.0
    points_residual = draw.scenarios.scenario_points.to_numpy() - 4.0
    assert np.allclose(minutes_residual * 100.0, points_residual)
    assert draw.scenarios.diagnostics["component_sampler_contract_version"] == (
        TEAM_MATCH_BLOCK_CONTRACT_VERSION
    )
    assert draw.scenarios.diagnostics["residual_selection"] == "team_match_block"
    assert draw.scenarios.diagnostics["team_match_block_target_clubs"] == 2
    assert draw.scenarios.diagnostics["team_match_block_blocks_per_fold_mean"] == 3.0
    assert draw.scenarios.diagnostics["team_match_block_block_rows_mean"] == pytest.approx(11 / 3)
    assert draw.scenarios.diagnostics["team_match_block_fixture_fallback_cells"] == 0
    assert draw.scenarios.diagnostics["team_match_block_mixed_fixture_blocks"] == 0


def test_a_missing_position_falls_back_to_the_block_and_is_counted() -> None:
    draw = _draw(TeamMatchBlockConfig())

    _, club, row = _decoded(draw)
    # Club 2's defender finds a defender in A (rows 1 and 2) and none in C (rows 9 and 10).
    from_a = club[:, 2] == 0
    assert set(row[from_a, 2].tolist()) == {1, 2}
    assert set(row[~from_a, 2].tolist()) == {9, 10}
    diagnostics = draw.scenarios.diagnostics
    assert diagnostics["team_match_block_position_fallback_cells"] == int((~from_a).sum())
    assert diagnostics["team_match_block_position_fallback_rate"] == pytest.approx(
        int((~from_a).sum()) / (400 * 3)
    )


def test_a_fixture_count_without_a_matching_block_falls_back_to_any_block_and_is_counted() -> None:
    draw = _draw(TeamMatchBlockConfig(), fixture_counts=(3, 3, 1))

    _, club, _ = _decoded(draw)
    assert set(club[:, 0].tolist()) == {0, 1, 2}, "no block has three fixtures, so any block"
    assert set(club[:, 2].tolist()) == {0, 2}
    diagnostics = draw.scenarios.diagnostics
    assert diagnostics["team_match_block_fixture_fallback_cells"] == 400
    assert diagnostics["team_match_block_fixture_fallback_rate"] == pytest.approx(0.5)
    assert diagnostics["team_match_block_blank_club_cells"] == 0


def test_a_blank_club_is_counted_apart_from_the_fixture_fallback() -> None:
    draw = _draw(TeamMatchBlockConfig(), fixture_counts=(2, 2, 0))

    assert not draw.sampled_appearances.to_numpy()[:, 2].any()
    assert (draw.scenarios.scenario_points.to_numpy()[:, 2] == 0.0).all()
    diagnostics = draw.scenarios.diagnostics
    assert diagnostics["team_match_block_blank_club_cells"] == 400
    assert diagnostics["team_match_block_fixture_fallback_cells"] == 0
    assert diagnostics["team_match_block_fixture_fallback_rate"] == 0.0


def test_the_same_seed_reproduces_the_candidate_draw() -> None:
    first = _draw(TeamMatchBlockConfig())
    second = _draw(TeamMatchBlockConfig())

    assert first.component_fingerprint == second.component_fingerprint
    assert_frame_equal(first.scenarios.scenario_points, second.scenarios.scenario_points)
    assert _draw(TeamMatchBlockConfig(), seed=8).component_fingerprint != (
        first.component_fingerprint
    )


def test_the_two_candidates_are_mutually_exclusive_and_the_config_has_no_knob() -> None:
    with pytest.raises(ScenarioValidationError, match="one or neither"):
        _draw(
            TeamMatchBlockConfig(),
            conditional_residuals=ConditionalResidualConfig(fraction=0.25, minimum_rows=4),
        )
    with pytest.raises(ScenarioValidationError, match="TeamMatchBlockConfig"):
        _draw("not a config")  # type: ignore[arg-type]
    with pytest.raises(ScenarioValidationError, match="contract_version"):
        TeamMatchBlockConfig(contract_version="team_match_block_v2")
    assert TeamMatchBlockConfig().contract_version == TEAM_MATCH_BLOCK_CONTRACT_VERSION
    assert TeamMatchBlockConfig.__dataclass_fields__.keys() == {"contract_version"}
