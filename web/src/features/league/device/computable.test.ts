import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntrySquad } from "../types";
import { deviceComputable, deviceRivalUsable } from "./computable";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const SNAPSHOT = "fpl-live-20261002T104314Z-8b70515b9b31";

function squad(entryId: number, payload: Partial<EntrySquad> = {}): EntrySquad {
  return { ...mockEntrySquadEnvelopes[entryId]!.payload, source_snapshot_id: SNAPSHOT, ...payload };
}

const own = squad(ENTRY, {
  device_plan: { held: [], bank_tenths: 0, free_transfers: 1, sell_tenths: {} },
});

/** As entry 5349883 on the live tree: the armband on a bench player, none in the eleven. */
function benchedCaptain(entryId: number): EntrySquad {
  const base = squad(entryId);
  return {
    ...base,
    starting_xi: base.starting_xi.map((player) => ({ ...player, is_captain: false })),
    bench: base.bench.map((player, index) => ({ ...player, is_captain: index === 2 })),
  };
}

describe("the rivals the device offers", () => {
  it("are the members whose own document it has read and can play against", () => {
    const rivals = [
      squad(35249002),
      benchedCaptain(35249003),
      squad(35249004, { source_snapshot_id: "fpl-live-an-earlier-capture" }),
      squad(35249005),
    ];
    // 35249006 and later are not read yet, so they are not offered yet.
    expect(deviceComputable(own, MEMBERS, rivals)?.rivals).toEqual([35249002, 35249005]);
  });

  it("leave out a rival whose captain is on the bench, whose eleven the device cannot score", () => {
    expect(deviceRivalUsable(own, squad(35249002))).toBe(true);
    expect(deviceRivalUsable(own, benchedCaptain(35249002))).toBe(false);
    expect(deviceComputable(own, MEMBERS, [benchedCaptain(35249002)])?.rivals).toEqual([]);
  });

  it("are none before any rival document is read, and the statement is absent without inputs", () => {
    expect(deviceComputable(own, MEMBERS, [])?.rivals).toEqual([]);
    expect(deviceComputable({ ...own, device_plan: null }, MEMBERS, [squad(35249002)])).toBe(
      undefined,
    );
  });
});
