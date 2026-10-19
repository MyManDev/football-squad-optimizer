/**
 * The duel's arithmetic (#1133) on one league capture: the fixture's three human entries,
 * all from `example-post-deadline-gw02`. The sets and the difference are written out by
 * hand from the fixture's elevens, so a change to the rule shows here as a number.
 */
import { describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { duelOf } from "./duelSides";

const MEMBER = mockEntrySquadEnvelopes[35249001]!;
const SECOND = mockEntrySquadEnvelopes[35249002]!;
const FOURTH = mockEntrySquadEnvelopes[35249003]!;

const ids = (players: { player_id: number }[]) => players.map((player) => player.player_id);
const sorted = (values: Iterable<number>) => [...values].sort((a, b) => a - b);

describe("the duel of two elevens from one capture", () => {
  it("splits the elevens into the shared and the differing players", () => {
    const duel = duelOf(MEMBER, SECOND)!;
    expect(sorted(duel.shared)).toEqual([103, 104, 107, 108, 110, 111]);
    expect(ids(duel.member.eleven).filter((id) => !duel.shared.has(id))).toEqual([
      101, 102, 105, 106, 109,
    ]);
    expect(ids(duel.rival.eleven).filter((id) => !duel.shared.has(id))).toEqual([
      116, 118, 119, 122, 123,
    ]);
  });

  it("counts each captain twice, so the same armband adds nothing to the difference", () => {
    const duel = duelOf(MEMBER, SECOND)!;
    expect(duel.member.captain.player_id).toBe(107);
    expect(duel.rival.captain.player_id).toBe(107);
    // 59.2 for the eleven and Lane's 6.7 again; 54.4 and the same 6.7.
    expect(duel.member.total).toBeCloseTo(65.9, 9);
    expect(duel.rival.total).toBeCloseTo(61.1, 9);
    // 27.0 from 101, 102, 105, 106, 109 against 22.2 from 116, 118, 119, 122, 123.
    expect(duel.difference).toBeCloseTo(4.8, 9);
    expect(duel.fromPlayers).toBeCloseTo(4.8, 9);
    expect(duel.fromCaptains).toBe(0);
  });

  it("puts a different armband's share in its own part, and the parts add up", () => {
    const duel = duelOf(MEMBER, FOURTH)!;
    expect(sorted(duel.shared)).toEqual([104, 105, 106, 111]);
    expect(duel.rival.captain.player_id).toBe(106);
    expect(duel.member.total).toBeCloseTo(65.9, 9);
    expect(duel.rival.total).toBeCloseTo(59.3, 9);
    expect(duel.fromPlayers).toBeCloseTo(6.1, 9);
    expect(duel.fromCaptains).toBeCloseTo(0.5, 9);
    expect(duel.difference).toBeCloseTo(6.6, 9);
    expect(duel.fromPlayers + duel.fromCaptains).toBeCloseTo(duel.difference, 9);
  });

  it("reads from the rival's side as the same duel with the sign turned", () => {
    const there = duelOf(MEMBER, FOURTH)!;
    const back = duelOf(FOURTH, MEMBER)!;
    expect(back.difference).toBeCloseTo(-there.difference, 9);
    expect(sorted(back.shared)).toEqual(sorted(there.shared));
  });

  it.each([
    ["another league", { league_id: 1 }],
    ["another season", { season: "2027-28" }],
    ["another gameweek", { gameweek: 3 }],
    ["another capture", { source_snapshot_id: "example-post-deadline-gw03" }],
    ["no capture named", { source_snapshot_id: null }],
  ])("gives no duel against a document from %s", (_, patch) => {
    expect(duelOf(MEMBER, { ...SECOND, payload: { ...SECOND.payload, ...patch } })).toBeNull();
    expect(duelOf({ ...MEMBER, payload: { ...MEMBER.payload, ...patch } }, SECOND)).toBeNull();
  });

  it("gives no duel of a member against himself or across example and live documents", () => {
    expect(duelOf(MEMBER, MEMBER)).toBeNull();
    expect(duelOf(MEMBER, { ...SECOND, source_kind: "live" })).toBeNull();
  });

  it("gives no duel for a partial eleven, a repeated player or an eleven without one captain", () => {
    const eleven = SECOND.payload.starting_xi;
    const withEleven = (starting_xi: typeof eleven) => ({
      ...SECOND,
      payload: { ...SECOND.payload, starting_xi },
    });
    expect(duelOf(MEMBER, withEleven(eleven.slice(0, 10)))).toBeNull();
    expect(duelOf(MEMBER, withEleven([...eleven.slice(0, 10), eleven[0]!]))).toBeNull();
    expect(
      duelOf(MEMBER, withEleven(eleven.map((player) => ({ ...player, is_captain: false })))),
    ).toBeNull();
    expect(
      duelOf(MEMBER, withEleven(eleven.map((player) => ({ ...player, is_captain: true })))),
    ).toBeNull();
    expect(
      duelOf(
        MEMBER,
        withEleven(
          eleven.map((player, i) => (i === 3 ? { ...player, expected_points: NaN } : player)),
        ),
      ),
    ).toBeNull();
  });
});
