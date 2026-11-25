import { describe, expect, it } from "vitest";

import type { EntryChipAvailability, EntrySquad } from "../types";
import { squadWithPlayedWeek, type PlayedLineup } from "./memberLineup";

const window = (state: "available" | "used" | "not_yet", gameweek: number | null, half: 1 | 2) => ({
  state,
  gameweek,
  start_event: half === 1 ? 2 : 20,
  stop_event: half === 1 ? 19 : 38,
});

const chips: EntryChipAvailability = {
  known: true,
  gameweek: 11,
  states: {
    wildcard: { first_half: window("available", null, 1), second_half: window("not_yet", null, 2) },
    bboost: { first_half: window("used", 4, 1), second_half: window("not_yet", null, 2) },
  },
};

// Only the fields the overlay reads; the rest of a squad passes through untouched.
const squad = {
  gameweek: 11,
  starting_xi: [],
  bench: [],
  chips_used: { bboost: [4] },
  chips,
} as unknown as EntrySquad;

const lineup = (active_chip: string | null): PlayedLineup => ({
  starting_xi: [],
  bench: [],
  gameweek: 11,
  active_chip,
});

describe("the squad shown once its week is played", () => {
  it("records the chip played at the deadline as used that week", () => {
    const shown = squadWithPlayedWeek(squad, lineup("wildcard"));
    expect(shown.chips_used).toEqual({ bboost: [4], wildcard: [11] });
    expect(shown.chips!.states.wildcard!.first_half).toMatchObject({ state: "used", gameweek: 11 });
    // The other half and the other chips stand as published.
    expect(shown.chips!.states.wildcard!.second_half).toEqual(chips.states.wildcard!.second_half);
    expect(shown.chips!.states.bboost).toEqual(chips.states.bboost);
    // The published record itself is not rewritten.
    expect(squad.chips_used).toEqual({ bboost: [4] });
    expect(chips.states.wildcard!.first_half!.state).toBe("available");
  });

  it("leaves the record as published when no chip was played or none was read", () => {
    expect(squadWithPlayedWeek(squad, lineup(null)).chips).toBe(chips);
    expect(squadWithPlayedWeek(squad, lineup(null)).chips_used).toBe(squad.chips_used);
    expect(squadWithPlayedWeek(squad, null).chips).toBe(chips);
  });

  it("does not record a chip twice when the published record already has it", () => {
    const shown = squadWithPlayedWeek(squad, { ...lineup("bboost"), gameweek: 4 });
    expect(shown.chips_used).toEqual({ bboost: [4] });
    expect(shown.chips!.states.bboost).toEqual(chips.states.bboost);
  });

  it("no longer states the free transfers, which were the passed deadline's", () => {
    const counted = { ...squad, free_transfers: 1, free_transfers_known: true } as EntrySquad;
    expect(squadWithPlayedWeek(counted, lineup("wildcard")).free_transfers_known).toBe(false);
    expect(squadWithPlayedWeek(counted, null).free_transfers_known).toBe(false);
    expect(counted.free_transfers_known).toBe(true);
  });

  it("keeps an uncaptured history uncaptured", () => {
    const unknown = { ...squad, chips_used: null, chips: undefined } as unknown as EntrySquad;
    const shown = squadWithPlayedWeek(unknown, lineup("wildcard"));
    expect(shown.chips_used).toBeNull();
    expect(shown.chips).toBeUndefined();
  });
});
