"""The Top 100 influence: a member's own weight on last week's Top 100 starting elevens.

A preference, not a model. The published plan carries none of it (the handoff is built
without the uplift, ``--projection component-only``), and a member who asks for a weight
gets the one-week pure-points plan solved on points scaled by it::

    expected_points * (1 + weight / 100 * count / 100)

where ``count`` is how many of the 100 Top 100 teams started the player in the previous
gameweek (``elite_start_count_lag1``). A player all 100 teams started gets ``weight``
extra points for every 100 base points; a player nobody started, or one the evidence does
not name, is unchanged, and a zero stays a zero. This is the frozen 0.05 rule of
``prediction/elite_evidence.py`` with the coefficient chosen by the member instead of
fixed, applied to the base the handoff already holds, never stacked on an uplifted one.

Nothing measured says any weight scores better (the GW4 study on #566 measured how often
the decision changes, and says so). So every number a weighted
document publishes is the **base model's**: the plan is chosen on the weighted points and
then scored on the unweighted ones, and what the preference costs is the base-model
difference against the member's own pure-points plan (``application/advice.py``).

The counts pass the same gate the handoff applies (``apply_elite_evidence``): the week,
the deadline, a capture taken before the decision capture, all 100 members read, no
unmapped player, eleven starters each. The adjusted table that gate returns is discarded;
the gate is the point.
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.application.advice_capabilities import TOP100_WEIGHTS as _CAPABILITY_WEIGHTS
from squadopt.application.entries import EntryError
from squadopt.data.errors import DataError
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.transfers import TransferDecision
from squadopt.planning import PlanningWeekResult
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.elite_evidence import ELITE_COHORT_SIZE, apply_elite_evidence

#: The weights a member may choose. Zero is the published plan and has no file of its own.
#: Defined beside the other request capabilities, which a transport reads without this
#: module's solver-side imports, and named here because this is where the rule lives.
TOP100_WEIGHTS: Final[tuple[int, ...]] = _CAPABILITY_WEIGHTS

#: How a weighted document's price is measured: base-model expected points of the eleven
#: with the captain doubled, net of the game's hit charge, against the member's own
#: pure-points plan at weight zero.
TOP100_PRICE_BASIS: Final = "base_model_pure_points_v1"

#: The index reasons the page translates.
NO_TOP100_THIS_RUN: Final = "no_top100_this_run"
TOP100_INPUTS_REFUSED: Final = "top100_inputs_refused"
PUBLISHED_PLAN_CARRIES_TOP100: Final = "published_plan_carries_top100"

_ELITE_PICKS_PREFIX: Final = "fpl-elite-picks-"


class Top100InputsRefused(ValueError):
    """The week's Top 100 counts cannot be used for this capture; ``reason`` is the code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def top100_file(weight: int, *, word_file: str | None = None) -> str:
    """The file name of one weighted document, beside ``saf-puan/1.json``'s directory."""

    return f"top100-{weight}.json" if word_file is None else f"top100-{weight}-{word_file}"


def top100_manifest_path(table: Path) -> Path:
    """The manifest the evidence export writes beside its table."""

    table = Path(table)
    return table.with_name(table.name.removesuffix(".csv") + ".manifest.json")


def validate_top100_weight(value: object) -> int:
    """The weight as an int, when it is one the menu offers; anything else is refused."""

    if isinstance(value, bool) or not isinstance(value, int) or value not in TOP100_WEIGHTS:
        raise EntryError(
            f"The Top 100 influence must be one of {list(TOP100_WEIGHTS)}; got {value!r}."
        )
    return value


@dataclass(frozen=True, slots=True)
class Top100Counts:
    """How many Top 100 teams started each player last gameweek, with where it came from.

    Only players at least one team started are listed; a player absent here is a zero.
    """

    counts: Mapping[int, int]
    table_sha256: str
    cohort_snapshot_id: str
    picks_snapshot_id: str
    picks_gameweek: int

    def source_record(self) -> dict[str, object]:
        return {
            "cohort_snapshot_id": self.cohort_snapshot_id,
            "picks_snapshot_id": self.picks_snapshot_id,
            "table_sha256": self.table_sha256,
            "picks_gameweek": self.picks_gameweek,
        }


def load_top100_counts(
    table: Path,
    *,
    inputs: RecommendationInputs,
    projection: Projection,
) -> Top100Counts:
    """Read the week's evidence export and gate it exactly as the handoff would.

    Refused (``Top100InputsRefused``) when the projection already carries the uplift, since
    a weight on top of it would stack two, or when the export fails any of the handoff's
    own checks for this capture.
    """

    if projection.diagnostics.get("projection_evidence_fingerprint") is not None:
        raise Top100InputsRefused(
            PUBLISHED_PLAN_CARRIES_TOP100,
            "The projection already carries the Top 100 uplift; a member's weight would "
            "stack on it. Build the handoff without the evidence to offer the menu.",
        )
    manifest = top100_manifest_path(table)
    try:
        evidence = read_player_evidence_artifact(Path(table), manifest)
        apply_elite_evidence(
            projection.table.loc[:, ["player_id", "expected_points"]],
            evidence,
            season=inputs.season,
            target_gameweek=int(inputs.deadline.gameweek),
            deadline_timestamp_utc=inputs.deadline.deadline_utc,
            decision_captured_at_utc=inputs.captured_at_utc,
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        sources = document.get("source_snapshot_ids") if isinstance(document, dict) else None
        picks = [
            str(value)
            for value in (sources if isinstance(sources, list) else [])
            if str(value).startswith(_ELITE_PICKS_PREFIX)
        ]
        if len(picks) != 1:
            raise ValueError(
                f"The evidence manifest names {len(picks)} picks captures; exactly one is required."
            )
        counts = {
            int(player): int(count)
            for player, count in zip(
                evidence["player_id"].tolist(),
                evidence["elite_start_count_lag1"].tolist(),
                strict=True,
            )
            if int(count) > 0
        }
        return Top100Counts(
            counts=counts,
            table_sha256=str(evidence.attrs["table_sha256"]),
            cohort_snapshot_id=str(evidence.attrs["cohort_snapshot_id"]),
            picks_snapshot_id=picks[0],
            picks_gameweek=int(inputs.deadline.gameweek) - 1,
        )
    except (DataError, PredictionConfigurationError, OSError, ValueError, KeyError) as error:
        raise Top100InputsRefused(TOP100_INPUTS_REFUSED, str(error)) from error


def weighted_projection(base: Projection, counts: Mapping[int, int], weight: int) -> Projection:
    """``base`` with every player's points scaled by the weight and his start count.

    Only ``expected_points`` moves. Weight zero returns the same numbers.
    """

    weight = validate_top100_weight(weight)
    table = base.table.copy(deep=True)
    if weight:
        support = (
            table["player_id"]
            .map(lambda player: counts.get(int(player), 0))
            .astype("float64")
            .div(float(ELITE_COHORT_SIZE))
        )
        table["expected_points"] = table["expected_points"].astype("float64") * (
            1.0 + weight / 100.0 * support
        )
    return replace(base, table=table, diagnostics={**base.diagnostics, "top100_weight": weight})


def base_points(projection: Projection) -> dict[int, float]:
    """Every player's unweighted expected points, by id."""

    return {
        int(str(player)): float(str(points))
        for player, points in zip(
            projection.table["player_id"].tolist(),
            projection.table["expected_points"].tolist(),
            strict=True,
        )
    }


def base_net(week: PlanningWeekResult, points: Mapping[int, float]) -> float:
    """A solved week scored on base points: the eleven, the captain once more, minus hits.

    The same arithmetic as the planner's own ``projected_score`` less the game's charge
    (``net_expected_points``), with the points read from ``points`` instead of the week.
    """

    if week.chip is not None:
        raise EntryError("A weighted one-week plan plays no chip; this week plays one.")
    eleven = [points[int(str(player))] for player in week.starting_xi["player_id"]]
    captain = points[int(str(week.captain["player_id"]))]
    score = float(sum(eleven) + captain)
    hits = float(week.transfer_hit_points)
    if not math.isfinite(score) or not math.isfinite(hits):
        raise EntryError("A weighted plan must score to finite base points.")
    return score - hits


def _rebased(frame: pd.DataFrame, points: Mapping[int, float]) -> pd.DataFrame:
    out = frame.copy(deep=True)
    if not out.empty:
        out["expected_points"] = [points[int(str(player))] for player in out["player_id"]]
    return out


def rebased_week(week: PlanningWeekResult, points: Mapping[int, float]) -> PlanningWeekResult:
    """The same decisions, every player's expected points replaced by his base points."""

    captain: pd.Series[Any] = week.captain.copy(deep=True)
    captain["expected_points"] = points[int(str(captain["player_id"]))]
    starting_xi = _rebased(week.starting_xi, points)
    bench = _rebased(week.bench, points)
    return replace(
        week,
        selected_squad=_rebased(week.selected_squad, points),
        starting_xi=starting_xi,
        bench=bench,
        captain=captain,
        transfers_in=_rebased(week.transfers_in, points),
        transfers_out=_rebased(week.transfers_out, points),
        projected_score=float(
            starting_xi["expected_points"].sum()
            + (2 if week.chip == "3xc" else 1) * captain["expected_points"]
        ),
        projected_bench_points=float(bench["expected_points"].sum()),
    )


def decision_changed(
    control_week: PlanningWeekResult,
    control: TransferDecision,
    week: PlanningWeekResult,
    decision: TransferDecision,
) -> bool:
    """Whether two one-week plans differ in their moves, their eleven or their captain.

    A plan whose score moved while every decision stayed is not a changed plan.
    """

    if sorted(control.transfers_in_ids) != sorted(decision.transfers_in_ids):
        return True
    if sorted(control.transfers_out_ids) != sorted(decision.transfers_out_ids):
        return True
    control_eleven = {int(str(player)) for player in control_week.starting_xi["player_id"]}
    eleven = {int(str(player)) for player in week.starting_xi["player_id"]}
    if control_eleven != eleven:
        return True
    return int(str(control_week.captain["player_id"])) != int(str(week.captain["player_id"]))
