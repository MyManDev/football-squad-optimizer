"""Exact independent-appearance lineup expectation and bounded fixed-squad search.

Weekly points are unconditional: appearance has already been applied upstream.
This is a transparent Bernoulli approximation, not a calibrated joint team model.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import permutations, product
from numbers import Integral, Real
from types import MappingProxyType

import pandas as pd

from squadopt.contracts import identifier_sort_key
from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import _validate_frozen_decision

EXPECTED_LINEUP_VERSION = "independent_appearance_lineup_v1"
ASSUMPTIONS = (
    "independent_player_week_appearances",
    "conditional_player_points_unaffected_by_other_appearances",
    "unconditional_weekly_points_already_include_appearance",
    "any_positive_gameweek_minutes_including_cameos_block_autosubs",
    "no_card_only_participation_outside_the_appearance_model",
    "double_gameweek_appearance_probability_is_supplied_by_the_caller",
)
_OUTFIELD = ("DEF", "MID", "FWD")
_MINIMUM = (3, 2, 1)
_MAXIMUM = (5, 5, 3)


@dataclass(frozen=True, slots=True)
class ExpectedLineupScore:
    starting_xi: tuple[object, ...]
    ordered_bench: tuple[object, ...]
    captain_id: object
    vice_captain_id: object
    chip: str | None
    hit_points: float
    expected_net_points: float
    starting_points: float
    autosub_points: float
    captain_bonus_points: float
    vice_bonus_points: float
    bench_boost_points: float
    scoring_multipliers: Mapping[object, float]
    fingerprint: str
    states_evaluated: int
    assumptions: tuple[str, ...] = ASSUMPTIONS
    contract_version: str = EXPECTED_LINEUP_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scoring_multipliers", MappingProxyType(dict(self.scoring_multipliers))
        )


@dataclass(frozen=True, slots=True)
class ExpectedLineupSearchResult:
    incumbent: ExpectedLineupScore
    best: ExpectedLineupScore
    evaluations: int
    max_evaluations: int
    cache_hits: int
    budget_exhausted: bool
    locked_first: bool
    states_evaluated: int
    autosub_cache_hits: int
    captain_pairs_considered: int
    proof_scope: str = "bounded_fixed_squad_neighborhood_only"


@dataclass(frozen=True, slots=True)
class _Decision:
    starters: tuple[object, ...]
    bench: tuple[object, ...]
    captain: object
    vice: object


@dataclass(slots=True)
class _Inputs:
    ids: tuple[object, ...]
    position: dict[object, str]
    points: dict[object, float]
    chance: dict[object, float]
    chip: str | None
    hits: float
    not_starting: frozenset[object]
    not_captain: frozenset[object]
    # Captain changes reuse exactly the same autosub expectation.
    autosub_cache: dict[
        tuple[tuple[object, ...], tuple[object, ...]], tuple[dict[object, float], int]
    ] = field(default_factory=dict)
    states_evaluated: int = 0
    autosub_cache_hits: int = 0
    captain_pairs_considered: int = 0


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number.")
    return float(value)


def _prepare(
    squad: pd.DataFrame,
    decision: _Decision,
    chip: str | None,
    hit_points: float,
    not_starting: Iterable[object],
    not_captain: Iterable[object],
) -> _Inputs:
    frame = _validate_frozen_decision(
        FrozenSquadDecision(
            squad,
            decision.starters,
            decision.bench,
            decision.captain,
            decision.vice,
        )
    )
    if decision.vice not in decision.starters:
        raise ValueError("The vice-captain must be in the starting XI.")
    if chip not in (None, "3xc", "bboost", "wildcard", "freehit"):
        raise ValueError("Unknown lineup chip.")
    hits = _number(hit_points, "hit_points")
    if hits < 0:
        raise ValueError("hit_points must be non-negative.")
    missing = {"expected_points", "appearance_probability"} - set(frame)
    if missing:
        raise ValueError(f"Lineup forecasts are missing columns: {sorted(missing)}.")
    points, chance, positions = {}, {}, {}
    for player, position, expected, probability in frame[
        [
            "player_id",
            "position",
            "expected_points",
            "appearance_probability",
        ]
    ].itertuples(index=False, name=None):
        mu = _number(expected, "expected_points")
        q = _number(probability, "appearance_probability")
        if not 0 <= q <= 1:
            raise ValueError("appearance_probability must lie in [0, 1].")
        if q == 0 and mu != 0:
            raise ValueError("A zero appearance probability requires zero expected points.")
        points[player], chance[player], positions[player] = mu, q, str(position)
    blocked_start, blocked_captain = frozenset(not_starting), frozenset(not_captain)
    if set(decision.starters) & blocked_start:
        raise ValueError("The incumbent XI violates not_starting.")
    if {decision.captain, decision.vice} & (blocked_captain | blocked_start):
        raise ValueError("The incumbent captain or vice violates not_captain.")
    return _Inputs(
        tuple(sorted(points, key=identifier_sort_key)),
        positions,
        points,
        chance,
        chip,
        hits,
        blocked_start,
        blocked_captain | blocked_start,
    )


def _autosub_multipliers(data: _Inputs, decision: _Decision) -> tuple[dict[object, float], int]:
    key = (decision.starters, decision.bench)
    if key in data.autosub_cache:
        data.autosub_cache_hits += 1
        return data.autosub_cache[key]
    multipliers = dict.fromkeys(data.ids, 0.0)
    if data.chip == "bboost":
        return multipliers, 0
    keeper = next(p for p in decision.starters if data.position[p] == "GK")
    backup = next(p for p in decision.bench if data.position[p] == "GK")
    if data.chance[backup] > 0:
        multipliers[backup] = 1 - data.chance[keeper]
    nominal = tuple(sum(data.position[p] == pos for p in decision.starters) for pos in _OUTFIELD)
    distribution: dict[tuple[int, ...], float] = {(0, 0, 0): 1.0}
    for player in decision.starters:
        if data.position[player] == "GK":
            continue
        pos = _OUTFIELD.index(data.position[player])
        following: dict[tuple[int, ...], float] = {}
        for missing, mass in distribution.items():
            if data.chance[player] > 0:
                following[missing] = following.get(missing, 0.0) + mass * data.chance[player]
            if data.chance[player] < 1:
                more = tuple(value + int(i == pos) for i, value in enumerate(missing))
                following[more] = following.get(more, 0.0) + mass * (1 - data.chance[player])
        distribution = following
    bench = tuple(p for p in decision.bench if data.position[p] != "GK")
    states = 0
    for missing, mass in distribution.items():
        for appearance in product((False, True), repeat=3):
            rates = tuple(
                data.chance[p] if plays else 1 - data.chance[p]
                for p, plays in zip(bench, appearance, strict=True)
            )
            if any(rate == 0 for rate in rates):
                continue
            states += 1
            actual = [count - absent for count, absent in zip(nominal, missing, strict=True)]
            empty = sum(missing)
            for index, (player, plays) in enumerate(zip(bench, appearance, strict=True)):
                if not plays or empty == 0:
                    continue
                pos = _OUTFIELD.index(data.position[player])
                needed = sum(
                    max(0, minimum - count - int(i == pos))
                    for i, (minimum, count) in enumerate(zip(_MINIMUM, actual, strict=True))
                )
                # A legal nominal formation can fill the remaining vacant slots.
                # This is the official greedy replacement test with absent identities
                # eliminated: which missing player occupies a slot cannot affect admission.
                if actual[pos] < _MAXIMUM[pos] and empty - 1 >= needed:
                    actual[pos] += 1
                    empty -= 1
                    # Exclude this player's own q: his points already include it.
                    multipliers[player] += mass * math.prod(
                        rate for j, rate in enumerate(rates) if j != index
                    )
    data.states_evaluated += states
    result = (multipliers, states)
    data.autosub_cache[key] = result
    return result


def _typed_id(player: object) -> tuple[str, int | str]:
    return ("integer", int(player)) if isinstance(player, Integral) else ("string", str(player))


def _score(data: _Inputs, decision: _Decision) -> ExpectedLineupScore:
    autosub, states = _autosub_multipliers(data, decision)
    multipliers = dict(autosub)
    for player in data.ids if data.chip == "bboost" else decision.starters:
        multipliers[player] += 1.0
    bonus = 2 if data.chip == "3xc" else 1
    multipliers[decision.captain] += bonus
    multipliers[decision.vice] += bonus * (1 - data.chance[decision.captain])
    starting = math.fsum(data.points[p] for p in decision.starters)
    auto = math.fsum(autosub[p] * data.points[p] for p in data.ids)
    captain = bonus * data.points[decision.captain]
    vice = bonus * (1 - data.chance[decision.captain]) * data.points[decision.vice]
    boosted = math.fsum(data.points[p] for p in decision.bench) if data.chip == "bboost" else 0.0
    net = math.fsum(multipliers[p] * data.points[p] for p in data.ids) - data.hits
    if not all(math.isfinite(value) for value in (starting, auto, captain, vice, boosted, net)):
        raise ValueError("Expected lineup scores exceed the finite numeric range.")
    payload = {
        "version": EXPECTED_LINEUP_VERSION,
        "players": [
            (_typed_id(p), data.position[p], data.points[p].hex(), data.chance[p].hex())
            for p in data.ids
        ],
        "starters": [_typed_id(p) for p in decision.starters],
        "bench": [_typed_id(p) for p in decision.bench],
        "captain": _typed_id(decision.captain),
        "vice": _typed_id(decision.vice),
        "chip": data.chip,
        "hits": data.hits.hex(),
        "assumptions": ASSUMPTIONS,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ExpectedLineupScore(
        decision.starters,
        decision.bench,
        decision.captain,
        decision.vice,
        data.chip,
        data.hits,
        net,
        starting,
        auto,
        captain,
        vice,
        boosted,
        multipliers,
        fingerprint,
        states,
    )


def expected_lineup_score(
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
) -> ExpectedLineupScore:
    """Score one fixed legal 15/11 decision without a bench bonus or random draws.

    Signed points are unconditional weekly expectations. q is the probability of
    any positive minutes across the entire gameweek, including cameos and doubles;
    it is not start probability. q=0 requires points=0. Point dependence on other
    players' appearances and card-only participation are outside this model.
    Restrictions exclude captain AND vice. Transfer costs are supplied once.
    """
    decision = _Decision(tuple(starting_xi), tuple(ordered_bench), captain_id, vice_captain_id)
    data = _prepare(squad, decision, chip, hit_points, not_starting, not_captain)
    return _score(data, decision)


def _neighbors(data: _Inputs, original: _Decision) -> list[tuple[object, ...]]:
    lineups = [original.starters]
    for outgoing in sorted(original.starters, key=identifier_sort_key):
        for incoming in sorted(original.bench, key=identifier_sort_key):
            if incoming in data.not_starting:
                continue
            selected = tuple(incoming if p == outgoing else p for p in original.starters)
            counts = tuple(
                sum(data.position[p] == pos for p in selected) for pos in ("GK", *_OUTFIELD)
            )
            if counts[0] == 1 and all(
                low <= value <= high
                for low, value, high in zip(_MINIMUM, counts[1:], _MAXIMUM, strict=True)
            ):
                lineups.append(selected)
    return lineups


def _choices(
    data: _Inputs, original: _Decision, starters: tuple[object, ...]
) -> Iterable[_Decision]:
    eligible = sorted(
        (p for p in starters if p not in data.not_captain),
        key=lambda p: (-data.points[p], identifier_sort_key(p)),
    )
    if len(eligible) < 2:
        return
    pairs = [(c, v) for c in eligible for v in eligible if c != v]
    data.captain_pairs_considered += len(pairs)
    # All at most 110 eligible pairs can be ranked analytically, independently of
    # bench admission. This spends no extra lineup scores or autosub convolutions.
    captain, vice = min(
        pairs,
        key=lambda pair: (
            -(data.points[pair[0]] + (1 - data.chance[pair[0]]) * data.points[pair[1]]),
            identifier_sort_key(pair[0]),
            identifier_sort_key(pair[1]),
        ),
    )
    bench = tuple(p for p in data.ids if p not in starters)
    keeper = next(p for p in bench if data.position[p] == "GK")
    outfield = tuple(p for p in bench if data.position[p] != "GK")
    if starters == original.starters:
        yield _Decision(starters, original.bench, captain, vice)
    for ordering in permutations(outfield):
        yield _Decision(starters, (keeper, *ordering), captain, vice)


def improve_expected_lineup(
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
    max_evaluations: int = 128,
    locked_first: bool = False,
) -> ExpectedLineupSearchResult:
    """Keep the incumbent and explore legal one-player XI swaps on the same 15.

    Six outfield bench orders are considered, with the best eligible captain/vice
    pair found analytically for each visited XI (at most 110 ordered pairs).
    The incumbent XI's bench orders are completed first, then round-robin
    exploration gives XI alternatives a turn before exhausting their bench orders.
    The positive count cap includes the incumbent; duplicate scores
    and repeated autosub convolutions are cached. The XI/bench neighborhood remains
    bounded; no global lineup or transfer optimality is claimed.
    locked_first freezes the entire action, including bench order and vice.
    """
    if (
        isinstance(max_evaluations, bool)
        or not isinstance(max_evaluations, Integral)
        or not 1 <= max_evaluations <= 10000
    ):
        raise ValueError("max_evaluations must be an integer in [1, 10000].")
    if not isinstance(locked_first, bool):
        raise ValueError("locked_first must be boolean.")
    decision = _Decision(tuple(starting_xi), tuple(ordered_bench), captain_id, vice_captain_id)
    data = _prepare(squad, decision, chip, hit_points, not_starting, not_captain)
    incumbent = best = _score(data, decision)
    cache = {decision: incumbent}
    evaluations, cache_hits = 1, 0

    def finish(exhausted: bool) -> ExpectedLineupSearchResult:
        return ExpectedLineupSearchResult(
            incumbent,
            best,
            evaluations,
            int(max_evaluations),
            cache_hits,
            exhausted,
            locked_first,
            data.states_evaluated,
            data.autosub_cache_hits,
            data.captain_pairs_considered,
        )

    if locked_first:
        return finish(False)

    def candidates() -> Iterable[_Decision]:
        # Six backup orders must not be starved by the much larger XI menu.
        yield from _choices(data, decision, decision.starters)
        pending = [
            iter(_choices(data, decision, starters)) for starters in _neighbors(data, decision)[1:]
        ]
        while pending:
            following = []
            for iterator in pending:
                candidate = next(iterator, None)
                if candidate is not None:
                    following.append(iterator)
                    yield candidate
            pending = following

    for candidate in candidates():
        if candidate in cache:
            cache_hits += 1
            continue
        if evaluations >= max_evaluations:
            return finish(True)
        scored = _score(data, candidate)
        cache[candidate] = scored
        evaluations += 1
        if scored.expected_net_points > best.expected_net_points:
            best = scored
    return finish(False)
