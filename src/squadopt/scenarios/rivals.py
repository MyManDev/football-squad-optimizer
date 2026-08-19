"""The rival the crowd is, built from what the crowd actually owns.

Every rank measurement so far has played against a synthetic rival: the fold's own
risk-neutral squad. That rival is convenient — it always exists and it sits inside the
optimizer's feasible set — but nobody in a real league fields it. What a real league mostly
fields is the *template*: the most-owned goalkeeper, the most-owned defenders, and so on,
because ownership concentrates hard on a small set of players. "Beating the crowd" means
beating that eleven, and it can be built from data the platform publishes every week.

This module builds it. The input is a player pool with an ownership column; the output is a
:class:`RivalSquad` — the same object every scenario evaluation and rank optimization
already accepts, so nothing downstream changes to play against the crowd instead of a
synthetic opponent.

Two honest limits, stated rather than hidden:

- The platform publishes no captaincy share, so the template's captain is the most-owned
  member of its eleven. That understates real captaincy concentration on premium players,
  and the diagnostic records the rule so a better source can replace it visibly.
- A template is one squad, not a distribution over squads. Effective ownership, differential
  risk and the rest of the field's variety are not in this object; it is the single most
  representative opponent, not the whole league.
"""

from collections.abc import Mapping
from typing import Final

import pandas as pd

from squadopt.data.schema import POSITIONS
from squadopt.optimization import OptimizationConfig
from squadopt.scenarios.evaluation import RivalSquad
from squadopt.scenarios.models import ScenarioValidationError

TEMPLATE_RIVAL_CONTRACT_VERSION: Final = "ownership_template_rival_v1"
TEMPLATE_RIVAL_LABEL: Final = "ownership-template"

_REQUIRED_COLUMNS: Final = ("player_id", "position", "ownership")


def template_rival_from_ownership(
    pool: pd.DataFrame,
    *,
    label: str = TEMPLATE_RIVAL_LABEL,
    optimization_config: OptimizationConfig | None = None,
) -> RivalSquad:
    """Build the most-owned legal eleven from a pool, captained by its most-owned member.

    ``pool`` needs ``player_id``, ``position`` and ``ownership`` (any non-negative scale —
    percent, share or raw count — only the ordering matters). Selection is greedy under the
    formation limits the optimizer itself uses: fill every position's minimum with its
    most-owned players, then fill the remaining starting slots from the whole pool in
    ownership order, skipping any position already at its maximum.

    Greedy is exact here, not a shortcut: with one constraint per position and a fixed
    starting size, swapping any selected player for a more-owned unselected one either
    breaks a minimum, breaks a maximum, or contradicts the ordering the selection walked.

    Ties are broken by ``player_id`` so the same pool always yields the same rival.
    """

    settings = OptimizationConfig() if optimization_config is None else optimization_config
    if not isinstance(settings, OptimizationConfig):
        raise ScenarioValidationError("optimization_config must be an OptimizationConfig.")
    if not isinstance(pool, pd.DataFrame):
        raise ScenarioValidationError("pool must be a pandas DataFrame.")
    missing = [column for column in _REQUIRED_COLUMNS if column not in pool.columns]
    if missing:
        raise ScenarioValidationError(f"The pool lacks columns {missing!r}.")
    frame = pool.loc[:, list(_REQUIRED_COLUMNS)].copy()
    frame["ownership"] = pd.to_numeric(frame["ownership"], errors="coerce")
    if bool(frame["ownership"].isna().any()) or bool((frame["ownership"] < 0).any()):
        raise ScenarioValidationError("ownership must be numeric and non-negative on every row.")
    unknown = sorted(set(frame["position"].astype(str)) - set(POSITIONS))
    if unknown:
        raise ScenarioValidationError(f"The pool carries unknown positions {unknown!r}.")
    if bool(frame["player_id"].duplicated().any()):
        raise ScenarioValidationError("The pool names a player more than once.")

    # Ownership descending, player_id ascending: the second key makes the eleven a pure
    # function of the pool rather than of row order.
    frame = frame.sort_values(
        ["ownership", "player_id"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)

    by_position: dict[str, list[tuple[object, float]]] = {position: [] for position in POSITIONS}
    for row in frame.itertuples(index=False):
        by_position[str(row.position)].append((row.player_id, float(str(row.ownership))))

    minimums = dict(settings.starting_position_min)
    maximums = dict(settings.starting_position_max)
    chosen: list[tuple[object, float, str]] = []
    counts: dict[str, int] = dict.fromkeys(POSITIONS, 0)
    cursors: dict[str, int] = dict.fromkeys(POSITIONS, 0)

    for position in POSITIONS:
        needed = int(minimums.get(position, 0))
        available = by_position[position]
        if len(available) < needed:
            raise ScenarioValidationError(
                f"The pool holds {len(available)} {position} players; the formation needs "
                f"at least {needed}."
            )
        for _ in range(needed):
            player_id, ownership = available[cursors[position]]
            cursors[position] += 1
            counts[position] += 1
            chosen.append((player_id, ownership, position))

    while len(chosen) < settings.starting_size:
        best: tuple[float, object, str] | None = None
        for position in POSITIONS:
            if counts[position] >= int(maximums.get(position, settings.starting_size)):
                continue
            if cursors[position] >= len(by_position[position]):
                continue
            player_id, ownership = by_position[position][cursors[position]]
            # Highest ownership wins; the id tie-break keeps the fill deterministic when
            # two positions offer equally owned candidates.
            key = (-ownership, str(player_id), position)
            if best is None or key < (-best[0], str(best[1]), best[2]):
                best = (ownership, player_id, position)
        if best is None:
            raise ScenarioValidationError(
                "The pool cannot fill a legal eleven: every position is at its maximum or "
                "out of players."
            )
        best_ownership, best_player, best_position = best
        cursors[best_position] += 1
        counts[best_position] += 1
        chosen.append((best_player, best_ownership, best_position))

    captain_id = max(chosen, key=lambda entry: (entry[1], -_id_rank(entry[0])))[0]
    return RivalSquad(
        label=label,
        starter_ids=tuple(entry[0] for entry in chosen),
        captain_id=captain_id,
    )


def _id_rank(player_id: object) -> float:
    """A deterministic tie-break for the captaincy when ownership is equal."""

    try:
        return float(int(str(player_id)))
    except (TypeError, ValueError):
        return float(sum(ord(character) for character in str(player_id)))


def template_rival_diagnostics(pool: pd.DataFrame, rival: RivalSquad) -> Mapping[str, object]:
    """What the template is made of, for the artifact beside a measurement."""

    frame = pool.set_index("player_id")
    starters = list(rival.starter_ids)
    ownership = [float(str(frame.at[player, "ownership"])) for player in starters]
    positions = [str(frame.at[player, "position"]) for player in starters]
    return {
        "contract_version": TEMPLATE_RIVAL_CONTRACT_VERSION,
        "label": rival.label,
        "starters": len(starters),
        "formation": {position: int(positions.count(position)) for position in POSITIONS},
        "mean_ownership": float(sum(ownership) / len(ownership)) if ownership else 0.0,
        "minimum_ownership": float(min(ownership)) if ownership else 0.0,
        "captain_rule": "most_owned_starter",
        "captaincy_share_available": False,
    }


__all__ = [
    "TEMPLATE_RIVAL_CONTRACT_VERSION",
    "TEMPLATE_RIVAL_LABEL",
    "template_rival_diagnostics",
    "template_rival_from_ownership",
]
