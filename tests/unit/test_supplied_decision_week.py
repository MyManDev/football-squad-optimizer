"""A season chain walked on a forecast handed to it for each decision gameweek.

``supplied_decision_week_v1`` replaces the form-window control with the caller's tables.
What must hold: handing the chain the control's own tables reproduces the calendar-blind
chain week for week, so the plumbing adds and loses nothing; a double is not scaled a second
time and a blank stays zero; a different forecast decides a different squad; the rule plans
one gameweek only; and a table that is missing, malformed or on foreign team labels is
refused instead of read as something else.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, TEAM_COUNT, make_canonical_gameweeks

from squadopt.experiments import (
    CALENDAR_BLIND_PROJECTION_RULE,
    NAIVE_PROJECTION_RULE,
    PROJECTION_RULES,
    SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
    DecisionWeekProjections,
    ExperimentConfigurationError,
    ExperimentExecutionError,
    SeasonChain,
    SeasonChainConfig,
)

POOL = {"candidate_pool_per_position": 10, "cheap_pool_per_position": 2}
MODEL = "a_forecast_v1"


def _fixture_counts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(1, 9):
        for team_id in range(1, TEAM_COUNT + 1):
            count = 1
            if gameweek == 4 and team_id == 1:
                count = 2
            if gameweek == 4 and team_id == 6:
                count = 0
            rows.append({"gameweek": gameweek, "team_id": team_id, "fixture_count": count})
    return pd.DataFrame(rows)


def _control(rule: str = CALENDAR_BLIND_PROJECTION_RULE) -> SeasonChain:
    return SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        SeasonChainConfig(season=SEASON, projection_rule=rule, **POOL),  # type: ignore[arg-type]
    )


def _control_tables() -> dict[int, pd.DataFrame]:
    control = _control()
    return {gameweek: control._projection_at(gameweek) for gameweek in control.available_gameweeks}


def _supplied(tables: dict[int, pd.DataFrame], **overrides: object) -> SeasonChain:
    settings = SeasonChainConfig(
        season=SEASON,
        projection_rule=SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
        **POOL,  # type: ignore[arg-type]
        **overrides,  # type: ignore[arg-type]
    )
    return SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        settings,
        decision_projections=DecisionWeekProjections(model_version=MODEL, tables=tables),
    )


def test_the_rule_is_registered_after_the_three_control_rules() -> None:
    assert PROJECTION_RULES[-1] == SUPPLIED_DECISION_WEEK_PROJECTION_RULE
    assert SUPPLIED_DECISION_WEEK_PROJECTION_RULE == "supplied_decision_week_v1"


def test_the_control_handed_back_walks_the_calendar_blind_chain_week_for_week() -> None:
    blind = _control().run()
    supplied = _supplied(_control_tables()).run()
    assert supplied.opening_squad_ids == blind.opening_squad_ids
    assert [week.as_record() for week in supplied.weeks] == [
        week.as_record() for week in blind.weeks
    ]
    assert supplied.diagnostics["projection_rule"] == SUPPLIED_DECISION_WEEK_PROJECTION_RULE
    assert supplied.diagnostics["decision_projection_model"] == MODEL
    assert "decision_projection_model" not in blind.diagnostics


def test_a_double_is_not_scaled_again_and_a_blank_is_zero() -> None:
    chain = _supplied(_control_tables())
    table = chain._projection_at(4)
    horizon = chain._naive_horizon(table, (4,))
    frame = horizon.table
    projected = dict(zip(frame["player_id"], frame["expected_points"], strict=True))
    forecast = dict(zip(table["player_id"], table["expected_points"], strict=True))
    team = dict(zip(table["player_id"], table["team_id"], strict=True))
    doubles = [player for player, club in team.items() if club == 1]
    blanks = [player for player, club in team.items() if club == 6]
    assert doubles and blanks
    assert all(projected[player] == forecast[player] for player in doubles)
    assert all(projected[player] == 0.0 for player in blanks)
    assert horizon.model_version == MODEL


def test_a_different_forecast_decides_a_different_squad() -> None:
    tables = _control_tables()
    reversed_tables = {}
    for gameweek, table in tables.items():
        flipped = table.copy(deep=True)
        flipped["expected_points"] = flipped["expected_points"].max() - flipped["expected_points"]
        reversed_tables[gameweek] = flipped
    assert (
        _supplied(reversed_tables).run().opening_squad_ids
        != _supplied(tables).run().opening_squad_ids
    )


def test_the_rule_plans_one_gameweek_only() -> None:
    with pytest.raises(ExperimentConfigurationError, match="lookahead 1"):
        _supplied(_control_tables(), lookahead=2)
    chain = _supplied(_control_tables())
    pool = chain._candidate_pool(chain._projection_at(3))
    with pytest.raises(ExperimentExecutionError, match="decision gameweek"):
        chain._naive_horizon(pool, (3, 4))


def test_the_tables_are_needed_under_the_rule_and_refused_under_any_other() -> None:
    with pytest.raises(ExperimentConfigurationError, match="needs decision_projections"):
        _control(SUPPLIED_DECISION_WEEK_PROJECTION_RULE)
    with pytest.raises(ExperimentConfigurationError, match="refuses one"):
        SeasonChain(
            make_canonical_gameweeks(),
            _fixture_counts(),
            SeasonChainConfig(season=SEASON, projection_rule=NAIVE_PROJECTION_RULE, **POOL),  # type: ignore[arg-type]
            decision_projections=DecisionWeekProjections(
                model_version=MODEL, tables=_control_tables()
            ),
        )


def test_a_gameweek_without_a_table_stops_the_walk() -> None:
    tables = _control_tables()
    del tables[5]
    with pytest.raises(ExperimentExecutionError, match="No projection was supplied for gameweek 5"):
        _supplied(tables).run()


def test_foreign_team_labels_are_a_mismatch_and_not_a_blank_week() -> None:
    tables = {
        gameweek: table.assign(team_id=table["team_id"].map(lambda club: f"club-{club}"))
        for gameweek, table in _control_tables().items()
    }
    with pytest.raises(ExperimentExecutionError, match="team labels"):
        _supplied(tables).run()


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda table: table.drop(columns="price_tenths"), "missing columns"),
        (lambda table: pd.concat([table, table.head(1)], ignore_index=True), "one row a player"),
        (lambda table: table.assign(expected_points=float("nan")), "finite forecast"),
        (lambda table: table.assign(expected_points=float("inf")), "finite forecast"),
        (lambda table: table.head(0), "one row a player"),
    ],
)
def test_a_malformed_table_is_refused(damage: object, message: str) -> None:
    tables = _control_tables()
    tables[3] = damage(tables[3])  # type: ignore[operator]
    with pytest.raises(ExperimentConfigurationError, match=message):
        DecisionWeekProjections(model_version=MODEL, tables=tables)


def test_the_tables_need_a_name_and_a_gameweek() -> None:
    tables = _control_tables()
    with pytest.raises(ExperimentConfigurationError, match="model_version"):
        DecisionWeekProjections(model_version=" ", tables=tables)
    with pytest.raises(ExperimentConfigurationError, match="at least one decision gameweek"):
        DecisionWeekProjections(model_version=MODEL, tables={})
    with pytest.raises(ExperimentConfigurationError, match="positive integer"):
        DecisionWeekProjections(model_version=MODEL, tables={0: tables[3]})


def test_the_kept_tables_do_not_follow_the_caller_s_frame() -> None:
    tables = _control_tables()
    kept = DecisionWeekProjections(model_version=MODEL, tables=tables)
    before = kept.tables[3]["expected_points"].tolist()
    tables[3]["expected_points"] = 0.0
    assert kept.tables[3]["expected_points"].tolist() == before
