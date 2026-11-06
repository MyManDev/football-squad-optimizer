import { describe, expect, it } from "vitest";

import { BUNDLE_EXAMPLES } from "../../../fixtures/forwarder";
import vectors from "../entryState/vectors.json";
import { rebuildPurchasePrices, sellingInputs } from "../entryState/prices";
import { bankedFreeTransfers, chipStates, type ChipWindow } from "../entryState/rules";
import { bundleEntryState } from "./entryState";

const { free_hit_walk_back: freeHit, late_joiner: lateJoiner } = BUNDLE_EXAMPLES;
const WINDOWS = vectors.windows as ChipWindow[];

function read(bundle: typeof freeHit, entryId: number) {
  const result = bundleEntryState(bundle, { gameweek: 10 }, entryId);
  if (!result.ok) throw new Error(result.reason);
  return result.state;
}

describe("a forwarded bundle read through the entry-state readers", () => {
  it("walks a Free Hit back to the squad held before it", () => {
    const state = read(freeHit, 101);
    expect(state.entry).toEqual({ entry_id: 101, name: "Synthetic XI", started_event: 1 });
    expect([...state.picks.keys()]).toEqual([1, 8, 9]);
    expect(state.captured.gameweek).toBe(9);
    expect(state.captured.active_chip).toBe("freehit");
    expect(state.held.gameweek).toBe(8);
    expect(state.held.squad).toEqual(freeHit.picks[1]!.picks.map((pick) => pick.element));
    expect(state.opening?.gameweek).toBe(1);
    expect(state.history.chips_used).toEqual({ wildcard: [4], freehit: [9] });
    expect(state.transfers.map((row) => row.event)).toEqual([2, 5, 9]);
    // The rules take the readers' answers unchanged.
    expect(bankedFreeTransfers(state.history, 9, 5, state.captured.active_chip)).toEqual({
      count: 5,
      known: true,
    });
    const chips = chipStates(WINDOWS, 10, state.history.chips_used);
    expect(chips.wildcard.first_half).toMatchObject({ state: "used", gameweek: 4 });
    expect(chips.freehit.first_half).toMatchObject({ state: "used", gameweek: 9 });
    expect(chips.bboost.first_half).toMatchObject({ state: "available" });
  });

  it("replays the Free Hit entry's purchase prices from what the bundle holds", () => {
    const state = read(freeHit, 101);
    // What the bundle does not carry: the season's budget and fee, each opening player's
    // start price (the capture's table states them) and the deadlines (the calendar).
    const opening = state.opening!;
    const start = Object.fromEntries(
      opening.squad.map((id, index) => [id, index < 5 ? 67 : 66] as const),
    );
    const deadlines = Object.fromEntries(
      Array.from({ length: 10 }, (_, index) => [
        index + 1,
        new Date(Date.UTC(2026, 7, 21, 17, 30) + index * 7 * 86_400_000).toISOString(),
      ]),
    );
    const rebuilt = rebuildPurchasePrices({
      transfers: state.transfers,
      history: state.history,
      opening,
      held: state.held,
      budget_tenths: 1000,
      start_prices: start,
      deadlines,
      // As the capture's provider asks it: through the captured week, with its chip, and
      // the held squad the Free Hit walk-back gives.
      through_gameweek: state.captured.gameweek,
      active_chip: state.captured.active_chip,
      sell_on_fee: 0.5,
    });
    // The opening players still held keep their start price; 120 and 121 were bought for
    // 55 in weeks 2 and 5; the Free Hit's transfer in week 9 is replayed on a copy.
    const paid: Record<number, number> = { 120: 55, 121: 55 };
    for (let id = 101; id <= 113; id++) paid[id] = id <= 105 ? 67 : 66;
    expect(rebuilt).toEqual({
      known: true,
      prices: paid,
      applied: 2,
      free_hit_skipped: 1,
      pending: 0,
      sales_checked: 0,
    });
    // Each held player two tenths above what was paid sells for one tenth more.
    const current = Object.fromEntries(
      state.held.squad.map((id) => [id, rebuilt.prices[id]! + 2] as const),
    );
    const selling = sellingInputs(state.held, current, rebuilt, 0.5);
    expect(selling.purchase_prices_known).toBe(true);
    expect(selling.squad_sell_value_tenths).toBe(
      state.held.squad.reduce((total, id) => total + rebuilt.prices[id]! + 1, 0),
    );
  });

  it("reads a late joiner's picks in FPL's positions, with no opening fifteen", () => {
    const state = read(lateJoiner, 202);
    expect([...state.picks.keys()]).toEqual([9]);
    expect(state.held).toBe(state.captured);
    expect(state.opening).toBeNull();
    // The automatic substitution left 213 in the starter's position, as FPL answers it.
    expect(state.held.starting_xi).toContain(213);
    expect(state.held.squad.slice(11)).toEqual([212, 203, 214, 220]);
    expect(state.held.captain).toBe(205);
    expect(state.held.bank_tenths).toBe(5);
    expect(state.held.market_value_tenths).toBe(1003);
    // A history that starts after gameweek 1 leaves the count unknown, as the server does.
    expect(bankedFreeTransfers(state.history, 9, 5, null)).toEqual({ count: 1, known: false });
  });

  it("passes the identity rule's refusal on", () => {
    expect(bundleEntryState(lateJoiner, { gameweek: 9 }, 202)).toEqual({
      ok: false,
      reason: "table_gameweek_mismatch",
    });
  });

  it("is unreadable when a reader refuses a part, and throws nothing", () => {
    const short = {
      ...lateJoiner,
      picks: [{ ...lateJoiner.picks[0]!, picks: lateJoiner.picks[0]!.picks.slice(1) }],
    };
    expect(bundleEntryState(short, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "unreadable",
    });
    // A Free Hit whose basis week the bundle does not hold.
    const walk = {
      ...freeHit,
      picks: freeHit.picks.filter((row) => row.entry_history.event !== 8),
    };
    expect(bundleEntryState(walk, { gameweek: 10 }, 101)).toEqual({
      ok: false,
      reason: "unreadable",
    });
  });
});
