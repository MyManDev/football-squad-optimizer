"""Stated price against realized cost, from recorded advice; solves nothing.

The protocol is ``docs/live_price_honesty_prereg.md``. Both arms of every pair are documents
of one advice record: the member's control (``saf-puan`` at one week) and the plan under a
setting. Nobody has to have followed either, and what the member actually scored is not read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd

from squadopt.application.weekly_suggestion_eval import (
    SuggestionEvaluationError,
    score_recorded_advice,
)
from squadopt.data.errors import DataError
from squadopt.evaluation.models import EvaluationValidationError

LIVE_PRICE_HONESTY_CONTRACT_VERSION: Final = "live_price_honesty_v1"
CONTROL_STRATEGY: Final = "saf-puan"
FAMILY_RIVAL: Final = "rival_strategy"
FAMILY_TOP100: Final = "top100"
FAMILY_WORD: Final = "managers_word"
FAMILY_COMBINED: Final = "combined"
FAMILIES: Final = (FAMILY_RIVAL, FAMILY_TOP100, FAMILY_WORD, FAMILY_COMBINED)
#: The protocol's own numbers: no interval and no verdict below this many gameweeks.
MINIMUM_GAMEWEEKS_FOR_INTERVAL: Final = 6
BOOTSTRAP_DRAWS: Final = 2000
BOOTSTRAP_SEED: Final = 20260919
INTERVAL_LEVEL: Final = 0.90


class LivePriceHonestyError(DataError):
    """A record that cannot be paired is refused, never read around."""


@dataclass(frozen=True, slots=True)
class PricedPair:
    """One member, one setting, one gameweek: what the site said and what happened."""

    gameweek: int
    entry_id: int
    family: str
    setting: str
    binding: bool
    stated_cost: float
    realized_cost: float
    stated_ceiling: float | None


def _is_control(document: Mapping[str, Any], entry_id: object) -> bool:
    # Switched publications share the control's strategy, window and rival and differ by
    # address, so the address is checked as ``weekly_suggestion_eval`` checks it.
    baseline = f"advice/{entry_id}/{CONTROL_STRATEGY}/1.json"
    return (
        document.get("published_path", baseline) == baseline
        and document.get("strategy") == CONTROL_STRATEGY
        and document.get("window") == 1
        and document.get("rival_entry_id") is None
        and document.get("top100_weight") is None
        and document.get("managers_word") is not True
        and document.get("chip") is None
    )


def family_of(document: Mapping[str, Any]) -> str | None:
    """The setting family of a one-week document, or ``None`` for one the protocol leaves out."""

    if document.get("window") != 1 or document.get("chip") is not None:
        return None
    switched = [
        document.get("strategy") != CONTROL_STRATEGY,
        document.get("top100_weight") is not None,
        document.get("managers_word") is True,
    ]
    if sum(switched) == 0:
        return None
    if sum(switched) > 1:
        return FAMILY_COMBINED
    return (FAMILY_RIVAL, FAMILY_TOP100, FAMILY_WORD)[switched.index(True)]


def _setting(document: Mapping[str, Any]) -> str:
    parts = [str(document.get("strategy"))]
    if document.get("rival_entry_id") is not None:
        parts.append(f"rival-{document['rival_entry_id']}")
    if document.get("top100_weight") is not None:
        parts.append(f"top100-{document['top100_weight']}")
    if document.get("managers_word") is True:
        parts.append("word")
    return "/".join(parts)


def _decision(document: Mapping[str, Any]) -> tuple[object, ...]:
    # The eleven as a set, the bench in its order (the order the game's autosubs walk).
    return (
        tuple(sorted(int(player) for player in document["starting_xi"])),
        tuple(int(player) for player in document["bench"]),
        int(document["captain"]),
        int(document["vice_captain"]),
    )


def _expected_net(document: Mapping[str, Any]) -> float:
    return float(document["expected_own_points"]) - float(document["transfer_hit_points"])


def pairs_for_record(
    record: Mapping[str, Any], outcomes: pd.DataFrame
) -> tuple[tuple[PricedPair, ...], dict[str, int]]:
    """Every priced pair of one record, and a count of what was left out and why."""

    documents = [doc for doc in record.get("advice", ()) if isinstance(doc, Mapping)]
    controls = [doc for doc in documents if _is_control(doc, record.get("entry_id"))]
    if len(controls) != 1:
        raise LivePriceHonestyError("The record does not hold exactly one control.")
    control = controls[0]
    left_out: dict[str, int] = {}

    def leave(reason: str, count: int = 1) -> None:
        left_out[reason] = left_out.get(reason, 0) + count

    candidates = [doc for doc in documents if doc is not control]
    if control.get("solver_status") != "OPTIMAL" or control.get("scoring_complete") is not True:
        leave("control_not_proved_or_incomplete", len(candidates))
        return (), left_out
    try:
        control_score, _ = score_recorded_advice(record, control, outcomes)
    except (SuggestionEvaluationError, EvaluationValidationError, KeyError) as error:
        raise LivePriceHonestyError(f"The control cannot be scored: {error}") from error
    gameweek, entry_id = int(record["gameweek"]), int(record["entry_id"])
    pairs: list[PricedPair] = []
    seen: set[str] = set()
    for document in candidates:
        family = family_of(document)
        if family is None:
            leave("window_or_chip")
            continue
        setting = _setting(document)
        if setting in seen:
            leave("listed_twice")
            continue
        seen.add(setting)
        if document.get("scoring_complete") is not True:
            leave("setting_incomplete")
            continue
        try:
            score, _ = score_recorded_advice(record, document, outcomes)
        except (SuggestionEvaluationError, EvaluationValidationError, KeyError):
            leave("setting_unscorable")
            continue
        recorded = document.get("expected_points_cost")
        stated = (
            float(recorded)
            if recorded is not None
            else max(0.0, _expected_net(control) - _expected_net(document))
        )
        ceiling = document.get("expected_points_cost_ceiling")
        pairs.append(
            PricedPair(
                gameweek=gameweek,
                entry_id=entry_id,
                family=family,
                setting=setting,
                binding=_decision(document) != _decision(control),
                stated_cost=stated,
                realized_cost=control_score.net_points - score.net_points,
                stated_ceiling=None if ceiling is None else float(ceiling),
            )
        )
    return tuple(pairs), left_out


def _mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _interval(pairs: Sequence[PricedPair]) -> dict[str, object] | None:
    """Whole gameweeks are resampled: members share one projection and one set of matches."""

    by_week: dict[int, list[float]] = {}
    for pair in pairs:
        by_week.setdefault(pair.gameweek, []).append(pair.realized_cost - pair.stated_cost)
    if len(by_week) < MINIMUM_GAMEWEEKS_FOR_INTERVAL:
        return None
    weeks = sorted(by_week)
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        chosen = generator.choice(len(weeks), size=len(weeks), replace=True)
        pooled = [value for index in chosen for value in by_week[weeks[int(index)]]]
        draws.append(float(np.mean(pooled)))
    tail = (1.0 - INTERVAL_LEVEL) / 2.0
    low, high = (float(value) for value in np.quantile(draws, [tail, 1.0 - tail]))
    return {
        "level": INTERVAL_LEVEL,
        "low": low,
        "high": high,
        "resampled": "gameweeks",
        "gameweeks": len(weeks),
        "understates": low > 0.0,
    }


def summarise(pairs: Sequence[PricedPair]) -> dict[str, object]:
    """The protocol's statistics over binding pairs; the rest are counted, never averaged."""

    binding = [pair for pair in pairs if pair.binding]
    with_ceiling = [pair for pair in binding if pair.stated_ceiling is not None]
    return {
        "pairs": len(pairs),
        "binding_pairs": len(binding),
        "gameweeks": sorted({pair.gameweek for pair in binding}),
        "mean_stated_cost": _mean([pair.stated_cost for pair in binding]),
        "mean_realized_cost": _mean([pair.realized_cost for pair in binding]),
        "mean_realized_minus_stated": _mean(
            [pair.realized_cost - pair.stated_cost for pair in binding]
        ),
        "realized_above_stated": sum(pair.realized_cost > pair.stated_cost for pair in binding),
        "pairs_with_ceiling": len(with_ceiling),
        "realized_above_ceiling": sum(
            pair.realized_cost > float(pair.stated_ceiling or 0.0) for pair in with_ceiling
        ),
        "interval": _interval(binding),
    }


def reading(pairs: Sequence[PricedPair]) -> dict[str, object]:
    """Pooled, per family and per gameweek, in that order."""

    return {
        "pooled": summarise(pairs),
        "by_family": {
            family: summarise([pair for pair in pairs if pair.family == family])
            for family in FAMILIES
            if any(pair.family == family for pair in pairs)
        },
        "by_gameweek": {
            str(week): summarise([pair for pair in pairs if pair.gameweek == week])
            for week in sorted({pair.gameweek for pair in pairs})
        },
    }
