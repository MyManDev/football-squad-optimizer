"""Explicit exhaustive role search within one already selected FPL fifteen.

This module has no live caller. It reuses the published independent-appearance
scorer and does not change the bounded search or any transfer-planning default.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations, permutations

import pandas as pd

from squadopt.contracts import identifier_sort_key
from squadopt.scenarios.expected_lineup import (
    ExpectedLineupScore,
    _autosub_multipliers,
    _Decision,
    _Inputs,
    _prepare,
    _score,
)

EXACT_FOOTBALL_LINEUP_VERSION = "exact_fixed_fifteen_roles_v1"
_POSITIONS = ("DEF", "MID", "FWD")
_MINIMUM = (3, 2, 1)
_MAXIMUM = (5, 5, 3)


@dataclass(frozen=True, slots=True)
class ExactFootballLineupResult:
    """A complete enumeration certificate for fixed-squad roles only."""

    incumbent: ExpectedLineupScore
    best: ExpectedLineupScore
    legal_xis: int
    reserve_orders_evaluated: int
    role_scores_evaluated: int
    score_records_built: int
    captain_pairs_covered: int
    captain_pair_terms_computed: int
    captain_pair_scores_evaluated: int
    captain_pair_membership_checks: int
    states_evaluated: int
    autosub_cache_hits: int
    outfield_autosub_cache_hits: int
    locked_first: bool
    proof_scope: str
    search_version: str = EXACT_FOOTBALL_LINEUP_VERSION


def _canonical(data: _Inputs, decision: _Decision) -> _Decision:
    goalkeeper = next(p for p in decision.bench if data.position[p] == "GK")
    return _Decision(
        tuple(sorted(decision.starters, key=identifier_sort_key)),
        (goalkeeper, *(p for p in decision.bench if p != goalkeeper)),
        decision.captain,
        decision.vice,
    )


@dataclass(slots=True)
class _ScoringCache:
    outfield: dict[tuple[tuple[object, ...], tuple[object, ...]], tuple[dict[object, float], int]]
    hits: int = 0

    def multipliers(self, data: _Inputs, decision: _Decision) -> dict[object, float]:
        canonical = _canonical(data, decision)
        key = (
            tuple(p for p in canonical.starters if data.position[p] != "GK"),
            canonical.bench[1:],
        )
        if key not in self.outfield:
            # Reuse the published convolution in canonical player order. The
            # two goalkeeper choices have exactly the same outfield admissions.
            self.outfield[key] = _autosub_multipliers(data, canonical)
        else:
            self.hits += 1
        cached, states = self.outfield[key]
        multipliers = dict(cached)
        for player in data.ids:
            if data.position[player] == "GK":
                multipliers[player] = 0.0
        keeper = next(p for p in canonical.starters if data.position[p] == "GK")
        backup = canonical.bench[0]
        if data.chip != "bboost" and data.chance[backup] > 0:
            multipliers[backup] = 1 - data.chance[keeper]
        data.autosub_cache[(decision.starters, decision.bench)] = (multipliers, states)
        return multipliers

    def score(self, data: _Inputs, decision: _Decision) -> ExpectedLineupScore:
        self.multipliers(data, decision)
        return _score(data, decision)


def _best_pair(
    data: _Inputs,
    base_terms: list[float],
    indices: dict[object, int],
    pairs: list[tuple[object, object]],
    pair_terms: dict[tuple[object, object], tuple[float, float]],
) -> tuple[object, object, float]:
    """Compare full canonical fsum scores, preserving the published operations.

    Ranking a separately rounded two-term captain bonus can hide a genuine
    difference when other signed terms cancel. Replace the two starter terms in
    the complete fifteen-term list instead of adding a rounded partial bonus.
    """
    terms = list(base_terms)
    best_pair = pairs[0]
    best_net = -math.inf
    for captain, vice in pairs:
        c_index, v_index = indices[captain], indices[vice]
        terms[c_index], terms[v_index] = pair_terms[(captain, vice)]
        try:
            net = math.fsum(terms) - data.hits
        except (OverflowError, ValueError) as exc:
            raise ValueError("Expected lineup scores exceed the finite numeric range.") from exc
        if not math.isfinite(net):
            raise ValueError("Expected lineup scores exceed the finite numeric range.")
        if net > best_net:
            best_pair, best_net = (captain, vice), net
        terms[c_index], terms[v_index] = base_terms[c_index], base_terms[v_index]
    return (*best_pair, best_net)


def _lineups(data: _Inputs) -> Iterator[tuple[object, ...]]:
    keepers = tuple(p for p in data.ids if data.position[p] == "GK" and p not in data.not_starting)
    outfield = tuple(p for p in data.ids if data.position[p] != "GK" and p not in data.not_starting)
    for selected in combinations(outfield, 10):
        counts = tuple(sum(data.position[p] == pos for p in selected) for pos in _POSITIONS)
        if not all(
            low <= count <= high
            for low, count, high in zip(_MINIMUM, counts, _MAXIMUM, strict=True)
        ):
            continue
        for keeper in keepers:
            yield tuple(sorted((keeper, *selected), key=identifier_sort_key))


def optimize_football_lineup_exact(
    squad: pd.DataFrame,
    starting_xi: Sequence[object],
    ordered_bench: Sequence[object],
    captain_id: object,
    vice_captain_id: object,
    *,
    chip: str | None = None,
    hit_points: float = 0.0,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
    locked_first: bool = False,
) -> ExactFootballLineupResult:
    """Exhaust every permitted XI/reserve action on the supplied fifteen.

    Captain and vice both start. Every eligible pair is compared on the complete
    published floating-point score with cached autosubs and no random draws.
    Unconditional points already contain appearance; no second eligibility or
    strength multiplier is introduced. The original complete action wins exact
    point and XI-appearance ties. A locked first action is returned unchanged.
    The input incumbent must satisfy all restrictions, as in the existing scorer.
    This is neither a transfer/squad optimizer nor a correlated-absence model.
    """
    if not isinstance(locked_first, bool):
        raise ValueError("locked_first must be boolean.")
    decision = _Decision(tuple(starting_xi), tuple(ordered_bench), captain_id, vice_captain_id)
    data = _prepare(squad, decision, chip, hit_points, not_starting, not_captain)
    unknown = (data.not_starting | data.not_captain) - set(data.ids)
    if unknown:
        raise ValueError("Role restrictions must identify players in the selected fifteen.")
    scoring = _ScoringCache({})
    incumbent = best = scoring.score(data, decision)
    if locked_first:
        return ExactFootballLineupResult(
            incumbent=incumbent,
            best=best,
            legal_xis=1,
            reserve_orders_evaluated=1,
            role_scores_evaluated=1,
            score_records_built=1,
            captain_pairs_covered=0,
            captain_pair_terms_computed=0,
            captain_pair_scores_evaluated=0,
            captain_pair_membership_checks=0,
            states_evaluated=data.states_evaluated,
            autosub_cache_hits=data.autosub_cache_hits,
            outfield_autosub_cache_hits=scoring.hits,
            locked_first=True,
            proof_scope="locked_complete_action_only",
        )

    eligible = tuple(p for p in data.ids if p not in data.not_captain)
    pairs = [(c, v) for c in eligible for v in eligible if c != v]
    bonus = 2 if data.chip == "3xc" else 1
    pair_terms = {
        (c, v): (
            (1.0 + bonus) * data.points[c],
            (1.0 + bonus * (1 - data.chance[c])) * data.points[v],
        )
        for c, v in pairs
    }
    indices = {p: index for index, p in enumerate(data.ids)}
    best_key = (
        best.expected_net_points,
        math.fsum(data.chance[p] for p in best.starting_xi),
    )
    xis = orders = pair_coverage = membership_checks = 0
    pair_scores = 0
    records = 1
    for starters in _lineups(data):
        selected = set(starters)
        permitted_pairs = [(c, v) for c, v in pairs if c in selected and v in selected]
        membership_checks += len(pairs)
        if not permitted_pairs:
            continue
        xis += 1
        pair_coverage += len(permitted_pairs)
        remaining = tuple(p for p in data.ids if p not in selected)
        keeper = next(p for p in remaining if data.position[p] == "GK")
        reserves = tuple(p for p in remaining if data.position[p] != "GK")
        availability = math.fsum(data.chance[p] for p in starters)
        for ordering in permutations(reserves):
            orders += 1
            captain, vice = permitted_pairs[0]
            candidate = _Decision(starters, (keeper, *ordering), captain, vice)
            multipliers = dict(scoring.multipliers(data, candidate))
            for p in data.ids if data.chip == "bboost" else starters:
                multipliers[p] += 1.0
            base_terms = [multipliers[p] * data.points[p] for p in data.ids]
            captain, vice, net = _best_pair(data, base_terms, indices, permitted_pairs, pair_terms)
            pair_scores += len(permitted_pairs)
            key = (net, availability)
            if key > best_key:
                best = scoring.score(data, _Decision(starters, candidate.bench, captain, vice))
                records += 1
                if best.expected_net_points != net:
                    raise ValueError("Captain pair arithmetic differs from the published scorer.")
                best_key = key
    return ExactFootballLineupResult(
        incumbent=incumbent,
        best=best,
        legal_xis=xis,
        reserve_orders_evaluated=orders,
        role_scores_evaluated=pair_scores + records,
        score_records_built=records,
        captain_pairs_covered=pair_coverage,
        captain_pair_terms_computed=len(pair_terms),
        captain_pair_scores_evaluated=pair_scores,
        captain_pair_membership_checks=membership_checks,
        states_evaluated=data.states_evaluated,
        autosub_cache_hits=data.autosub_cache_hits,
        outfield_autosub_cache_hits=scoring.hits,
        locked_first=False,
        proof_scope="all_legal_fixed_fifteen_roles_under_independent_appearance",
    )
