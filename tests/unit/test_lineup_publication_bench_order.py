"""What the member sees is what the official scorer would produce, by delegation.

The planning horizon narrows ``appearance_probability`` away, so the shared rule meets no
chance on this path and falls back. That is the point rather than a gap: the page and the
scorer call one function, so the docstring's promise holds by construction instead of by
two hand-written sorts happening to agree, and the day the horizon carries the column the
page follows with no edit here.
"""

import pandas as pd

from squadopt.application.lineup_publication import lineup_fields
from squadopt.contracts import order_outfield_bench
from squadopt.planning.models import PlanningWeekResult

_POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _squad(points: list[float], **extra: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "player_id": list(range(1, len(_POSITIONS) + 1)),
            "name": [f"Player {index}" for index in range(1, len(_POSITIONS) + 1)],
            "team_id": [index % 10 + 1 for index in range(len(_POSITIONS))],
            "position": _POSITIONS,
            "price_tenths": [45 + index for index in range(len(_POSITIONS))],
            "expected_points": points,
        }
    )
    for column, values in extra.items():
        frame[column] = values
    return frame


def _week(squad: pd.DataFrame) -> PlanningWeekResult:
    """One solved week: eleven starters, a four-player bench holding one goalkeeper."""

    starters = squad.loc[[0, *range(2, 12)]]
    bench = squad.loc[[1, 12, 13, 14]]
    empty = squad.iloc[0:0]
    return PlanningWeekResult(
        gameweek=6,
        selected_squad=squad,
        starting_xi=starters,
        bench=bench,
        captain=starters.iloc[0],
        transfers_in=empty,
        transfers_out=empty,
        bank_before_tenths=0,
        bank_after_tenths=0,
        free_transfers_before=1,
        free_transfers_unused=1,
        free_transfers_for_next_gameweek=2,
        transfer_count=0,
        paid_transfer_count=0,
        transfer_hit_points=0.0,
        projected_score=0.0,
        projected_bench_points=0.0,
        discounted_objective_contribution=0.0,
    )


def _points() -> list[float]:
    return [6.0, 1.0, *(2.0 + index * 0.1 for index in range(10)), 5.0, 3.0, 4.0]


def test_the_published_bench_is_the_goalkeeper_then_descending_points() -> None:
    """Today's order, unchanged: the planning week states no appearance chance."""

    fields = lineup_fields(_week(_squad(_points())))
    bench = [int(str(row["player_id"])) for row in fields["bench"]]  # type: ignore[index]

    assert bench[0] == 2
    assert bench[1:] == [13, 15, 14]


def test_the_page_and_the_shared_rule_answer_the_same_thing() -> None:
    """The claim the docstring makes, held by the function both sides call."""

    week = _week(_squad(_points()))
    fields = lineup_fields(week)
    outfield = week.bench.loc[week.bench["position"] != "GK"]

    published = [int(str(row["player_id"])) for row in fields["bench"]][1:]  # type: ignore[index]
    assert published == [int(v) for v in order_outfield_bench(outfield)["player_id"]]


def test_a_week_that_did_carry_the_chance_would_publish_the_conditional_order() -> None:
    """Nothing produces this on the planning path today, which is why it is constructed.

    It holds that the page is wired to the rule rather than to the fallback: the day the
    projection horizon carries the column, this is the order a member sees, and no edit in
    ``lineup_publication`` is needed to get it.
    """

    chances = [1.0] * 12 + [1.0, 0.5, 0.4]
    week = _week(_squad(_points(), appearance_probability=chances))

    bench = [int(str(row["player_id"])) for row in lineup_fields(week)["bench"]]  # type: ignore[index]

    # 5.0/1.0, 3.0/0.5 and 4.0/0.4 are 5.0, 6.0 and 10.0, so the order inverts.
    assert bench == [2, 15, 14, 13]
