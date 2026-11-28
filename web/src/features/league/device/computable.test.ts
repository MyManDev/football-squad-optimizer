import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { EntrySquad } from "../types";
import { deviceComputable, deviceRivalUsable, type DeviceRivalReads } from "./computable";
import { deviceSelection } from "./selection";
import { deviceHorizonWindows } from "./types";

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

describe("the published horizon windows", () => {
  it.each([
    { title: "an older capture without a horizon", horizon: undefined, windows: [1] },
    { title: "a late-season capture carrying H3 only", horizon: { windows: [3] }, windows: [1, 3] },
    { title: "a capture carrying H3 and H5", horizon: { windows: [3, 5] }, windows: [1, 3, 5] },
  ])(
    "retains the published inputs in $title and leaves slow windows to the service",
    ({ horizon, windows }) => {
      const published = {
        ...own,
        device_plan: { ...own.device_plan!, ...(horizon ? { horizon } : {}) },
      };
      expect(deviceHorizonWindows(published.device_plan)).toEqual(windows.filter((w) => w !== 1));
      expect(deviceComputable(published, MEMBERS, read([]))?.windows).toEqual([1]);
      for (const window of [1, 3, 5] as const) {
        const selection = deviceSelection(
          { leagueId: own.league_id, entryId: ENTRY, strategy: "saf-puan", window },
          published,
        );
        expect(selection).toEqual(window === 1 ? { kind: "plain" } : null);
      }
    },
  );
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
    expect(deviceComputable(own, MEMBERS, read([benchedCaptain(35249002)]))?.invalidRivals).toEqual(
      [35249002],
    );
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
