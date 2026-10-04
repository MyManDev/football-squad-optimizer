import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import type { AdviceRequest } from "../advice/adviceClient";
import { deviceSelection, rivalFromSquad } from "./selection";

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
