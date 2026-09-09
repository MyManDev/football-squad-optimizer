import { describe, expect, it } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { comparedRivalPlayers } from "./rivalPlayers";

const own = mockEntrySquadEnvelopes[35249001]!;
const base = mockEntryAdviceEnvelope(35249001, "ortak-koru", 1, 35249002);
const rival = mockEntrySquadEnvelopes[35249002]!;

describe("published player identity comparison", () => {
  it("includes the recommended bench in the overlap basis and preserves source names/order", () => {
    const recommended = [...base.payload.starting_xi!, ...base.payload.bench!];
    const held = recommended
      .slice(4)
      .map((player, i) => ({ ...rival.payload.starting_xi[i]!, ...player }));
    const changed = { ...rival, payload: { ...rival.payload, starting_xi: held } };
    const result = comparedRivalPlayers(base, own, changed)!;
    expect(result.shared.map((player) => player.player_id)).toEqual(
      recommended.slice(4).map((player) => player.player_id),
    );
    expect(result.recommendedOnly.map((player) => player.name)).toEqual(
      recommended.slice(0, 4).map((player) => player.name),
    );
    expect(result.rivalOnly).toEqual([]);
    expect(
      result.shared.some((player) => player.player_id === base.payload.bench![0]!.player_id),
    ).toBe(true);
  });
  it.each([
    { league_id: 9 },
    { season: "next" },
    { gameweek: 99 },
    { source_snapshot_id: "other" },
  ])("does not compare a rival with different publication context %j", (fields) => {
    expect(
      comparedRivalPlayers(base, own, { ...rival, payload: { ...rival.payload, ...fields } }),
    ).toBeNull();
  });
  it("requires selected rival identity and complete unique player lists", () => {
    expect(comparedRivalPlayers(base, own, own)).toBeNull();
    expect(comparedRivalPlayers(base, own, null)).toBeNull();
    expect(
      comparedRivalPlayers({ ...base, payload: { ...base.payload, bench: null } }, own, rival),
    ).toBeNull();
    expect(
      comparedRivalPlayers(base, own, {
        ...rival,
        payload: { ...rival.payload, starting_xi: Array(11).fill(rival.payload.starting_xi[0]) },
      }),
    ).toBeNull();
    expect(
      comparedRivalPlayers(
        { ...base, payload: { ...base.payload, source_snapshot_id: null } },
        own,
        rival,
      ),
    ).toBeNull();
  });
});
