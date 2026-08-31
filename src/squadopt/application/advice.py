"""One member's advice, as a pure application call: ``advise_entry``.

This is the seam the on-demand backend will stand on. The request is wire-shaped —
primitive fields only, deliberately **no Path anywhere**: ``DecideRequest`` carries
filesystem paths because it is an operator command, and a shape like that must never
travel over a network boundary. Everything else ``advise_entry`` needs — the picks
provider, the capture inputs, the projection, the season rules — is an injected
collaborator, so the function is a pure computation over what it is handed: the same
call from the batch site builder and from a future worker produces the same bytes.

Independence is structural here, as it is in the league builder: the provider reads
the league capture, which contains neither the requesting user's secrets nor our own
paper entry, so nothing a member is told can depend on the system's own squad.
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    held_squad_from_picks,
)
from squadopt.live import (
    Projection,
    RecommendationInputs,
    SeasonRules,
    plan_transfers,
)
from squadopt.live.transfers import TransferDecision

#: The one combination computed today: the deterministic planner's own answer.
COMPUTED_MODE = "saf-puan"
COMPUTED_WINDOW = 1


@dataclass(frozen=True, slots=True)
class AdviseEntryRequest:
    """Everything a caller may say about one advice computation — primitives only."""

    season: str
    gameweek: int
    league_id: int
    entry_id: int
    strategy: str = COMPUTED_MODE
    window: int = COMPUTED_WINDOW
    rival_entry_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise EntryError("season must be non-empty text.")
        for name in ("gameweek", "league_id", "entry_id"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EntryError(f"{name} must be a positive integer.")
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise EntryError("strategy must be non-empty text.")
        if isinstance(self.window, bool) or not isinstance(self.window, int):
            raise EntryError("window must be an integer.")
        if self.rival_entry_id is not None and (
            isinstance(self.rival_entry_id, bool)
            or not isinstance(self.rival_entry_id, int)
            or self.rival_entry_id < 1
        ):
            raise EntryError("rival_entry_id must be None or a positive integer.")


def _advice_player(row: "pd.Series[Any]") -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
    }


def build_advice_payload(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    mode: str = COMPUTED_MODE,
    decision: TransferDecision | None = None,
    expected_points_cost: float = 0.0,
    rival_label: str | None = None,
    solver_status: str | None = None,
    optimality_gap: float | None = None,
) -> dict[str, object]:
    """One member's advice payload — from their squad and the shared projection only.

    Without ``decision`` this solves the one-week pure-points plan itself: the site's
    saf-puan baseline, exactly what the page always showed. With one — a menu entry a
    mode's selector chose — it renders that decision instead, labelled ``mode`` and
    carrying the mode's expected-points price tag together with the solver's own account
    of that plan (``solver_status``, ``optimality_gap``), read from the menu entry it
    chose. A competitive mode without a supplied decision is refused rather than
    silently re-labelled as the baseline.

    A plan the solver found but could not prove optimal is published with
    ``solver_status: "FEASIBLE"`` and the measured bound gap, not discarded: the plan
    it found is real, the missing proof is stated, and the reader decides.
    """

    if mode != COMPUTED_MODE and decision is None:
        raise EntryError(f"Mode {mode!r} advice needs the decision its selector chose.")
    pool_by_id = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    if decision is None:
        prices = {
            int(str(row["player_id"])): int(str(row["price_tenths"]))
            for _, row in inputs.players.iterrows()
        }
        held = held_squad_from_picks(picks, current_prices=prices)
        plan, plan_decision, _ = plan_transfers(inputs, projection, held, rules)
        transfers: TransferDecision | None = plan_decision
        by_id = {
            int(str(row["player_id"])): row for _, row in plan.weeks[0].selected_squad.iterrows()
        }
        solver_status = plan.solver_status.name
        raw_gap = plan.diagnostics.get("absolute_optimality_gap")
        optimality_gap = float(str(raw_gap)) if raw_gap is not None else None
    else:
        transfers = decision
        by_id = pool_by_id
    reason_code = "window_value" if mode == COMPUTED_MODE else "mode_tradeoff"
    moves: list[dict[str, object]] = []
    if transfers is not None:
        record = transfers.as_record()
        outs_raw = record.get("transfers_out", [])
        ins_raw = record.get("transfers_in", [])
        outs = [int(str(v)) for v in outs_raw] if isinstance(outs_raw, list | tuple) else []
        ins = [int(str(v)) for v in ins_raw] if isinstance(ins_raw, list | tuple) else []
        for index in range(max(len(outs), len(ins))):
            player_out = outs[index] if index < len(outs) else None
            player_in = ins[index] if index < len(ins) else None
            delta = 0.0
            if player_in is not None and player_in in by_id:
                delta += float(str(by_id[player_in]["expected_points"]))
            if player_out is not None and player_out in pool_by_id:
                delta -= float(str(pool_by_id[player_out]["expected_points"]))
            moves.append(
                {
                    "move_id": f"gw{picks.gameweek + 1:02d}-{index + 1}",
                    "player_out": (
                        _advice_player(pool_by_id[player_out])
                        if player_out is not None and player_out in pool_by_id
                        else None
                    ),
                    "player_in": (
                        _advice_player(by_id[player_in])
                        if player_in is not None and player_in in by_id
                        else None
                    ),
                    "expected_points_delta": delta,
                    "expected_points_cost": float(str(record.get("transfer_hit_points", 0.0))),
                    "reason_code": reason_code,
                }
            )
    missing: list[str] = []
    if not picks.free_transfers_known:
        missing.append("free_transfers")
    if not picks.purchase_prices_known:
        missing.append("purchase_prices")
    return {
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "entry_id": picks.entry_id,
        "league_id": league_id,
        "mode": mode,
        "window": COMPUTED_WINDOW,
        "source_snapshot_id": picks.source_snapshot_id,
        "moves": moves,
        # The mode's whole-plan price against the pure-points pick, in expected points —
        # the only cross-mode number the site may show (no probability ships, ever).
        "expected_points_cost": float(expected_points_cost),
        "rival_label": rival_label,
        # The solver's own account of the plan: OPTIMAL is a proof, FEASIBLE is a found
        # plan with the measured bound gap beside it. Absent proof is stated, not hidden.
        "solver_status": solver_status,
        "optimality_gap": optimality_gap,
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
    }


def advise_entry(
    request: AdviseEntryRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
) -> dict[str, object]:
    """Compute one member's baseline advice for a validated request.

    The request is checked against the capture it will be answered from: the season and
    gameweek must be the capture's own, the strategy and window must be a combination
    that is actually computed, and a rival parameter is refused until the rival request
    lands — an advice file for a combination nobody computed would make the site show
    an answer where none was measured.
    """

    if request.season != str(inputs.season):
        raise EntryError(
            f"Request season {request.season!r} is not the capture's {inputs.season!r}."
        )
    if request.gameweek != int(inputs.deadline.gameweek):
        raise EntryError(
            f"Request gameweek {request.gameweek} is not the capture's "
            f"{int(inputs.deadline.gameweek)}."
        )
    if request.strategy != COMPUTED_MODE:
        raise EntryError(
            f"Strategy {request.strategy!r} is not computed on this path yet; only "
            f"{COMPUTED_MODE!r} is."
        )
    if request.window != COMPUTED_WINDOW:
        raise EntryError(f"Window {request.window} is not computed; only {COMPUTED_WINDOW} is.")
    if request.rival_entry_id is not None:
        raise EntryError(
            "A requested rival arrives with the rival request parameter; until then the "
            "competitive files come from the batch mode selection."
        )
    picks = provider.picks(request.entry_id, request.season, request.gameweek - 1)
    return build_advice_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=request.league_id,
    )


__all__: tuple[str, ...] = (
    "COMPUTED_MODE",
    "COMPUTED_WINDOW",
    "AdviseEntryRequest",
    "advise_entry",
    "build_advice_payload",
)
