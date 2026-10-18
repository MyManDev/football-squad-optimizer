"""The mean-reversion projection rule of the laboratory chain.

``mean_reversion_discount_v1`` discounts a later horizon week's deviation from the position
mean by ``rho`` per week of offset and leaves the decision week untouched. What must hold:
the arithmetic on a tiny synthetic table (a blank week stays zero, a double counts twice,
``rho = 1`` is the naive rule exactly, the shrink target is the mean of the full projection
table and not of the pool, the offset counts from the decision week), the two existing
rules keep their arithmetic byte for byte, the factor is refused where it is not read, and
the chain's week record carries the shrink target under the rule and nothing under the
others.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, TEAM_COUNT, make_canonical_gameweeks

from squadopt.experiments import (
    CALENDAR_BLIND_PROJECTION_RULE,
    MEAN_REVERSION_PROJECTION_RULE,
    NAIVE_PROJECTION_RULE,
    PROJECTION_RULES,
    ExperimentConfigurationError,
    SeasonChain,
    SeasonChainConfig,
)
from squadopt.experiments.multi_gw_rehearsal import DecisionSeason, position_means

POOL = {"candidate_pool_per_position": 10, "cheap_pool_per_position": 2}
DECISION = 3
HORIZON = (3, 4, 5)


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


def _chain(rule: str, rho: float | None = None) -> SeasonChain:
    return SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        SeasonChainConfig(season=SEASON, projection_rule=rule, mean_reversion_factor=rho, **POOL),
    )


def _old_arithmetic(chain: SeasonChain, pool: pd.DataFrame, rule: str) -> pd.DataFrame:
    """The frame the two calendar rules built before the mean-reversion rule existed."""

    rows: list[dict[str, object]] = []
    columns = ("player_id", "name", "team_id", "position", "price_tenths", "expected_points")
    for gameweek in HORIZON:
        for player_id, name, team_id, position, price, expected in zip(
            *(pool[column].tolist() for column in columns), strict=True
        ):
            count = chain._fixture_counts.get((gameweek, team_id), 0)
            scale = count if rule == NAIVE_PROJECTION_RULE else min(count, 1)
            rows.append(
                {
                    "gameweek": gameweek,
                    "player_id": player_id,
                    "name": name,
                    "team_id": team_id,
                    "position": position,
                    "price_tenths": int(price),
                    "expected_points": float(expected) * scale,
                    "fixture_count": count,
                    "home_fixture_count": 0,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def naive() -> SeasonChain:
    return _chain(NAIVE_PROJECTION_RULE)


@pytest.fixture(scope="module")
def pool(naive: SeasonChain) -> pd.DataFrame:
    return naive._candidate_pool(naive._projection_at(DECISION))


def test_the_rule_is_registered_beside_the_two_calendar_rules() -> None:
    assert PROJECTION_RULES == (
        NAIVE_PROJECTION_RULE,
        CALENDAR_BLIND_PROJECTION_RULE,
        MEAN_REVERSION_PROJECTION_RULE,
    )
    assert MEAN_REVERSION_PROJECTION_RULE == "mean_reversion_discount_v1"


@pytest.mark.parametrize("rule", [NAIVE_PROJECTION_RULE, CALENDAR_BLIND_PROJECTION_RULE])
def test_the_two_calendar_rules_keep_their_arithmetic(rule: str, pool: pd.DataFrame) -> None:
    chain = _chain(rule)
    frame = chain._naive_horizon(pool, HORIZON).table
    expected = _old_arithmetic(chain, pool, rule)
    assert frame[expected.columns].equals(expected)


def test_rho_one_is_the_naive_rule_exactly(naive: SeasonChain, pool: pd.DataFrame) -> None:
    frame = _chain(MEAN_REVERSION_PROJECTION_RULE, 1.0)._naive_horizon(pool, HORIZON).table
    reference = naive._naive_horizon(pool, HORIZON).table
    assert frame.equals(reference)
    assert frame["expected_points"].tolist() == reference["expected_points"].tolist()


def test_the_later_weeks_regress_toward_the_position_mean_of_the_full_table(
    naive: SeasonChain, pool: pd.DataFrame
) -> None:
    rho = 0.75
    chain = _chain(MEAN_REVERSION_PROJECTION_RULE, rho)
    frame = chain._naive_horizon(pool, HORIZON).table
    reference = naive._naive_horizon(pool, HORIZON).table
    full = naive._projection_at(DECISION)
    means = position_means(full)
    assert means == {
        str(position): float(group["expected_points"].mean())
        for position, group in full.groupby("position")
    }
    # The target is the roster's level, not the pool's: the pool is top-heavy by design.
    pool_means = position_means(pool)
    assert any(abs(pool_means[p] - means[p]) > 1e-9 for p in means)

    decision = frame["gameweek"] == DECISION
    assert frame.loc[decision].equals(reference.loc[decision])
    for offset, gameweek in enumerate(HORIZON):
        if offset == 0:
            continue
        week = frame.loc[frame["gameweek"] == gameweek]
        for row in week.itertuples(index=False):
            expected = float(
                pool.loc[pool["player_id"] == row.player_id, "expected_points"].iloc[0]
            )
            mean = means[str(row.position)]
            base = mean + rho**offset * (expected - mean)
            assert row.expected_points == pytest.approx(max(0.0, base) * row.fixture_count)
    week_four = frame.loc[frame["gameweek"] == 4]
    blanks = week_four.loc[week_four["team_id"] == 6, "expected_points"]
    doubles = week_four.loc[week_four["team_id"] == 1]
    assert not blanks.empty and blanks.eq(0.0).all()
    assert not doubles.empty and (doubles["fixture_count"] == 2).all()
    singles = week_four.loc[week_four["team_id"] == 2]
    # A double counts twice at the regressed level, a single once.
    for row in doubles.itertuples(index=False):
        expected = float(pool.loc[pool["player_id"] == row.player_id, "expected_points"].iloc[0])
        mean = means[str(row.position)]
        assert row.expected_points == pytest.approx(2.0 * max(0.0, mean + rho * (expected - mean)))
    assert (singles["fixture_count"] == 1).all()


def test_the_offset_counts_from_the_decision_week(naive: SeasonChain) -> None:
    chain = _chain(MEAN_REVERSION_PROJECTION_RULE, 0.6)
    pool = naive._candidate_pool(naive._projection_at(4))
    later = chain._naive_horizon(pool, (4, 5)).table
    reference = naive._naive_horizon(pool, (4, 5)).table
    first = later["gameweek"] == 4
    assert later.loc[first].equals(reference.loc[first])
    assert chain._position_means(4) == position_means(naive._projection_at(4))
    assert chain._position_means(4) != chain._position_means(DECISION)


def test_the_rule_names_itself_on_the_horizon(pool: pd.DataFrame) -> None:
    horizon = _chain(MEAN_REVERSION_PROJECTION_RULE, 0.9)._naive_horizon(pool, HORIZON)
    assert horizon.post_processing_contract_version == MEAN_REVERSION_PROJECTION_RULE


@pytest.mark.parametrize(
    ("rule", "rho"),
    [
        (NAIVE_PROJECTION_RULE, 0.75),
        (CALENDAR_BLIND_PROJECTION_RULE, 1.0),
        (MEAN_REVERSION_PROJECTION_RULE, None),
        (MEAN_REVERSION_PROJECTION_RULE, 0.0),
        (MEAN_REVERSION_PROJECTION_RULE, 1.5),
        (MEAN_REVERSION_PROJECTION_RULE, float("nan")),
        (MEAN_REVERSION_PROJECTION_RULE, True),
    ],
)
def test_the_factor_is_refused_where_it_is_not_read_and_required_where_it_is(
    rule: str, rho: object
) -> None:
    with pytest.raises(ExperimentConfigurationError, match="mean_reversion_factor"):
        SeasonChainConfig(season=SEASON, projection_rule=rule, mean_reversion_factor=rho)  # type: ignore[arg-type]
    with pytest.raises(ExperimentConfigurationError, match="mean_reversion_factor"):
        DecisionSeason(
            make_canonical_gameweeks(),
            _fixture_counts(),
            season=SEASON,
            form_window=5,
            candidate_pool_per_position=10,
            cheap_pool_per_position=2,
            cross_season_config=None,
            projection_rule=rule,
            mean_reversion_factor=rho,  # type: ignore[arg-type]
        )


def test_the_week_record_carries_the_shrink_target_only_under_the_rule() -> None:
    reverted = SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        SeasonChainConfig(
            season=SEASON,
            lookahead=2,
            end_gameweek=3,
            projection_rule=MEAN_REVERSION_PROJECTION_RULE,
            mean_reversion_factor=0.75,
            **POOL,  # type: ignore[arg-type]
        ),
    )
    result = reverted.run()
    assert result.diagnostics["projection_rule"] == MEAN_REVERSION_PROJECTION_RULE
    assert result.diagnostics["mean_reversion_factor"] == 0.75
    for week in result.weeks:
        record = week.as_record()
        assert record["position_means"] == dict(reverted._position_means(week.gameweek))
        assert set(record["position_means"]) == {"GK", "DEF", "MID", "FWD"}
    plain = SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        SeasonChainConfig(season=SEASON, lookahead=2, end_gameweek=3, **POOL),  # type: ignore[arg-type]
    ).run()
    assert "mean_reversion_factor" not in plain.diagnostics
    assert all("position_means" not in week.as_record() for week in plain.weeks)
    assert all(week.position_means is None for week in plain.weeks)
