"""Mode-aware plan selection: scoring arithmetic, mode targets, and tie-breaking.

Synthetic paths and hand-built plans — no solver runs here; candidate generation is
exercised end to end in the measurement script, and its pieces (the planner, the paths)
have their own suites.
"""

from types import MappingProxyType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.plan_selection import (
    MODES,
    CandidatePlan,
    rival_window_scores,
    score_candidate_on_paths,
    select_plan,
)
from squadopt.scenarios.evaluation import RivalSquad

PLAYERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
GAMEWEEKS = (8, 9, 10)


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


def _paths(*, scenarios: int = 100, seed: int = 0) -> _FakePaths:
    generator = np.random.default_rng(seed)
    matrices = {
        gameweek: pd.DataFrame(
            generator.uniform(0.0, 8.0, size=(scenarios, len(PLAYERS))),
            columns=PLAYERS,
        )
        for gameweek in GAMEWEEKS
    }
    return _FakePaths(matrices, scenarios)


def _plan(
    *,
    starters: list[int],
    captain: int,
    chips: dict[int, str] | None = None,
    hit_points: float = 0.0,
) -> CandidatePlan:
    weeks = tuple(
        SimpleNamespace(
            gameweek=gameweek,
            starting_xi=pd.DataFrame({"player_id": starters}),
            bench=pd.DataFrame({"player_id": [p for p in PLAYERS if p not in starters]}),
            captain=pd.Series({"player_id": captain}),
            transfer_hit_points=hit_points,
        )
        for gameweek in GAMEWEEKS
    )
    plan = SimpleNamespace(weeks=weeks, chips_played=MappingProxyType(chips or {}))
    return CandidatePlan(label="synthetic", plan=plan)  # type: ignore[arg-type]


def test_a_plain_week_scores_starters_plus_captain() -> None:
    paths = _paths()
    starters = PLAYERS[:11]
    candidate = _plan(starters=starters, captain=1)
    scores = score_candidate_on_paths(candidate, paths)  # type: ignore[arg-type]
    expected = sum(
        paths.week(gw)[starters].to_numpy().sum(axis=1) + paths.week(gw)[1].to_numpy()
        for gw in GAMEWEEKS
    )
    np.testing.assert_allclose(scores, expected)


def test_a_triple_captain_week_counts_the_captain_three_times() -> None:
    paths = _paths()
    starters = PLAYERS[:11]
    plain = score_candidate_on_paths(_plan(starters=starters, captain=1), paths)  # type: ignore[arg-type]
    tripled = score_candidate_on_paths(
        _plan(starters=starters, captain=1, chips={9: "3xc"}),
        paths,  # type: ignore[arg-type]
    )
    np.testing.assert_allclose(tripled - plain, paths.week(9)[1].to_numpy())


def test_a_bench_boost_week_adds_the_bench() -> None:
    paths = _paths()
    starters = PLAYERS[:11]
    bench = PLAYERS[11:]
    plain = score_candidate_on_paths(_plan(starters=starters, captain=1), paths)  # type: ignore[arg-type]
    boosted = score_candidate_on_paths(
        _plan(starters=starters, captain=1, chips={10: "bboost"}),
        paths,  # type: ignore[arg-type]
    )
    np.testing.assert_allclose(boosted - plain, paths.week(10)[bench].to_numpy().sum(axis=1))


def test_transfer_hits_are_charged_per_week() -> None:
    paths = _paths()
    starters = PLAYERS[:11]
    free = score_candidate_on_paths(_plan(starters=starters, captain=1), paths)  # type: ignore[arg-type]
    hit = score_candidate_on_paths(
        _plan(starters=starters, captain=1, hit_points=4.0),
        paths,  # type: ignore[arg-type]
    )
    np.testing.assert_allclose(free - hit, np.full(100, 12.0))


def test_a_plan_missing_a_window_week_is_refused() -> None:
    paths = _paths()
    candidate = _plan(starters=PLAYERS[:11], captain=1)
    short = CandidatePlan(
        label="short",
        plan=SimpleNamespace(  # type: ignore[arg-type]
            weeks=candidate.plan.weeks[:2], chips_played=MappingProxyType({})
        ),
    )
    with pytest.raises(ExperimentExecutionError, match="no week for"):
        score_candidate_on_paths(short, paths)  # type: ignore[arg-type]


def test_the_rival_scores_like_a_plain_squad() -> None:
    paths = _paths()
    rival = RivalSquad("crowd", tuple(PLAYERS[:11]), 2)
    scores = rival_window_scores(rival, paths)  # type: ignore[arg-type]
    expected = sum(
        paths.week(gw)[PLAYERS[:11]].to_numpy().sum(axis=1) + paths.week(gw)[2].to_numpy()
        for gw in GAMEWEEKS
    )
    np.testing.assert_allclose(scores, expected)


def test_each_mode_picks_the_candidate_its_name_promises() -> None:
    """A safe squad, an aggressive one, and modes that must disagree about them.

    The safe candidate matches the rival almost exactly (tiny constant edge); the
    aggressive one is the rival plus noise with a small positive drift. Garantici must
    prefer the safe one (never behind); Asiri Agresif must prefer the aggressive one
    (only variance clears a five-point margin).
    """

    scenarios = 4000
    rival = RivalSquad("crowd", tuple(PLAYERS[:11]), 1)
    generator = np.random.default_rng(7)
    base = generator.uniform(2.0, 6.0, size=(scenarios, len(PLAYERS)))
    matrices = {gw: pd.DataFrame(base.copy(), columns=PLAYERS) for gw in GAMEWEEKS}
    paths = _FakePaths(matrices, scenarios)

    safe = _plan(starters=PLAYERS[:11], captain=1)
    aggressive = _plan(starters=[12, *PLAYERS[1:11]], captain=2)
    # Player 12 is player 1 plus noise and a small drift, so the aggressive squad wins
    # big sometimes and loses sometimes; the safe squad never loses.
    for gw in GAMEWEEKS:
        frame = paths.week(gw)
        frame[12] = frame[1] + generator.normal(0.7, 6.0, scenarios)
        frame[1] = frame[1] + 0.01  # the safe squad's tiny certain edge

    safe = CandidatePlan(label="safe", plan=safe.plan)
    aggressive = CandidatePlan(label="aggressive", plan=aggressive.plan)
    selection = select_plan([safe, aggressive], paths, rival)  # type: ignore[arg-type]
    assert selection.recommended["garantici"] == "safe"
    assert selection.recommended["asiri_agresif"] == "aggressive"
    garantici_safe = next(
        v for v in selection.verdicts if v.mode == "garantici" and v.candidate == "safe"
    )
    assert garantici_safe.probability_success == pytest.approx(1.0)
    assert garantici_safe.probability_behind == pytest.approx(0.0)


def test_saf_puan_ignores_the_rival_entirely() -> None:
    paths = _paths()
    strong = CandidatePlan(label="strong", plan=_plan(starters=PLAYERS[:11], captain=1).plan)
    weak = CandidatePlan(label="weak", plan=_plan(starters=PLAYERS[4:15], captain=15).plan)
    with_rival = select_plan(
        [strong, weak],
        paths,
        RivalSquad("crowd", tuple(PLAYERS[:11]), 1),  # type: ignore[arg-type]
    )
    without = select_plan([strong, weak], paths, None)  # type: ignore[arg-type]
    assert with_rival.recommended["saf_puan"] == without.recommended["saf_puan"]
    assert "garantici" not in without.recommended
    saf = next(v for v in without.verdicts if v.mode == "saf_puan" and v.candidate == "strong")
    assert saf.probability_success is None
    assert saf.probability_behind is None


def test_ties_break_toward_fewer_chips() -> None:
    """Identical elevens, one burning a chip for nothing: the chip must not be recommended."""

    paths = _paths()
    plain = CandidatePlan(label="plain", plan=_plan(starters=PLAYERS[:11], captain=1).plan)
    burner_plan = _plan(starters=PLAYERS[:11], captain=1, chips={9: "3xc"})
    # Neutralise the chip's effect so the two candidates tie exactly.
    paths.week(9)[1] = 0.0
    burner = CandidatePlan(label="a_burner", plan=burner_plan.plan)
    selection = select_plan([burner, plain], paths, None)  # type: ignore[arg-type]
    assert selection.recommended["saf_puan"] == "plain"


def test_an_empty_menu_is_refused() -> None:
    with pytest.raises(ExperimentConfigurationError, match="At least one"):
        select_plan([], _paths(), None)  # type: ignore[arg-type]


def test_the_mode_table_is_the_declared_one() -> None:
    assert set(MODES) == {"saf_puan", "garantici", "agresif", "asiri_agresif"}
    assert MODES["saf_puan"]["rival_aware"] is False
    assert MODES["garantici"]["level_counts"] is True
    assert MODES["asiri_agresif"]["margin"] == 5.0


def test_a_zero_edge_selection_is_the_historical_one() -> None:
    paths = _paths()
    rival = RivalSquad("crowd", tuple(PLAYERS[:11]), 1)
    strong = CandidatePlan(label="strong", plan=_plan(starters=PLAYERS[:11], captain=1).plan)
    base = select_plan([strong], paths, rival)  # type: ignore[arg-type]
    explicit = select_plan(
        [strong],
        paths,
        rival,
        rival_edge_points_per_week=0.0,  # type: ignore[arg-type]
    )
    assert base.verdicts == explicit.verdicts
    assert explicit.diagnostics["rival_edge_points_per_week"] == 0.0


def test_the_edge_is_charged_once_per_week_of_the_window() -> None:
    paths = _paths()
    rival = RivalSquad("crowd", tuple(PLAYERS[:11]), 1)
    base = rival_window_scores(rival, paths)  # type: ignore[arg-type]
    edged = rival_window_scores(
        rival,
        paths,
        rival_edge_points_per_week=7.19,  # type: ignore[arg-type]
    )
    np.testing.assert_allclose(edged - base, np.full(100, 7.19 * len(GAMEWEEKS)))


def test_an_edged_crowd_deflates_every_competitive_success_probability() -> None:
    paths = _paths()
    rival = RivalSquad("crowd", tuple(PLAYERS[:11]), 1)
    strong = CandidatePlan(label="strong", plan=_plan(starters=PLAYERS[:11], captain=2).plan)
    base = select_plan([strong], paths, rival)  # type: ignore[arg-type]
    edged = select_plan(
        [strong],
        paths,
        rival,
        rival_edge_points_per_week=50.0,  # type: ignore[arg-type]
    )
    for before, after in zip(base.verdicts, edged.verdicts, strict=True):
        if before.probability_success is not None:
            assert after.probability_success <= before.probability_success
            assert after.probability_behind >= before.probability_behind
