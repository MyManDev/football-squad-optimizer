/**
 * A forwarded entry bundle (`fpl_entry_bundle_v1`) read through the entry-state readers of
 * #983 steps 1 and 2. The bundle keeps FPL's own field names, so each part goes to its
 * reader unchanged: the entry to `readEntry`, the history to `readHistory`, the transfers to
 * `readTransfers` and each week's picks to `readPicks`, and the held squad is the Free Hit
 * walk-back of `heldSquadBasis` over the weeks the bundle holds. Nothing here asks the
 * network or solves a plan.
 */

import {
  EntryStateError,
  readEntry,
  readHistory,
  readPicks,
  type EntryPicks,
  type TransferHistory,
} from "../entryState/parsers";
import { readTransfers, type EntryTransfer } from "../entryState/prices";
import { heldSquadBasis } from "../entryState/rules";
import type { FplEntryBundle } from "./documents";
import { bundleMatchesTable, type BundleTableRefusal } from "./identity";

export interface BundleEntryState {
  entry: ReturnType<typeof readEntry>;
  history: TransferHistory;
  /** In time order, as the purchase-price replay takes them. */
  transfers: EntryTransfer[];
  /** Every week's picks the bundle holds, by gameweek. */
  picks: ReadonlyMap<number, EntryPicks>;
  /** The picks frozen at the deadline before the table's: the table gameweek minus 1. */
  captured: EntryPicks;
  /** The squad held at the table's deadline: the captured week's, or the one before a Free Hit. */
  held: EntryPicks;
  /** The gameweek 1 picks the purchase-price replay starts from; null for a late joiner. */
  opening: EntryPicks | null;
}

export type BundleEntryStateResult =
  { ok: true; state: BundleEntryState } | { ok: false; reason: BundleTableRefusal | "unreadable" };

/**
 * The bundle's entry state for the table of `table.gameweek`, once the identity rule holds.
 * A part a reader refuses makes the whole bundle `unreadable`; nothing is thrown.
 */
export function bundleEntryState(
  bundle: FplEntryBundle,
  table: { gameweek: number },
  entryId: number,
): BundleEntryStateResult {
  const match = bundleMatchesTable(bundle, table, entryId);
  if (!match.ok) return match;
  try {
    const picks = new Map(
      bundle.picks.map((document) => {
        const week = document.entry_history.event;
        return [week, readPicks(document, entryId, week)] as const;
      }),
    );
    const captured = picks.get(match.held_gameweek)!;
    const held = heldSquadBasis(captured, (week) => {
      const read = picks.get(week);
      if (read === undefined) throw new EntryStateError("The bundle holds no Free Hit basis.");
      return read;
    });
    return {
      ok: true,
      state: {
        entry: readEntry(bundle.entry, entryId),
        history: readHistory(bundle.history, entryId),
        transfers: readTransfers(bundle.transfers, entryId),
        picks,
        captured,
        held,
        opening: picks.get(1) ?? null,
      },
    };
  } catch (error) {
    if (error instanceof EntryStateError) return { ok: false, reason: "unreadable" };
    throw error;
  }
}
