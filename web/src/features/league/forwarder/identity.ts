/**
 * The identity rule for live entry inputs (#983 step 3, `docs/contracts/league_device_plan_v1.md`):
 * a forwarded entry bundle is combined with a device table only when it holds the squad
 * that table plans from. The table plans gameweek N from the picks frozen at deadline N - 1,
 * so the bundle's held picks must be gameweek N - 1's, and its history must have that week.
 */

import type { FplEntryBundle } from "./documents";

/**
 * Why a bundle is not combined with a table:
 *
 * - `entry_mismatch`: the bundle, or the entry it names, is another member's;
 * - `table_gameweek_mismatch`: it was asked for another table gameweek;
 * - `picks_gameweek_mismatch`: its newest picks are not the table gameweek minus 1;
 * - `history_missing_week`: its history has no row for that week.
 */
export type BundleTableRefusal =
  "entry_mismatch" | "table_gameweek_mismatch" | "picks_gameweek_mismatch" | "history_missing_week";

export type BundleTableMatch =
  { ok: true; held_gameweek: number } | { ok: false; reason: BundleTableRefusal };

/** Whether `bundle` may be combined with the table of `table.gameweek` for `entryId`. */
export function bundleMatchesTable(
  bundle: Pick<FplEntryBundle, "entry_id" | "gameweek" | "entry" | "history" | "picks">,
  table: { gameweek: number },
  entryId: number,
): BundleTableMatch {
  if (bundle.entry_id !== entryId || bundle.entry.id !== entryId) {
    return { ok: false, reason: "entry_mismatch" };
  }
  if (bundle.gameweek !== table.gameweek) return { ok: false, reason: "table_gameweek_mismatch" };
  const held = table.gameweek - 1;
  const newest = bundle.picks.at(-1)?.entry_history.event;
  if (newest !== held || bundle.picks.some((picks) => picks.entry_history.event > held)) {
    return { ok: false, reason: "picks_gameweek_mismatch" };
  }
  if (!bundle.history.current.some((row) => row.event === held)) {
    return { ok: false, reason: "history_missing_week" };
  }
  return { ok: true, held_gameweek: held };
}
