"""The strategy catalogue's honesty is structural: these tests are the structure."""

import re

import pytest

from squadopt.application.strategies import (
    PUBLISHABLE_FIELDS,
    STRATEGY_CATALOG,
    CandidateConstraints,
    EvidenceStatus,
    RankingCriterion,
    Strategy,
    StrategyConfigurationError,
    strategy,
)
from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN
from squadopt.bayesopt import BayesianFactor


def _factor(name: str) -> BayesianFactor:
    return BayesianFactor(name=name, lower_bound=0, upper_bound=2, step=1, kind="integer")


# --- the envelope -------------------------------------------------------------------


def test_every_registered_strategy_publishes_inside_the_envelope() -> None:
    for entry in STRATEGY_CATALOG.values():
        assert entry.publishes <= PUBLISHABLE_FIELDS


def test_the_envelope_itself_carries_no_probability_shaped_field() -> None:
    """The meta-gate: PUBLISHABLE_FIELDS cannot quietly widen toward a probability."""

    for field_name in PUBLISHABLE_FIELDS:
        assert not FORBIDDEN_FIELD_PATTERN.search(field_name), field_name


def test_a_field_outside_the_envelope_is_refused_at_construction() -> None:
    with pytest.raises(StrategyConfigurationError, match="unpublishable"):
        Strategy(
            slug="kacak",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=frozenset({"probability_ahead"}),
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
        )


def test_no_ranking_criterion_reads_a_probability() -> None:
    for criterion in RankingCriterion:
        assert not re.search(r"probab|olas.l.k", str(criterion), re.IGNORECASE)


# --- naming and evidence ------------------------------------------------------------


def test_an_ungated_strategy_may_not_use_safety_language() -> None:
    with pytest.raises(StrategyConfigurationError, match="safety language"):
        Strategy(
            slug="sozde-guvenli",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=frozenset({"moves"}),
            evidence=EvidenceStatus.PREREG_OPEN,
            tagline="Daha güvenli bir plan.",
        )


def test_nothing_in_the_catalogue_claims_a_gated_pass_yet() -> None:
    """The bench has not run; a gated_pass in the initial catalogue would be a lie."""

    for entry in STRATEGY_CATALOG.values():
        assert entry.evidence is not EvidenceStatus.GATED_PASS


# --- rival consistency --------------------------------------------------------------


def test_rival_relative_strategies_declare_their_rival() -> None:
    for entry in STRATEGY_CATALOG.values():
        if (
            entry.constraints.is_rival_relative
            or entry.ranks_by is RankingCriterion.EXPECTED_GAP_VS_RIVAL
        ):
            assert entry.rival_required, entry.slug


def test_an_undeclared_rival_dependency_is_refused() -> None:
    with pytest.raises(StrategyConfigurationError, match="rival_required"):
        Strategy(
            slug="gizli-rakip",
            constraints=CandidateConstraints(overlap_floor=8),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=frozenset({"moves"}),
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
        )


# --- knobs are the declared search space --------------------------------------------


def test_knob_keys_match_their_factor_names_and_feed_the_search() -> None:
    for entry in STRATEGY_CATALOG.values():
        for name, factor in entry.knobs.items():
            assert factor.name == name
        assert entry.search_factors() == tuple(entry.knobs[name] for name in sorted(entry.knobs))


def test_a_mismatched_knob_key_is_refused() -> None:
    with pytest.raises(StrategyConfigurationError, match="must equal"):
        Strategy(
            slug="kayik-knob",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=frozenset({"moves"}),
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={"beklenen": _factor("baska")},
        )


# --- constraints --------------------------------------------------------------------


def test_constraint_bounds_are_validated() -> None:
    with pytest.raises(StrategyConfigurationError, match=r"0\.\.11"):
        CandidateConstraints(overlap_floor=12)
    with pytest.raises(StrategyConfigurationError, match="may not exceed"):
        CandidateConstraints(overlap_floor=8, overlap_ceiling=4)
    with pytest.raises(StrategyConfigurationError, match="Unknown chip"):
        CandidateConstraints(forced_chip="joker")
    with pytest.raises(StrategyConfigurationError, match="non-negative"):
        CandidateConstraints(transfer_cap=-1)


# --- the catalogue ------------------------------------------------------------------


def test_the_catalogue_holds_the_declared_nine_and_the_control_is_unconstrained() -> None:
    assert sorted(STRATEGY_CATALOG) == [
        "cip-yerlesimi",
        "fark-yarat",
        "fiyat-yakala",
        "kaptan-ayris",
        "ortak-koru",
        "sablon-uzakligi",
        "saf-puan",
        "takvim-onceligi",
        "transfer-disiplini",
    ]
    control = strategy("saf-puan")
    assert control.constraints == CandidateConstraints()
    assert control.ranks_by is RankingCriterion.EXPECTED_OWN_POINTS
    assert not control.rival_required


def test_slugs_are_ascii_paths() -> None:
    """Advice files are addressed by slug; the path convention is ASCII kebab."""

    for slug in STRATEGY_CATALOG:
        assert re.fullmatch(r"[a-z0-9-]+", slug), slug


def test_an_unknown_slug_is_refused_loudly() -> None:
    with pytest.raises(StrategyConfigurationError, match="Unknown strategy"):
        strategy("yok-boyle-taktik")


def test_the_catalogue_is_immutable() -> None:
    with pytest.raises(TypeError):
        STRATEGY_CATALOG["yeni"] = strategy("saf-puan")  # type: ignore[index]
