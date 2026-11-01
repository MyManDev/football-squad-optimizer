import { describe, expect, it } from "vitest";

import { BUNDLE_EXAMPLES } from "../../../fixtures/forwarder";
import vectors from "../entryState/vectors.json";
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
