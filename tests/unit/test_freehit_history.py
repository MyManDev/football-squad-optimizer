"""Historical Free Hit eligibility through the actual live transfer path."""

from types import SimpleNamespace

import pandas as pd
import pytest

from squadopt.data.errors import DataSourceError
from squadopt.live.rules import (
    SEASON_RULES_CONTRACT_VERSION,
    ChipWindow,
    ScoringRules,
    SeasonRules,
    TransferRules,
)
from squadopt.live.transfers import HeldSquad, plan_transfers
from squadopt.optimization import OptimizationConfig
from tests.unit.test_live_transfers import _elements, _game_config


@pytest.mark.parametrize("gameweek,allowed", [(20, False), (21, True)])
def test_live_free_hit_respects_previous_week_even_when_rights_renew(
    gameweek: int, allowed: bool
) -> None:
    table = pd.DataFrame(
        {
            "player_id": e["code"],
            "name": e["second_name"],
            "team_id": f"Club {e['team']}",
            "position": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[e["element_type"]],
            "price_tenths": e["now_cost"],
            "expected_points": 5.0,
        }
        for e in _elements()
    )
    ids = (1001, 1002, 1004, 1005, 1006, 1007, 1008, 1012, 1013, 1014, 1015, 1016, 1020, 1021, 1022)
    prices = table.set_index("player_id").price_tenths.to_dict()
    held = HeldSquad(
        "2026-27", gameweek - 1, ids, {p: prices[p] for p in ids},
        1000 - sum(prices[p] for p in ids), 2, {"freehit": (19,)},
    )
    rules = SeasonRules(
        SEASON_RULES_CONTRACT_VERSION, "2026-27", "capture",
        ScoringRules(**_game_config()["scoring"]),
        TransferRules(15, 11, 3, 1000, 4, 20, 0.5, False),
        (
            ChipWindow("freehit", 1, 2, 19, "transfer"),
            ChipWindow("freehit", 1, 20, 38, "transfer"),
        ),
    )
    inputs = SimpleNamespace(season="2026-27", deadline=SimpleNamespace(gameweek=gameweek))
    projection = SimpleNamespace(table=table)
    if not allowed:
        with pytest.raises(DataSourceError, match="cannot be played"):
            plan_transfers(inputs, projection, held, rules, chip="freehit")
    else:
        plan, decision, _ = plan_transfers(
            inputs, projection, held, rules, chip="freehit",
            optimization=OptimizationConfig(solver_time_limit_seconds=10),
        )
        assert decision.chip == "freehit"
        assert plan.chips_played == {gameweek: "freehit"}

