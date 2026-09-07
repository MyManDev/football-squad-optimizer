"""The declared strategy rule: bands on the gap, and nothing that reads as a chance.

The rule is data plus one function, so these tests are the rule's own statement: which
slug each band names, that the edge is written in measured differentials rather than
invented constants, that the edge closes as the season runs out, and that nothing it
publishes could be mistaken for a probability.
"""

import math

import pytest

from squadopt.application.strategies import PUBLISHABLE_FIELDS
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    STRATEGY_CATALOG,
    EvidenceStatus,
    StrategyConfigurationError,
)
from squadopt.application.strategies.rule import (
    BAND_EDGE_DIFFERENTIALS,
    RIVAL_RULE_STRATEGIES,
    RULE_STRATEGIES,
    SEASON_FINAL_GAMEWEEK,
    STRATEGY_RULE_ID,
    WEEKLY_POINTS_DIFFERENTIAL_POINTS,
    GapBand,
    StrategySuggestion,
    band_edge_points,
    gameweeks_remaining,
    suggest_strategy,
)


def _suggest(*, ahead: int, gameweek: int) -> StrategySuggestion:
    return suggest_strategy(
        rival_entry_id=202,
        points_ahead_of_rival=ahead,
        gameweek=gameweek,
        scored_gameweek=gameweek - 1,
    )


# --- the three bands ------------------------------------------------------------------


def test_the_rule_chooses_only_from_the_catalogues_computable_three() -> None:
    assert RULE_STRATEGIES == ("saf-puan", "ortak-koru", "fark-yarat")
    for slug in RULE_STRATEGIES:
        assert slug in STRATEGY_CATALOG
    assert set(RIVAL_RULE_STRATEGIES) < set(RULE_STRATEGIES)


def test_far_enough_behind_with_the_season_running_out_names_fark_yarat() -> None:
    """Mirroring the rival cannot close a gap, so the chaser is sent to the ceiling."""

    edge = band_edge_points(gameweeks_remaining(36))
    suggestion = _suggest(ahead=-int(edge) - 1, gameweek=36)
    assert suggestion.strategy == "fark-yarat"
    assert suggestion.band is GapBand.BEHIND


def test_far_enough_ahead_with_the_season_running_out_names_ortak_koru() -> None:
    """Shared players cancel from the difference, which is what a leader wants."""

    edge = band_edge_points(gameweeks_remaining(36))
    suggestion = _suggest(ahead=int(edge) + 1, gameweek=36)
    assert suggestion.strategy == "ortak-koru"
    assert suggestion.band is GapBand.AHEAD


def test_inside_the_band_the_rule_names_saf_puan() -> None:
    for ahead in (0, 5, -5):
        suggestion = _suggest(ahead=ahead, gameweek=36)
        assert suggestion.strategy == "saf-puan"
        assert suggestion.band is GapBand.LEVEL


def test_the_edge_itself_is_inside_the_band_on_both_sides() -> None:
    """A gap exactly at the edge has not crossed it; the constraint is not yet paid for."""

    edge = int(band_edge_points(gameweeks_remaining(38)))
    assert _suggest(ahead=edge, gameweek=38).strategy == "saf-puan"
    assert _suggest(ahead=-edge, gameweek=38).strategy == "saf-puan"


def test_the_same_gap_early_in_the_season_stays_on_pure_points() -> None:
    """The band is the season's remaining movement: a gap it absorbs in September falls
    outside it in May, so the rule reads the calendar, not a fixed number of points."""

    assert _suggest(ahead=-40, gameweek=4).strategy == "saf-puan"
    assert _suggest(ahead=-40, gameweek=37).strategy == "fark-yarat"


# --- the edge is measured, not invented ------------------------------------------------


def test_the_band_edge_is_written_in_measured_differentials() -> None:
    for weeks in (0, 1, 5, 19, 38):
        expected = BAND_EDGE_DIFFERENTIALS * WEEKLY_POINTS_DIFFERENTIAL_POINTS * math.sqrt(weeks)
        assert band_edge_points(weeks) == pytest.approx(expected, abs=0.06)


def test_the_band_edge_closes_as_the_season_runs_out() -> None:
    edges = [band_edge_points(gameweeks_remaining(gw)) for gw in range(1, 39)]
    assert edges == sorted(edges, reverse=True)
    assert band_edge_points(gameweeks_remaining(38)) == pytest.approx(
        WEEKLY_POINTS_DIFFERENTIAL_POINTS, abs=0.06
    )


def test_weeks_remaining_counts_the_week_being_decided_and_never_goes_negative() -> None:
    assert gameweeks_remaining(1) == SEASON_FINAL_GAMEWEEK
    assert gameweeks_remaining(SEASON_FINAL_GAMEWEEK) == 1
    assert gameweeks_remaining(SEASON_FINAL_GAMEWEEK + 4) == 0


# --- the envelope ----------------------------------------------------------------------


def test_the_published_suggestion_carries_the_rules_identity_and_its_inputs() -> None:
    published = _suggest(ahead=-77, gameweek=36).to_dict()
    assert published["rule_id"] == STRATEGY_RULE_ID
    assert published["points_ahead_of_rival"] == -77
    assert published["gameweeks_remaining"] == gameweeks_remaining(36)
    # The inputs and the edge together are enough to re-derive the answer.
    assert published["band_edge_points"] == band_edge_points(gameweeks_remaining(36))
    assert published["strategy"] in RULE_STRATEGIES


def test_nothing_the_rule_publishes_is_shaped_like_a_probability() -> None:
    published = _suggest(ahead=-77, gameweek=36).to_dict()
    for key, value in published.items():
        assert not FORBIDDEN_FIELD_PATTERN.search(str(key)), key
        assert not FORBIDDEN_FIELD_PATTERN.search(str(value)), value
    assert "suggested_strategy" in PUBLISHABLE_FIELDS
    assert not FORBIDDEN_FIELD_PATTERN.search("suggested_strategy")


def test_the_rule_claims_no_measured_edge_over_the_strategies_it_names() -> None:
    """The rule may not quietly become a verdict: all three are still pre-registered."""

    for slug in RULE_STRATEGIES:
        assert STRATEGY_CATALOG[slug].evidence is not EvidenceStatus.GATED_PASS


def test_a_non_integer_input_is_refused_rather_than_coerced() -> None:
    for bad in (1.5, "3", True, None):
        with pytest.raises(StrategyConfigurationError):
            suggest_strategy(
                rival_entry_id=202,
                points_ahead_of_rival=bad,  # type: ignore[arg-type]
                gameweek=36,
                scored_gameweek=35,
            )
