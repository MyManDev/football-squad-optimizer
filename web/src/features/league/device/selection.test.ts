import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import type { AdviceRequest } from "../advice/adviceClient";
import { deviceSelection, offeredDeviceSelection, rivalFromSquad } from "./selection";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const plain: AdviceRequest = {
  leagueId: squad.league_id,
  entryId: squad.entry.entry_id,
  strategy: "saf-puan",
  window: 1,
};

describe("what the device solves", () => {
  it("is the plain plan, a held chip, or a rival strategy over one week", () => {
    expect(deviceSelection(plain, squad)).toEqual({ kind: "plain" });
    expect(deviceSelection({ ...plain, chip: "3xc" }, squad)).toEqual({
      kind: "chip",
      chip: "3xc",
    });
    expect(
      deviceSelection({ ...plain, strategy: "fark-yarat", rivalEntryId: 35249002 }, squad),
    ).toEqual({ kind: "rival", strategy: "fark-yarat", rivalEntryId: 35249002 });
    expect(
      deviceSelection({ ...plain, strategy: "ortak-koru", rivalEntryId: 35249002 }, squad),
    ).toEqual({ kind: "rival", strategy: "ortak-koru", rivalEntryId: 35249002 });
  });

  it("leaves every other selection to the service", () => {
    expect(deviceSelection({ ...plain, window: 3 }, squad)).toBeNull();
    expect(deviceSelection({ ...plain, top100Weight: 20 }, squad)).toBeNull();
    expect(deviceSelection({ ...plain, managersWord: true }, squad)).toBeNull();
    expect(deviceSelection({ ...plain, model: "football" }, squad)).toBeNull();
    // A rival strategy needs its rival, combines with no chip, and lives at one week.
    expect(deviceSelection({ ...plain, strategy: "fark-yarat" }, squad)).toBeNull();
    expect(
      deviceSelection(
        { ...plain, strategy: "fark-yarat", rivalEntryId: 35249002, chip: "3xc" },
        squad,
      ),
    ).toBeNull();
    expect(
      deviceSelection(
        { ...plain, strategy: "fark-yarat", rivalEntryId: 35249002, window: 3 },
        squad,
      ),
    ).toBeNull();
    // The plain plan names no rival.
    expect(deviceSelection({ ...plain, rivalEntryId: 35249002 }, squad)).toBeNull();
    // A chip the squad document does not hold, or the automatic chip, is not the device's.
    expect(deviceSelection({ ...plain, chip: "auto" }, squad)).toBeNull();
  });

  it("takes a weight the entry block names, for the pure-points plan at one week only", () => {
    const named = {
      ...squad,
      device_plan: {
        held: squad.starting_xi.map((p) => p.player_id),
        bank_tenths: 0,
        free_transfers: 1,
        sell_tenths: {},
        top100_weights: [20, 50],
      },
    };
    expect(deviceSelection({ ...plain, top100Weight: 20 }, named)).toEqual({
      kind: "top100",
      weight: 20,
    });
    expect(deviceSelection({ ...plain, top100Weight: 10 }, named)).toBeNull();
    expect(deviceSelection({ ...plain, top100Weight: 20, chip: "3xc" }, named)).toBeNull();
    expect(
      deviceSelection(
        { ...plain, top100Weight: 20, strategy: "fark-yarat", rivalEntryId: 35249002 },
        named,
      ),
    ).toBeNull();
    expect(deviceSelection({ ...plain, top100Weight: 20 }, squad)).toBeNull();
  });

  it("offers a rival strategy only against a rival the device's statement names", () => {
    const rival = { ...plain, strategy: "fark-yarat" as const, rivalEntryId: 35249002 };
    expect(offeredDeviceSelection(rival, squad, [35249002, 35249004])).toEqual({
      kind: "rival",
      strategy: "fark-yarat",
      rivalEntryId: 35249002,
    });
    expect(offeredDeviceSelection(rival, squad, [35249004])).toBeNull();
    expect(offeredDeviceSelection(rival, squad, [])).toBeNull();
    // The list narrows rivals only: the plain plan and a held chip stand as they are.
    expect(offeredDeviceSelection(plain, squad, [])).toEqual({ kind: "plain" });
    expect(offeredDeviceSelection({ ...plain, chip: "3xc" }, squad, [])).toEqual({
      kind: "chip",
      chip: "3xc",
    });
  });

  it("reads the rival's eleven and captain from their document, or nothing", () => {
    const rival = rivalFromSquad(35249002, squad);
    expect(rival).not.toBeNull();
    expect(rival!.starting_xi).toHaveLength(11);
    expect(rival!.starting_xi).toContain(rival!.captain);
    const unmarked = {
      starting_xi: squad.starting_xi.map((player) => ({ ...player, is_captain: false })),
    };
    expect(rivalFromSquad(35249002, unmarked)).toBeNull();
  });
});
