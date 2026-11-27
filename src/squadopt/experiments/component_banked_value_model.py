"""A carried free transfer valued by a Bellman model over the rest of the season.

Protocol: ``docs/research/component_banked_value_model_prereg.md``. Free transfers are a
stock. A week's opportunity is the vector ``g_k = P(k) - P(k-1)`` of what the ``k``-th free
transfer adds to the member policy's one-week plan. With independent weeks,

    V_{T+1}(b) = 0,
    V_t(b) = E_g [ max_{0 <= m <= b} (g_1 + ... + g_m + V_{t+1}(min(b - m + 1, C))) ],

and a decision at ``t`` adds ``V_{t+1}(n)`` for the ``n`` free transfers it carries. The
marginal values ``V_{t+1}(k) - V_{t+1}(k-1)`` fall with ``k``, add nothing past the cap and
reach zero at the season's last decision. ``GainProbeChain`` measures the vectors on the
policy chain's states; ``BankValueModelChain`` decides under the value function.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

import pandas as pd

from squadopt.evaluation.promotion import ExperimentConfigurationError
from squadopt.experiments.component_banked_transfer_value import PRIMARY_CELL, arm_label
from squadopt.experiments.component_hit_margin import MAX_LOSING_SEASONS, gate
from squadopt.experiments.season_chain import SeasonChain
from squadopt.planning import InitialSquadState, TransferPlanningConfig, optimize_transfer_plan

MODEL_LABEL: Final = f"{PRIMARY_CELL[0]}_{PRIMARY_CELL[1]}_bankmodel"
POLICY_LABEL: Final = arm_label(*PRIMARY_CELL, 0.0)
OWNER_LABEL: Final = arm_label(*PRIMARY_CELL, 1.12)
HALF_LABEL: Final = arm_label(*PRIMARY_CELL, 0.5)

ValueFunction = Mapping[int, Sequence[float]]
"""Decision gameweek -> ``W[n]`` for ``n = 0..C``: the value of carrying ``n`` free
transfers out of that decision (``V`` of the next decision, zero after the last)."""


def opportunity(objectives: Sequence[float]) -> tuple[float, ...]:
    """``g_k = P(k) - P(k-1)`` for ``k = 1..C`` from ``P(0..C)``, clipped at zero."""

    if len(objectives) < 2:
        raise ExperimentConfigurationError("An opportunity needs P(0) and at least P(1).")
    return tuple(
        max(0.0, float(objectives[k]) - float(objectives[k - 1])) for k in range(1, len(objectives))
    )


def bellman_values(
    gameweeks: Sequence[int], samples: Sequence[Sequence[float]], cap: int
) -> dict[int, tuple[float, ...]]:
    """The value of carrying ``n = 0..cap`` free transfers out of each decision gameweek.

    ``samples`` are opportunity vectors ``(g_1..g_cap)``; the expectation is their mean.
    Returns ``W[t][n] = V_{t'}(n)`` for the decision ``t'`` after ``t`` (zero for ``n = 0``
    and after the season's last decision).
    """

    if cap < 1 or not samples or any(len(g) < cap for g in samples):
        raise ExperimentConfigurationError("Every sample must cover the cap.")
    prefix = [[0.0, *(sum(float(x) for x in g[:m]) for m in range(1, cap + 1))] for g in samples]
    following = [0.0] * (cap + 1)  # V_{T+1}
    values: dict[int, tuple[float, ...]] = {}
    for gameweek in sorted(gameweeks, reverse=True):
        values[gameweek] = tuple(following)
        current = [0.0] * (cap + 1)
        for b in range(1, cap + 1):
            total = 0.0
            for sums in prefix:
                total += max(sums[m] + following[min(b - m + 1, cap)] for m in range(b + 1))
            current[b] = total / len(prefix)
        following = current
    return values


def marginal_values(row: Sequence[float]) -> tuple[float, ...]:
    """``w_k = W[k] - W[k-1]`` for ``k = 2..C``: the ``k``-th carried transfer's value."""

    return tuple(float(row[k]) - float(row[k - 1]) for k in range(2, len(row)))


def best_choice(candidates: Sequence[tuple[int | None, float, int]], row: Sequence[float]) -> int:
    """Index of the candidate with the highest ``objective + W[carried]``; ties to fewer moves.

    Each candidate is ``(cap, objective, carried)`` in increasing order of transfers allowed.
    """

    best = 0
    best_total = float("-inf")
    for index, (_, objective, carried) in enumerate(candidates):
        total = float(objective) + float(row[carried])
        if total > best_total + 1e-9:
            best, best_total = index, total
    return best


class GainProbeChain(SeasonChain):
    """The policy chain, measuring ``P(0..C)`` at every decision from its own state."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.objectives: dict[int, tuple[float, ...]] = {}
        self.free_transfers: dict[int, int] = {}

    def _week_transfer_config(self, gameweek: int, state: object) -> TransferPlanningConfig:
        frozen = self._settings.frozen_transfer_config
        pool, _, _, _ = self._week_pool(gameweek, state)  # type: ignore[arg-type]
        horizon = self._planning_horizon(pool, (gameweek,), state)  # type: ignore[arg-type]
        plain = replace(frozen, banked_transfer_value_points=0.0)
        values: list[float] = []
        for k in range(frozen.max_free_transfers + 1):
            plan = optimize_transfer_plan(
                horizon,
                InitialSquadState(
                    state.squad_ids,  # type: ignore[attr-defined]
                    bank_tenths=state.bank_tenths,  # type: ignore[attr-defined]
                    free_transfers=k,
                ),
                self._settings.frozen_optimization_config,
                plain,
                chips=None,
            )
            if not plan.has_solution or plan.objective_value is None:
                raise ExperimentConfigurationError(f"P({k}) has no plan at gameweek {gameweek}.")
            values.append(float(plan.objective_value))
        self.objectives[gameweek] = tuple(values)
        self.free_transfers[gameweek] = int(state.free_transfers)  # type: ignore[attr-defined]
        return frozen


class BankValueModelChain(SeasonChain):
    """The policy chain deciding each week under the value function ``W``."""

    def __init__(self, *args: object, values: ValueFunction, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._values = values
        self._caps: dict[int, int | None] = {}
        self.choices: dict[int, dict[str, object]] = {}

    def _week_pool(
        self, gameweek: int, state: object
    ) -> tuple[pd.DataFrame, frozenset[object], int, int]:
        pool, carried, blank, holes = super()._week_pool(gameweek, state)  # type: ignore[arg-type]
        frozen = self._settings.frozen_transfer_config
        row = self._values[gameweek]
        squad = set(state.squad_ids)  # type: ignore[attr-defined]
        held_pool = pool.loc[pool["player_id"].isin(squad)].reset_index(drop=True)
        free = int(state.free_transfers)  # type: ignore[attr-defined]
        candidates: list[tuple[int | None, float, int]] = []
        options: list[tuple[pd.DataFrame, int | None]] = [
            (held_pool, None),
            *((pool, cap) for cap in range(1, free + 1)),
            (pool, None),
        ]
        for option_pool, cap in options:
            horizon = self._planning_horizon(option_pool, (gameweek,), state)  # type: ignore[arg-type]
            plan = optimize_transfer_plan(
                horizon,
                InitialSquadState(
                    state.squad_ids,  # type: ignore[attr-defined]
                    bank_tenths=state.bank_tenths,  # type: ignore[attr-defined]
                    free_transfers=free,
                ),
                self._settings.frozen_optimization_config,
                replace(frozen, max_transfers_per_gameweek=cap),
                chips=None,
            )
            if not plan.has_solution or plan.objective_value is None:
                raise ExperimentConfigurationError(f"No candidate plan at gameweek {gameweek}.")
            carried_next = int(plan.weeks[0].free_transfers_for_next_gameweek)
            candidates.append((cap, float(plan.objective_value), carried_next))
        chosen = best_choice(candidates, row)
        self._caps[gameweek] = candidates[chosen][0]
        self.choices[gameweek] = {
            "free_transfers": free,
            "chosen": "hold" if chosen == 0 else candidates[chosen][0] or "uncapped",
            "carried": candidates[chosen][2],
            "marginal_values": list(marginal_values(row)),
        }
        return (held_pool if chosen == 0 else pool), carried, blank, holes

    def _week_transfer_config(self, gameweek: int, state: object) -> TransferPlanningConfig:
        frozen = self._settings.frozen_transfer_config
        return replace(frozen, max_transfers_per_gameweek=self._caps.get(gameweek))


def _interval(comparison: Mapping[str, object]) -> tuple[float, float]:
    bounds = comparison["weekly_advantage_block_bootstrap_interval"]
    if not isinstance(bounds, list | tuple) or len(bounds) != 2:
        raise ValueError("A comparison carries a two-sided interval.")
    return float(bounds[0]), float(bounds[1])


def side(comparison: Mapping[str, object]) -> str:
    low, high = _interval(comparison)
    return "better" if low > 0 else "worse" if high < 0 else "not_separable"


def model_reading(
    against_owner: Mapping[str, object],
    against_zero: Mapping[str, object],
    against_half: Mapping[str, object],
) -> dict[str, object]:
    """The protocol's three readings and its proposal."""

    primary = side(against_owner)
    verdict = gate(against_zero)
    passes = bool(verdict["passed"]) and len(verdict["losing_seasons"]) <= MAX_LOSING_SEASONS  # type: ignore[arg-type]
    proposal = {
        "better": "replace_the_constant_with_the_model",
        "not_separable": "owner_chooses",
        "worse": "keep_1.12",
    }[primary]
    return {
        "primary_against_1.12": primary,
        "against_0_gate_passed": passes,
        "against_0.5": side(against_half),
        "proposal": proposal,
    }
