"""Member mode selection: the bridge's rules, on synthetic paths and hand-built menus.

The halves this module bridges have their own suites — the menu's guarantees in
`test_transfer_menu`, the scoring arithmetic and mode targets in `test_plan_selection`.
What is under test here is the bridge itself: the rival rule, the price tags, the
one-week limit, and that no probability ever reaches the advice surface.
"""

from types import MappingProxyType, SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from squadopt.application.entries import EntryPicks
from squadopt.application.mode_selection import (
    MEMBER_MODE_SELECTION_CONTRACT_VERSION,
    MODE_SLUGS,
    ModeAdvice,
    ModeSelectionError,
    build_mode_paths,
    choose_rival,
    rival_squad_from_picks,
    select_member_modes,
)
from squadopt.scenarios.evaluation import RivalSquad

PLAYERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
GAMEWEEK = 9


class _FakePaths:
    """Just enough of a ScenarioPathSet for the scoring arithmetic."""

    def __init__(self, matrices: dict[int, pd.DataFrame], scenario_count: int) -> None:
        self._matrices = matrices
        self.target = SimpleNamespace(
            gameweeks=tuple(matrices), horizon=len(matrices), window_id="synthetic"
        )
        self.config = SimpleNamespace(scenario_count=scenario_count)

    def week(self, gameweek: int) -> pd.DataFrame:
        return self._matrices[gameweek]


def _paths(
    *, scenarios: int = 200, seed: int = 0, gameweeks: tuple[int, ...] = (GAMEWEEK,)
) -> _FakePaths:
    generator = np.random.default_rng(seed)
    matrices = {
        gameweek: pd.DataFrame(
            generator.uniform(0.0, 8.0, size=(scenarios, len(PLAYERS))),
            columns=PLAYERS,
        )
        for gameweek in gameweeks
    }
    return _FakePaths(matrices, scenarios)


def _menu_entry(
    *,
    starters: list[int],
    captain: int,
    hit_points: float = 0.0,
    name: str,
) -> tuple[Any, Any]:
    plan = SimpleNamespace(
        weeks=(
            SimpleNamespace(
                gameweek=GAMEWEEK,
                starting_xi=pd.DataFrame({"player_id": starters}),
                bench=pd.DataFrame({"player_id": [p for p in PLAYERS if p not in starters]}),
                captain=pd.Series({"player_id": captain}),
                transfer_hit_points=hit_points,
            ),
        ),
        chips_played=MappingProxyType({}),
        # The selection record serializes these three from every real TransferPlanResult.
        total_projected_score=0.0,
        total_transfer_hit_points=hit_points,
        solver_status=SimpleNamespace(name="OPTIMAL"),
    )
    decision = SimpleNamespace(name=name)
    return plan, decision


def _picks(entry_id: int, *, captain: int = 1) -> EntryPicks:
    return EntryPicks(
        entry_id=entry_id,
        season="2026-27",
        gameweek=1,
        squad=tuple(PLAYERS),
        starting_xi=tuple(PLAYERS[:11]),
        captain=captain,
        bank_tenths=0,
        free_transfers=1,
        free_transfers_known=False,
    )


def test_a_rival_squad_is_the_members_public_eleven() -> None:
    rival = rival_squad_from_picks(_picks(7, captain=3), label="Third FC")
    assert rival.label == "Third FC"
    assert rival.starter_ids == tuple(PLAYERS[:11])
    assert rival.captain_id == 3


def test_the_rival_is_the_nearest_member_above() -> None:
    squads = {n: RivalSquad(f"entry-{n}", tuple(PLAYERS[:11]), 1) for n in (10, 20, 30)}
    ranks = {10: 1, 20: 2, 30: 3, 40: 4}
    assert choose_rival(40, ranks, squads) is squads[30]
    assert choose_rival(30, ranks, {10: squads[10], 20: squads[20]}) is squads[20]


def test_the_leader_defends_against_the_nearest_below() -> None:
    candidates = {n: RivalSquad(f"entry-{n}", tuple(PLAYERS[:11]), 1) for n in (20, 30)}
    assert choose_rival(10, {10: 1, 20: 2, 30: 3}, candidates) is candidates[20]


def test_no_standing_or_no_candidates_means_no_rival() -> None:
    candidates = {20: RivalSquad("entry-20", tuple(PLAYERS[:11]), 1)}
    assert choose_rival(10, {20: 2}, candidates) is None
    assert choose_rival(10, {10: 1}, {}) is None


def test_a_member_in_their_own_candidates_is_refused() -> None:
    candidates = {10: RivalSquad("entry-10", tuple(PLAYERS[:11]), 1)}
    with pytest.raises(ModeSelectionError, match="never their own rival"):
        choose_rival(10, {10: 1}, candidates)


def test_every_mode_gets_advice_and_prices_are_against_the_pure_pick() -> None:
    paths = _paths()
    menu = [
        _menu_entry(starters=PLAYERS[:11], captain=1, name="first"),
        _menu_entry(starters=PLAYERS[4:15], captain=15, name="second"),
    ]
    rival = RivalSquad("neighbour", tuple(PLAYERS[2:13]), 5)

    result = select_member_modes(menu, paths, rival)  # type: ignore[arg-type]

    assert result.contract_version == MEMBER_MODE_SELECTION_CONTRACT_VERSION
    assert result.gameweek == GAMEWEEK
    assert {item.mode for item in result.advice} == set(MODE_SLUGS.values())
    by_mode = result.by_mode()
    assert by_mode["saf-puan"].expected_points_cost == 0.0
    assert by_mode["saf-puan"].rival_label is None
    for slug in ("garantici", "agresif", "asiri-agresif"):
        assert by_mode[slug].expected_points_cost >= 0.0
        assert by_mode[slug].rival_label == "neighbour"
    for item in result.advice:
        assert item.decision is menu[item.plan_index][1]


def test_without_a_rival_only_the_pure_mode_is_computed() -> None:
    paths = _paths()
    menu = [_menu_entry(starters=PLAYERS[:11], captain=1, name="only")]

    result = select_member_modes(menu, paths, None)  # type: ignore[arg-type]

    assert [item.mode for item in result.advice] == ["saf-puan"]
    assert result.advice[0].expected_points_cost == 0.0


def test_every_mode_now_picks_the_expected_points_winner() -> None:
    """A perfect win-share no longer buys the safe plan the Garantici pick.

    The selector under it (`select_plan`) reads expected points only; the win-shares
    are diagnostics. Until the strategies declare structural constraints of their own,
    the modes agree on the same menu entry and their price tags are honestly zero —
    the disagreement that returns later comes from declared constraints, not from a
    probability.
    """

    scenarios = 4000
    generator = np.random.default_rng(7)
    base = generator.uniform(2.0, 6.0, size=(scenarios, len(PLAYERS)))
    matrices = {GAMEWEEK: pd.DataFrame(base.copy(), columns=PLAYERS)}
    paths = _FakePaths(matrices, scenarios)
    frame = paths.week(GAMEWEEK)
    # Player 12 is player 1 plus noise and a drift: the risky eleven wins the mean, the
    # safe eleven never falls behind the rival.
    frame[12] = frame[1] + generator.normal(0.7, 6.0, scenarios)
    frame[1] = frame[1] + 0.01
    rival = RivalSquad("neighbour", tuple(PLAYERS[:11]), 1)
    menu = [
        _menu_entry(starters=[12, *PLAYERS[1:11]], captain=2, name="risky"),
        _menu_entry(starters=PLAYERS[:11], captain=1, name="safe"),
    ]

    result = select_member_modes(menu, paths, rival)  # type: ignore[arg-type]

    by_mode = result.by_mode()
    for slug in ("garantici", "agresif", "asiri-agresif", "saf-puan"):
        assert by_mode[slug].decision.name == "risky"  # type: ignore[attr-defined]
        assert by_mode[slug].expected_points_cost == 0.0


def test_the_advice_surface_carries_no_probability() -> None:
    """The price tag is the only number a mode may publish; probabilities stay internal."""

    fields = set(ModeAdvice.__dataclass_fields__)
    assert fields == {
        "mode",
        "plan_index",
        "decision",
        "expected_window_score",
        "expected_points_cost",
        "rival_label",
    }
    assert not any("probability" in name for name in fields)


def test_the_unmeasured_rival_edge_is_recorded_as_the_assumption_it_is() -> None:
    paths = _paths()
    menu = [_menu_entry(starters=PLAYERS[:11], captain=1, name="only")]
    rival = RivalSquad("neighbour", tuple(PLAYERS[2:13]), 5)
    result = select_member_modes(menu, paths, rival)  # type: ignore[arg-type]
    assert result.diagnostics["rival_edge_points_per_week"] == 0.0
    assert "unmeasured" in str(result.diagnostics["rival_edge_note"]).lower()


def _identity(**overrides: str) -> SimpleNamespace:
    values = {
        "model_name": "m",
        "model_version": "1",
        "feature_contract_version": "f1",
        "post_processing_contract_version": "p1",
    }
    values.update(overrides)
    return SimpleNamespace(**values, table=None, source_id="test")


def test_mode_paths_refuse_a_residual_history_from_another_model() -> None:
    projection = SimpleNamespace(
        diagnostics={
            "model_name": "m",
            "model_version": "2",
            "feature_contract_version": "f1",
            "availability_contract_version": "p1",
        },
        table=None,
    )
    with pytest.raises(ModeSelectionError, match="different model contract"):
        build_mode_paths(
            projection,  # type: ignore[arg-type]
            _identity(),  # type: ignore[arg-type]
            season="2026-27",
            gameweek=2,
        )


def test_mode_paths_refuse_a_projection_without_provenance() -> None:
    projection = SimpleNamespace(
        diagnostics={
            "model_name": "m",
            "model_version": "1",
            "feature_contract_version": "f1",
            "availability_contract_version": "p1",
        },
        table=None,
    )
    with pytest.raises(ModeSelectionError, match="training_cutoff"):
        build_mode_paths(
            projection,  # type: ignore[arg-type]
            _identity(),  # type: ignore[arg-type]
            season="2026-27",
            gameweek=2,
        )


def test_an_empty_menu_is_refused() -> None:
    with pytest.raises(ModeSelectionError, match="at least one"):
        select_member_modes([], _paths(), None)  # type: ignore[arg-type]


def test_a_window_wider_than_one_week_is_refused() -> None:
    paths = _paths(gameweeks=(9, 10))
    menu = [_menu_entry(starters=PLAYERS[:11], captain=1, name="only")]
    with pytest.raises(ModeSelectionError, match="one deadline"):
        select_member_modes(menu, paths, None)  # type: ignore[arg-type]
