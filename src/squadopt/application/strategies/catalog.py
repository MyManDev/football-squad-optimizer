"""The strategy catalogue: declared structural constraints, priced in expected points.

One framing unifies every play mode this system will offer: **maximise expected points
under a declared structural constraint; the constraint's cost is the price tag.** The
user's own recipe — hold the shared high scorers, replace the shared low scorers — is
what "maximise expected points subject to overlap >= g" produces by itself; reversing
the inequality produces the differential game. A tactic is therefore a registration,
not a rewrite: a slug, a constraint, a ranking criterion from a closed list, the fields
it may publish, its evidence status, and the knobs a search may move.

Honesty is structural here, not editorial:

- ``RankingCriterion`` is a closed enum of expected-points readings. A criterion that
  reads a probability cannot be registered because it cannot be written down — the
  rival-relative window probabilities fell three pre-registered calibrations and the
  line's stop-rule binds (``measurements_index.md:87-89``).
- ``publishes`` must be a subset of ``PUBLISHABLE_FIELDS``, checked at construction.
  The envelope carries expected points, expected gap, overlap, the price tag with the
  ceiling that bounds it when a proof is missing, and the solver's own account; it
  carries no probability and no spread of the gap — shared players cancel in the gap's
  *mean*, not in its spread, so the spread was never honestly publishable from this
  machinery. A solver bound is not a spread: it is a deterministic statement about a
  search that stopped, and it is published as one end, never as an interval.
- A strategy whose ``evidence`` is not ``GATED_PASS`` cannot carry safety language in
  its tagline: until the pre-registered bench (``docs/strategy_bench_prereg.md``)
  passes for its bands, a name may describe the constraint, never the outcome.
- ``knobs`` *is* the search-space declaration. A design or a Bayesian search reads
  ``search_factors()`` directly; there is no separate search configuration, so "what
  was searched" and "what was declared" cannot drift apart. This is the gap that let
  ``asiri_agresif``'s ``margin: 5.0`` ship hand-picked and never searched.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from squadopt.contracts import BayesianFactor, FactorKind
from squadopt.planning.models import CHIP_NAMES


class StrategyConfigurationError(ValueError):
    """Raised when a strategy declaration violates the catalogue's contract."""


#: Everything a strategy may publish. The honesty envelope, closed: expected points,
#: expected gap, set arithmetic, the price tag and its ceiling, the solver's own account,
#: and the decision itself — captain, vice-captain, eleven, bench order, chip. No
#: probability, no quantile, no spread — the stop-rule that closed those lines is a
#: measurement, and this list is where it is enforced structurally.
PUBLISHABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "moves",
        # The week's hit charge, once. It belongs to the week — the game takes four
        # points for each transfer beyond the free ones — not to any one move, so it is
        # published beside ``moves`` and no move row carries it.
        "transfer_hit_points",
        "expected_own_points",
        "expected_gap_vs_rival",
        "expected_points_cost",
        # The most that price can be, from the solver's own bound on the control it is
        # measured against. A deterministic ceiling on a difference of two solved plans
        # — not a spread, not an interval around an estimate: under a proof it *is* the
        # price, and without one it is the only end of the range that can be stated
        # without reading as a confidence claim.
        "expected_points_cost_ceiling",
        "overlap_count",
        "captain_agreement",
        "difference_makers",
        "solver_status",
        "optimality_gap",
        "captain",
        "vice_captain",
        "starting_xi",
        "bench",
        "chip",
        "control_solver_status",
        "control_optimality_gap",
        "transfer_cap",
        "overlap_target",
        "overlap_applied",
        "plan_kind",
        "alternative_plan",
        # The multi-week window: one row per gameweek (transfers, hit points, chip,
        # expected points) and the sentences naming what the window assumes.
        "plan_weeks",
        "stated_limits",
        # The declared rule's pick for the week, with the gap and the weeks remaining it
        # read (``strategies/rule.py``). A band on points, stamped with the rule's id and
        # version — never a chance of catching up, which is why it fits in here at all.
        "suggested_strategy",
        # Which squad the advice stands on: ``captured``, or ``pre_free_hit_gwNN`` when
        # a Free Hit voided the captured week's fifteen. A label, never a number.
        "squad_basis",
    }
)

#: Words a strategy without a gated pass may not use about itself, in either language.
_SAFETY_LANGUAGE: Final = re.compile(r"g[üu]venli|riskli?|safe|daha az riskli", re.IGNORECASE)

#: Field names that could smuggle a probability into the envelope; a meta-test keeps
#: PUBLISHABLE_FIELDS clean against this, so the envelope cannot quietly widen. The
#: last alternative is the ``p_`` naming convention for a probability, and it needs
#: the word boundary: bare ``p_`` would also match ``overlap_count`` and the rest of
#: the overlap fields, which are set arithmetic and publishable.
FORBIDDEN_FIELD_PATTERN: Final = re.compile(r"probab|olas.l.k|quantile|spread|\bp_")

#: The same rule applied to *text* rather than to field names, in both languages the
#: site publishes. Its subject is the text **this repository generates**: strategy names,
#: notes, badges, rule copy, every string in the published tree that a member did not
#: type. ``tests/unit/test_public_probability_guards.py`` sweeps the built tree with it.
#:
#: It is deliberately **not** applied to a member's own team name, manager name or
#: registry label. Those are the member's words, chosen inside the game and public there
#: once the deadline passes; they are not a claim this site makes, so the honesty envelope
#: does not reach them and the producer publishes them as captured
#: (``application/league_views.py``). The producer still normalises a name's *shape* —
#: control characters, markup delimiters, length — because that is a safety question and
#: not a question of wording.
#:
#: This is the web guard's ``AS_A_CHANCE`` set (``MemberDecisionControls.test.tsx``)
#: with the repository's own ``P(`` and ``quantile`` beside it: one rule written twice.
#:
#: Some alternatives carry word boundaries — ``chances?``, ``likelihood``, ``odds``,
#: ``\u015fans`` and ``y\u00fczde`` — while ``ihtimal`` and ``olas\u0131l`` stay stems.
#: The boundaries were added while this pattern still read member-typed names, so that
#: ``\u015eansl\u0131`` ("lucky"), the surname ``\u015eansal`` and ``Bu Y\u00fczden``
#: ("for that reason") were not published as ``entry-<id>`` in place of the name a member
#: chose. That reason is gone now that names are out of scope. The boundaries are left
#: exactly as they are rather than re-tuned in the same change: widening them would move
#: the guard on our own copy, and this change moves nothing there. Our own wording does
#: not rely on them either way — the web tests hold it with an unbounded set.
#:
#: The dotless i and the soft g are escaped wherever they appear, here and in the pattern,
#: because they are easy to misread as ``i`` and ``g``.
#:
#: The pattern is compiled from ``str``, so ``\b`` is the Unicode boundary and counts
#: ``\u0131``, ``\u015f``, ``\u011f`` and ``\u00fc`` as word characters — measured,
#: not assumed: under ``re.ASCII`` it would fall *inside* these words, and bare
#: ``\u015fans`` would pass.
FORBIDDEN_TEXT_PATTERN: Final = re.compile(
    r"%|\bP\(|probabilit|quantile|\bchances?\b|\blikelihood\b|\bodds\b"
    "|\\bihtimal|\\b\u015fans\\b|\\by\u00fczde\\b|olas\u0131l",
    re.IGNORECASE,
)


class RankingCriterion(StrEnum):
    """The closed list of things a strategy may rank its candidates by.

    All three are expected-points readings. With the rival held fixed,
    ``EXPECTED_GAP_VS_RIVAL`` ranks identically to ``EXPECTED_OWN_POINTS`` — declaring
    it still matters, because it is the number the member is shown and it requires a
    rival to exist. There is deliberately no probability criterion: a number that may
    not be published may not pick the plan either.
    """

    EXPECTED_OWN_POINTS = "expected_own_points"
    EXPECTED_GAP_VS_RIVAL = "expected_gap_vs_rival"
    EXPECTED_POINTS_MINUS_HITS = "expected_points_minus_hits"


class EvidenceStatus(StrEnum):
    """Where a strategy stands against the pre-registered bench.

    ``GATED_PASS`` means the bench's gates passed for this strategy's bands and its
    name may carry direction. ``PREREG_OPEN`` means a pre-registration exists and the
    measurement has not run (or has not passed). ``DIAGNOSTIC_ONLY`` means not even a
    pre-registration covers it yet: it may render with its constraint and price only.
    """

    GATED_PASS = "gated_pass"
    PREREG_OPEN = "prereg_open"
    DIAGNOSTIC_ONLY = "diagnostic_only"


@dataclass(frozen=True, slots=True)
class CandidateConstraints:
    """The structural constraint a strategy declares, in solver-enforceable terms.

    Every field maps onto a lever the planner already has or the banded candidate
    generation adds: ``required_player_ids`` and forced chips exist today
    (``optimization/optimizer.py``, ``ChipAvailability.forced``), the overlap bounds
    become no-good-style cuts against the rival's known eleven, and the transfer cap
    bounds the week's moves. ``None`` means unconstrained — the control.
    """

    overlap_floor: int | None = None
    """Keep at least this many of the rival's known eleven in the fifteen (0-11)."""
    overlap_ceiling: int | None = None
    """Keep at most this many of the rival's known eleven in the fifteen (0-11)."""
    captain_must_differ: bool = False
    """The captain may not be the rival's captain."""
    required_player_ids: frozenset[int] = frozenset()
    """Players the squad must hold, by code."""
    forced_chip: str | None = None
    """Force this chip to be played inside the window."""
    transfer_cap: int | None = None
    """At most this many transfers in the decided week."""
    template_distance_floor: int | None = None
    """Differ from the ownership template's eleven by at least this many players."""

    def __post_init__(self) -> None:
        for name in ("overlap_floor", "overlap_ceiling"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 11
            ):
                raise StrategyConfigurationError(f"{name} must be None or an integer in 0..11.")
        if (
            self.overlap_floor is not None
            and self.overlap_ceiling is not None
            and self.overlap_floor > self.overlap_ceiling
        ):
            raise StrategyConfigurationError("overlap_floor may not exceed overlap_ceiling.")
        if self.forced_chip is not None and self.forced_chip not in CHIP_NAMES:
            raise StrategyConfigurationError(f"Unknown chip {self.forced_chip!r}.")
        for name in ("transfer_cap", "template_distance_floor"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise StrategyConfigurationError(f"{name} must be None or a non-negative integer.")
        object.__setattr__(
            self, "required_player_ids", frozenset(int(p) for p in self.required_player_ids)
        )

    @property
    def is_rival_relative(self) -> bool:
        """True when the constraint cannot even be stated without a rival."""

        return (
            self.overlap_floor is not None
            or self.overlap_ceiling is not None
            or self.captain_must_differ
        )


@dataclass(frozen=True, slots=True)
class Strategy:
    """One registered tactic: a declared constraint, priced in expected points."""

    slug: str
    constraints: CandidateConstraints
    ranks_by: RankingCriterion
    publishes: frozenset[str]
    evidence: EvidenceStatus
    knobs: Mapping[str, BayesianFactor] = field(default_factory=dict)
    rival_required: bool = False
    tagline: str = ""
    """One sentence describing the constraint — never the outcome, unless gated."""

    def __post_init__(self) -> None:
        if not isinstance(self.slug, str) or not re.fullmatch(r"[a-z0-9-]+", self.slug):
            raise StrategyConfigurationError(
                "slug must be a lowercase ASCII kebab identifier (the site's path convention)."
            )
        if not isinstance(self.constraints, CandidateConstraints):
            raise StrategyConfigurationError("constraints must be CandidateConstraints.")
        if not isinstance(self.ranks_by, RankingCriterion):
            raise StrategyConfigurationError("ranks_by must be a RankingCriterion.")
        if not isinstance(self.evidence, EvidenceStatus):
            raise StrategyConfigurationError("evidence must be an EvidenceStatus.")
        stray = frozenset(self.publishes) - PUBLISHABLE_FIELDS
        if stray:
            raise StrategyConfigurationError(
                f"{self.slug!r} declares unpublishable fields {sorted(stray)}; the envelope "
                "is closed and this list is where it is enforced."
            )
        object.__setattr__(self, "publishes", frozenset(self.publishes))
        knobs = dict(self.knobs)
        for name, factor in knobs.items():
            if not isinstance(factor, BayesianFactor):
                raise StrategyConfigurationError(f"Knob {name!r} must be a BayesianFactor.")
            if factor.name != name:
                raise StrategyConfigurationError(
                    f"Knob key {name!r} must equal its factor's name {factor.name!r}."
                )
        object.__setattr__(self, "knobs", MappingProxyType(knobs))
        needs_rival = (
            self.constraints.is_rival_relative
            or self.ranks_by is RankingCriterion.EXPECTED_GAP_VS_RIVAL
        )
        if needs_rival and not self.rival_required:
            raise StrategyConfigurationError(
                f"{self.slug!r} is rival-relative but does not declare rival_required."
            )
        if self.evidence is not EvidenceStatus.GATED_PASS and _SAFETY_LANGUAGE.search(self.tagline):
            raise StrategyConfigurationError(
                f"{self.slug!r} has evidence {self.evidence} and may not describe itself "
                "with safety language; the bench decides that, not the copy."
            )

    def search_factors(self) -> tuple[BayesianFactor, ...]:
        """The declared knob space, in name order — what DoE and BO read directly."""

        return tuple(self.knobs[name] for name in sorted(self.knobs))


def _integer_knob(name: str, lower: int, upper: int, step: int = 1) -> BayesianFactor:
    return BayesianFactor(
        name=name, lower_bound=lower, upper_bound=upper, step=step, kind=FactorKind.INTEGER
    )


def _continuous_knob(name: str, lower: float, upper: float, step: float) -> BayesianFactor:
    return BayesianFactor(name=name, lower_bound=lower, upper_bound=upper, step=step)


_BASELINE_PUBLISHES: Final = frozenset(
    {
        "moves",
        "transfer_hit_points",
        "expected_own_points",
        "expected_points_cost",
        "solver_status",
        "optimality_gap",
        "captain",
        "vice_captain",
        "starting_xi",
        "bench",
        "chip",
    }
)
_RIVAL_PUBLISHES: Final = _BASELINE_PUBLISHES | frozenset(
    {
        "expected_gap_vs_rival",
        # A rival plan is priced against a control this member's own solve produced, so
        # it is the one path that knows how far that control's proof got.
        "expected_points_cost_ceiling",
        "overlap_count",
        "captain_agreement",
        "difference_makers",
        "control_solver_status",
        "control_optimality_gap",
        "transfer_cap",
        "overlap_target",
        "overlap_applied",
        "plan_kind",
        "alternative_plan",
    }
)


def _catalog() -> Mapping[str, Strategy]:
    strategies = (
        Strategy(
            slug="saf-puan",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            # The only strategy computed beyond one week: its three- and five-week
            # windows publish the per-week plan and the window's stated limits.
            publishes=_BASELINE_PUBLISHES | frozenset({"plan_weeks", "stated_limits"}),
            evidence=EvidenceStatus.PREREG_OPEN,
            # Not "the highest expected points". The solve maximises the eleven, the
            # captain and the bench together (``planning/optimizer.py``: ``projected_score
            # + bench_weight * projected_bench - hits``, bench_weight 0.1), while
            # ``expected_own_points`` — the number this publishes and the member reads —
            # is the eleven and the captain only. The two have different maximisers, and
            # on the 2026-27 GW4 capture they disagree: entry 3832237's plan scores 46.5454
            # on the published figure with a 7.1846 bench, and its ortak-koru plan scores
            # 46.7016 with a 4.3379 bench — the banded plan reads higher on the figure and
            # lower on the objective. Nothing enforces a maximum over the published figure,
            # so nothing may claim one.
            tagline="Unconstrained: chosen on the eleven, the captain and the bench together.",
        ),
        Strategy(
            slug="ortak-koru",
            constraints=CandidateConstraints(overlap_floor=9),
            ranks_by=RankingCriterion.EXPECTED_GAP_VS_RIVAL,
            publishes=_RIVAL_PUBLISHES,
            evidence=EvidenceStatus.PREREG_OPEN,
            knobs={"overlap_floor": _integer_knob("overlap_floor", 6, 11)},
            rival_required=True,
            tagline="Hold the shared core with the rival within the free transfers; spend the "
            "rest on expected points.",
        ),
        Strategy(
            slug="fark-yarat",
            constraints=CandidateConstraints(overlap_ceiling=5),
            ranks_by=RankingCriterion.EXPECTED_GAP_VS_RIVAL,
            publishes=_RIVAL_PUBLISHES,
            evidence=EvidenceStatus.PREREG_OPEN,
            knobs={"overlap_ceiling": _integer_knob("overlap_ceiling", 3, 8)},
            rival_required=True,
            tagline="Cap the overlap with the rival within the free transfers; unshared players "
            "decide the gap.",
        ),
        Strategy(
            slug="kaptan-ayris",
            constraints=CandidateConstraints(captain_must_differ=True),
            ranks_by=RankingCriterion.EXPECTED_GAP_VS_RIVAL,
            publishes=_RIVAL_PUBLISHES,
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            rival_required=True,
            tagline="Captain differs from the rival's; the cheapest differential.",
        ),
        Strategy(
            slug="sablon-uzakligi",
            constraints=CandidateConstraints(template_distance_floor=3),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=_BASELINE_PUBLISHES | frozenset({"difference_makers"}),
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={"template_distance_floor": _integer_knob("template_distance_floor", 2, 6)},
            tagline="Stay a declared distance from the ownership template.",
        ),
        Strategy(
            slug="takvim-onceligi",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=_BASELINE_PUBLISHES,
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={"calendar_weight": _continuous_knob("calendar_weight", 0.0, 1.0, 0.25)},
            tagline="Prefer double gameweeks, avoid blanks.",
        ),
        Strategy(
            slug="cip-yerlesimi",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=_BASELINE_PUBLISHES,
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={
                "wildcard_holding": _continuous_knob("wildcard_holding", 10.0, 30.0, 5.0),
                "freehit_holding": _continuous_knob("freehit_holding", 5.0, 25.0, 5.0),
            },
            tagline="Force a chip inside the window; holding values are declared.",
        ),
        Strategy(
            slug="transfer-disiplini",
            constraints=CandidateConstraints(transfer_cap=1),
            ranks_by=RankingCriterion.EXPECTED_POINTS_MINUS_HITS,
            publishes=_BASELINE_PUBLISHES,
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={"transfer_cap": _integer_knob("transfer_cap", 0, 3)},
            tagline="A hit cap; a banked transfer keeps its declared value.",
        ),
        Strategy(
            slug="fiyat-yakala",
            constraints=CandidateConstraints(),
            ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
            publishes=_BASELINE_PUBLISHES,
            evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            knobs={"rise_threshold": _continuous_knob("rise_threshold", 0.1, 0.5, 0.1)},
            tagline="Catch the riser early; movers are measured as under-projected.",
        ),
    )
    by_slug = {strategy.slug: strategy for strategy in strategies}
    if len(by_slug) != len(strategies):
        raise StrategyConfigurationError("Duplicate strategy slugs in the catalogue.")
    return MappingProxyType(by_slug)


#: The registered catalogue, immutable. A new tactic is one ``Strategy`` here, one
#: pre-registration row, and one bench run — the core does not change.
STRATEGY_CATALOG: Final[Mapping[str, Strategy]] = _catalog()


def strategy(slug: str) -> Strategy:
    """Return the registered strategy for ``slug``, or refuse loudly."""

    try:
        return STRATEGY_CATALOG[slug]
    except KeyError as error:
        raise StrategyConfigurationError(
            f"Unknown strategy {slug!r}; registered: {sorted(STRATEGY_CATALOG)}."
        ) from error
