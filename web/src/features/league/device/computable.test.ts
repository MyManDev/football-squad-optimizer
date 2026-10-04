import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntrySquad } from "../types";
import { deviceComputable, deviceRivalUsable, type DeviceRivalReads } from "./computable";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const SNAPSHOT = "fpl-live-20261002T104314Z-8b70515b9b31";

function squad(entryId: number, payload: Partial<EntrySquad> = {}): EntrySquad {
  return { ...mockEntrySquadEnvelopes[entryId]!.payload, source_snapshot_id: SNAPSHOT, ...payload };
}

function read(squads: EntrySquad[], more: Partial<DeviceRivalReads> = {}): DeviceRivalReads {
  return { squads, loading: false, unreadable: [], ...more };
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
    expect(deviceComputable(own, MEMBERS, read(rivals))?.rivals).toEqual([35249002, 35249005]);
  });

  it("leave out a rival whose captain is on the bench, whose eleven the device cannot score", () => {
    expect(deviceRivalUsable(own, squad(35249002))).toBe(true);
    expect(deviceRivalUsable(own, benchedCaptain(35249002))).toBe(false);
    expect(deviceComputable(own, MEMBERS, read([benchedCaptain(35249002)]))?.rivals).toEqual([]);
  });

  it("are none before any rival document is read, and the statement is absent without inputs", () => {
    expect(deviceComputable(own, MEMBERS, read([]))?.rivals).toEqual([]);
    expect(deviceComputable({ ...own, device_plan: null }, MEMBERS, read([squad(35249002)]))).toBe(
      undefined,
    );
  });

  it("say while the documents are still being read, and which could not be read", () => {
    const statement = deviceComputable(
      own,
      MEMBERS,
      read([squad(35249002)], { loading: true, unreadable: [35249004, 99999999] }),
    );
    expect(statement?.rivals).toEqual([35249002]);
    expect(statement?.loading).toBe(true);
    // Only a member of the league can be an unread rival.
    expect(statement?.unreadRivals).toEqual([35249004]);
  });
});
