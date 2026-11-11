import { describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { ForwarderResult, StandingsReason } from "../forwarder/client";
import type { FplH2hMatch, FplH2hMatches } from "../forwarder/documents";
import { chooseRival, h2hOpponent, H2H_PAGES, rivalChoices } from "./liveRival";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const SELF = 35249001;
const choices = rivalChoices(MEMBERS, SELF, null, "Unnamed");

describe("the members the picker offers", () => {
  it("are the other human members in the list's order, never the system or the member", () => {
    const humans = MEMBERS.filter((member) => member.member_kind === "human");
    expect(choices.map((choice) => choice.entryId)).toEqual(
      humans.map((member) => member.entry_id).filter((id) => id !== SELF),
    );
    expect(choices.find((choice) => choice.entryId === 35249009)?.name).toBe(
      humans.find((member) => member.entry_id === 35249009)!.manager_name ?? "Unnamed",
    );
  });

  it("take the head-to-head opponent the page does not hold", () => {
    const withOpponent = rivalChoices(MEMBERS, SELF, { entryId: 7777, name: "Far Away" }, "-");
    expect(withOpponent.at(-1)).toEqual({ entryId: 7777, name: "Far Away" });
    expect(rivalChoices(MEMBERS, SELF, { entryId: 35249002, name: "x" }, "-")).toHaveLength(
      choices.length,
    );
  });
});

describe("the rival the page sets beside the member", () => {
  const choose = (search: string, opponent: number | null = null, fallback: number | null = null) =>
    chooseRival({ search: new URLSearchParams(search), opponent, fallback, choices });

  it("is ?duel=, then the opponent, then ?rival=, then the default", () => {
    expect(choose("?duel=35249004&rival=35249005", 35249003, 35249002)).toBe(35249004);
    expect(choose("?rival=35249005", 35249003, 35249002)).toBe(35249003);
    expect(choose("?rival=35249005", null, 35249002)).toBe(35249005);
    expect(choose("", null, 35249002)).toBe(35249002);
  });

  it("passes over a number the page does not hold, the member and a malformed one", () => {
    expect(choose("?duel=99&rival=1e3", 12, 35249002)).toBe(35249002);
    expect(choose(`?duel=${SELF}`, null, null)).toBeNull();
    expect(choose("?duel=035249004", null, null)).toBeNull();
  });
});

const side = (entry: number | null, name: string) => ({
  entry,
  name,
  player_name: name,
  points: 0,
});
const match = (id: number, one: number | null, two: number | null): FplH2hMatch => ({
  id,
  entry_1: side(one, `Team ${one ?? "average"}`),
  entry_2: side(two, two === null ? "AVERAGE" : `Team ${two}`),
  winner: null,
  started: true,
  finished: false,
});
const page = (
  number: number,
  results: FplH2hMatch[],
  hasNext: boolean,
): ForwarderResult<FplH2hMatches, StandingsReason> => ({
  ok: true,
  copy: null,
  document: {
    contract_version: "fpl_h2h_matches_v1",
    league: { id: 4242, scoring: "h2h" },
    gameweek: 11,
    page: number,
    has_next: hasNext,
    source_time: "2026-11-21T12:00:00Z",
    results,
  },
});

describe("the live week's head-to-head opponent", () => {
  it("is found on either side of a pairing, on a later page", async () => {
    const read = vi.fn(async (number: number) =>
      number === 1 ? page(1, [match(1, 10, 11)], true) : page(2, [match(2, 12, 7001)], false),
    );
    await expect(h2hOpponent(read, 7001)).resolves.toEqual({ entryId: 12, name: "Team 12" });
    expect(read.mock.calls.map(([number]) => number)).toEqual([1, 2]);
  });

  it("is none for the league average or a bye", async () => {
    const read = async () => page(1, [match(1, 7001, null)], false);
    await expect(h2hOpponent(read, 7001)).resolves.toBeNull();
  });

  it("reads at most five pages and stops at a page the forwarder refuses", async () => {
    const endless = vi.fn(async (number: number) => page(number, [match(number, 1, 2)], true));
    await expect(h2hOpponent(endless, 7001)).resolves.toBeNull();
    expect(endless).toHaveBeenCalledTimes(H2H_PAGES);
    const refused = vi.fn(async (): Promise<ForwarderResult<FplH2hMatches, StandingsReason>> => ({
      ok: false,
      reason: "upstream_unavailable",
    }));
    await expect(h2hOpponent(refused, 7001)).resolves.toBeNull();
    expect(refused).toHaveBeenCalledTimes(1);
  });
});
