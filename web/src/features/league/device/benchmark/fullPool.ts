/** Diagnostic-build substitution only; never imported or selected by the application. */
import type { HorizonInputs } from "../lp/horizon";
import type { HorizonPoolReduction } from "../lp/reduce";
import type { DevicePlanDocument, DevicePlanEntry } from "../types";

export function reduceHorizonPool(
  document: DevicePlanDocument,
  _entry: DevicePlanEntry,
  inputs: HorizonInputs,
  window: 3 | 5,
): HorizonPoolReduction {
  const purchases = inputs.rules.max_transfers_per_gameweek * window;
  return {
    indices: document.players.map((_, index) => index),
    before: document.players.length,
    after: document.players.length,
    purchaseUnionLimit: purchases,
    fullClubUnionLimit: Math.floor(
      (document.rules.squad_size + purchases - 1) / document.rules.max_players_per_team,
    ),
  };
}
