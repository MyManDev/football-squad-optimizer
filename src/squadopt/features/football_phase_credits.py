"""Bind final FPL assists only when independent totals force one event assignment.

Callers supply every physical goal for one club-fixture and its independently
verified final FPL totals. This pure binder does not establish source admission,
phase coverage, historical availability or player minutes. Provider assist actors
are deliberately absent from its input contract.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import cache

from squadopt.features.football_phase_inputs import PHASES, PhaseGoal, PhaseTotal

PHASE_CREDIT_BINDING_VERSION = "unique_independent_fpl_event_credits_v1"
MAX_CREDIT_EVENTS = 64
MAX_SEARCH_NODES = 100_000


@dataclass(frozen=True, slots=True)
class PhaseCreditEvent:
    event_id: str
    phase: str
    scorer: int | None
    own_goal: bool
    source_evidence_ref: str


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("Phase credit evidence and identities must be bounded nonempty text.")
    return value


def _identity(value: object) -> None:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError("Phase credits require positive integer player identities.")


def _evidence(event: PhaseCreditEvent, totals_evidence_ref: str) -> str:
    return _text(
        json.dumps(
            {
                "binding_version": PHASE_CREDIT_BINDING_VERSION,
                "event": event.source_evidence_ref,
                "independent_fpl_totals": totals_evidence_ref,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _validated_totals(totals: tuple[PhaseTotal, ...]) -> dict[int, PhaseTotal]:
    if type(totals) is not tuple or not totals:
        raise ValueError("Phase credits require immutable complete independent FPL totals.")
    by_code = {}
    for total in totals:
        if not isinstance(total, PhaseTotal):
            raise ValueError("An independent FPL total has an invalid record.")
        _identity(total.player_code)
        if total.player_code in by_code:
            raise ValueError("Independent FPL totals repeat a player identity.")
        if any(type(value) is not int or value < 0 for value in (total.goals, total.assists)):
            raise ValueError("Independent FPL totals require nonnegative integer credits.")
        by_code[total.player_code] = total
    return by_code


def _validated_events(
    events: tuple[PhaseCreditEvent, ...],
    totals: dict[int, PhaseTotal],
    totals_evidence_ref: str,
) -> tuple[str, ...]:
    if type(events) is not tuple or len(events) > MAX_CREDIT_EVENTS:
        raise ValueError("Phase credits require a bounded immutable complete goal sequence.")
    seen = set()
    scorers: Counter[int] = Counter()
    evidence = []
    for event in events:
        if not isinstance(event, PhaseCreditEvent):
            raise ValueError("A physical phase goal has an invalid record.")
        _text(event.event_id)
        _text(event.source_evidence_ref)
        if event.event_id in seen or event.phase not in PHASES:
            raise ValueError("Physical goals repeat an event or lack a supported disjoint phase.")
        seen.add(event.event_id)
        if type(event.own_goal) is not bool or (event.scorer is None) != event.own_goal:
            raise ValueError("An own goal must have no credited attacking scorer.")
        if event.scorer is not None:
            _identity(event.scorer)
            if event.scorer not in totals:
                raise ValueError("A physical scorer is absent from independent FPL totals.")
            scorers[event.scorer] += 1
        evidence.append(_evidence(event, totals_evidence_ref))
    if any(scorers[code] != total.goals for code, total in totals.items()):
        raise ValueError("Physical scoring credits differ from independent FPL totals.")
    if sum(total.assists for total in totals.values()) > len(events):
        raise ValueError("FPL assist credits exceed the complete physical goal count.")
    return tuple(evidence)


def bind_unique_phase_credits(
    events: tuple[PhaseCreditEvent, ...],
    totals: tuple[PhaseTotal, ...],
    *,
    totals_evidence_ref: str,
    max_search_nodes: int = MAX_SEARCH_NODES,
) -> tuple[PhaseGoal, ...]:
    """Refuse absent or ambiguous assignments, including ambiguity within a phase.

    Each physical goal has at most one FPL assist, which cannot belong to its scorer.
    An own goal may have an attacking assist. Zero-credit players remain in the
    independent roster, and an explicit unassisted category fills the other events.
    No score, duty, source timestamp or provider assist is inferred here.
    """
    if type(max_search_nodes) is not int or not 0 < max_search_nodes <= MAX_SEARCH_NODES:
        raise ValueError("Phase credit search needs an explicit bounded positive node limit.")
    _text(totals_evidence_ref)
    by_code = _validated_totals(totals)
    evidence = _validated_events(events, by_code, totals_evidence_ref)
    actors: tuple[int | None, ...] = (
        None,
        *sorted(code for code, total in by_code.items() if total.assists),
    )
    remaining = (
        len(events) - sum(total.assists for total in totals),
        *(by_code[code].assists for code in actors[1:] if code is not None),
    )
    # This capacity is only the no-self-assist constraint, not guessed on-field time.
    capacity = tuple(
        tuple(
            sum(actor is None or event.scorer != actor for event in events[index:])
            for actor in actors
        )
        for index in range(len(events) + 1)
    )
    visited = 0

    @cache
    def ways(index: int, counts: tuple[int, ...]) -> int:
        nonlocal visited
        visited += 1
        if visited > max_search_nodes:
            raise ValueError("Phase credit assignment exceeded its bounded search.")
        if any(count > room for count, room in zip(counts, capacity[index], strict=True)):
            return 0
        if index == len(events):
            return int(not any(counts))
        found = 0
        for choice, (actor, count) in enumerate(zip(actors, counts, strict=True)):
            if not count or (actor is not None and actor == events[index].scorer):
                continue
            following = (*counts[:choice], count - 1, *counts[choice + 1 :])
            found += ways(index + 1, following)
            if found >= 2:
                return 2
        return found

    assignments = ways(0, remaining)
    if assignments == 0:
        raise ValueError("Independent FPL totals have no valid event assist assignment.")
    if assignments != 1:
        raise ValueError("Independent FPL totals leave ambiguous event assist assignments.")
    result = []
    for index, event in enumerate(events):
        for choice, (actor, count) in enumerate(zip(actors, remaining, strict=True)):
            if not count or (actor is not None and actor == event.scorer):
                continue
            following = (*remaining[:choice], count - 1, *remaining[choice + 1 :])
            if ways(index + 1, following) == 1:
                result.append(
                    PhaseGoal(
                        event.event_id,
                        event.phase,
                        event.scorer,
                        actor,
                        event.own_goal,
                        evidence[index],
                    )
                )
                remaining = following
                break
    return tuple(result)
