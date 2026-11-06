/**
 * The league race's places (#1135): one timeline with a rank change, ties sharing a place,
 * unsettled weeks left out, each member's points to the neighbours on the latest settled
 * week's totals, and the shipped tree's last settled week matching the league table the
 * tree publishes, place for place and gap for gap.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { shippedTrees } from "../../../testSupport/shippedTrees";
import {
  RACE_SYSTEM,
  raceMember,
  raceScoreboard,
  raceWeek,
} from "../../../testSupport/raceScoreboard";
import type { LeagueMembers, LeagueViewEnvelope, Scoreboard } from "../types";
import { leagueRace, neighbourGaps, placesMoved } from "./leagueRace";

const MEMBERS = [raceMember(11), raceMember(22), raceMember(33), RACE_SYSTEM];

describe("the league race", () => {
  it("places each member by the week's total and marks the week a place changed hands", () => {
    // Week 2: 22 overtakes 11. Week 3 is not settled and is left out.
    const race = leagueRace(
      raceScoreboard([
        raceWeek(1, { 11: 70, 22: 60, 33: 50 }),
        raceWeek(2, { 11: 120, 22: 125, 33: 90 }),
        raceWeek(3, { 11: 200, 22: 130, 33: 100 }, false),
      ]),
      MEMBERS,
    )!;
    expect(race.gameweeks).toEqual([1, 2]);
    expect(race.lines.map((line) => line.entryId)).toEqual([22, 11, 33]);
    const byId = new Map(race.lines.map((line) => [line.entryId, line]));
    expect(byId.get(22)!.ranks).toEqual([2, 1]);
    expect(byId.get(11)!.ranks).toEqual([1, 2]);
    expect(byId.get(33)!.ranks).toEqual([3, 3]);
    expect(byId.get(22)!.totals).toEqual([60, 125]);
    expect(placesMoved(byId.get(22)!, 1)).toBe(1);
    expect(placesMoved(byId.get(11)!, 1)).toBe(-1);
    expect(placesMoved(byId.get(33)!, 1)).toBe(0);
    expect(placesMoved(byId.get(22)!, 0)).toBeNull();
    expect(race.places).toBe(3);
  });

  it("lets an equal total share the place, the next one counting the members ahead", () => {
    const race = leagueRace(
      raceScoreboard([
        raceWeek(1, { 11: 70, 22: 70, 33: 50 }),
        raceWeek(2, { 11: 90, 22: 80, 33: 80 }),
      ]),
      MEMBERS,
    )!;
    const byId = new Map(race.lines.map((line) => [line.entryId, line.ranks]));
    expect(byId.get(11)).toEqual([1, 1]);
    expect(byId.get(22)).toEqual([1, 2]);
    expect(byId.get(33)).toEqual([3, 2]);
  });

  it("takes the table's places where it publishes them, so a tie reads as the table breaks it", () => {
    // Week 2: 11 and 22 are level on 120; the table, from the standings, puts 11 first.
    // Week 1: 22 and 33 are level on 60; the table's movement puts 33 second and 22 third.
    const table = [
      { ...raceMember(11), rank: 1, movement: "same" as const, movement_places: 0 },
      { ...raceMember(22), rank: 2, movement: "up" as const, movement_places: 1 },
      { ...raceMember(33), rank: 3, movement: "down" as const, movement_places: 1 },
      RACE_SYSTEM,
    ];
    const board = raceScoreboard([
      raceWeek(1, { 11: 70, 22: 60, 33: 60 }),
      raceWeek(2, { 11: 120, 22: 120, 33: 90 }),
    ]);
    const race = leagueRace(board, table, 2)!;
    const byId = new Map(race.lines.map((line) => [line.entryId, line.ranks]));
    expect(byId.get(11)).toEqual([1, 1]);
    expect(byId.get(22)).toEqual([3, 2]);
    expect(byId.get(33)).toEqual([2, 3]);
    // Without the table's scored week the totals alone decide, and the ties share.
    const alone = new Map(
      leagueRace(board, table)!.lines.map((line) => [line.entryId, line.ranks]),
    );
    expect(alone.get(22)).toEqual([2, 1]);
    expect(alone.get(33)).toEqual([2, 3]);
  });

  it("keeps a member who did not move in the place the table gives it the week before", () => {
    // Week 1: 22 and 33 are level on 60. None of the three moved, so the table's places for
    // week 1 are its places for week 2, and 33 is third in both, not level second.
    const table = [
      { ...raceMember(11), rank: 1, movement: "same" as const, movement_places: 0 },
      { ...raceMember(22), rank: 2, movement: "same" as const, movement_places: 0 },
      { ...raceMember(33), rank: 3, movement: "same" as const, movement_places: 0 },
      RACE_SYSTEM,
    ];
    const race = leagueRace(
      raceScoreboard([
        raceWeek(1, { 11: 70, 22: 60, 33: 60 }),
        raceWeek(2, { 11: 120, 22: 110, 33: 90 }),
      ]),
      table,
      2,
    )!;
    const byId = new Map(race.lines.map((line) => [line.entryId, line.ranks]));
    expect(byId.get(11)).toEqual([1, 1]);
    expect(byId.get(22)).toEqual([2, 2]);
    expect(byId.get(33)).toEqual([3, 3]);
  });

  it("keeps the shared place for a week the table's movement cannot reach", () => {
    const table = [
      { ...raceMember(11), rank: 1, movement: "unknown" as const, movement_places: null },
      { ...raceMember(22), rank: 2, movement: "new" as const, movement_places: null },
      RACE_SYSTEM,
    ];
    const race = leagueRace(
      raceScoreboard([raceWeek(1, { 11: 60, 22: 60 }), raceWeek(2, { 11: 120, 22: 120 })]),
      table,
      2,
    )!;
    const byId = new Map(race.lines.map((line) => [line.entryId, line.ranks]));
    expect(byId.get(11)).toEqual([1, 1]);
    expect(byId.get(22)).toEqual([1, 2]);
  });

  it("leaves a member out of a week the scoreboard has no row for", () => {
    const race = leagueRace(
      raceScoreboard([raceWeek(1, { 11: 70, 22: 60 }), raceWeek(2, { 11: 90, 22: 95, 33: 10 })]),
      MEMBERS,
    )!;
    expect(race.lines.find((line) => line.entryId === 33)!.ranks).toEqual([null, 3]);
    expect(
      placesMoved(
        race.lines.find((line) => line.entryId === 33)!,
        1,
      ),
    ).toBeNull();
  });

  it("draws no race without two settled weeks", () => {
    expect(leagueRace(raceScoreboard([raceWeek(1, { 11: 70 })]), MEMBERS)).toBeNull();
    expect(
      leagueRace(
        raceScoreboard([raceWeek(1, { 11: 70 }), raceWeek(2, { 11: 90 }, false)]),
        MEMBERS,
      ),
    ).toBeNull();
  });
});

describe("the gaps to the neighbours", () => {
  const gaps = (race: ReturnType<typeof leagueRace>) =>
    neighbourGaps(race!).map(({ entryId, place, total, ahead, behind }) => [
      entryId,
      place,
      total,
      ahead,
      behind,
    ]);

  it("measures each member against the one just ahead and just behind on the latest settled week", () => {
    // Week 3 is not settled, so week 2's totals are the ones measured.
    const race = leagueRace(
      raceScoreboard([
        raceWeek(1, { 11: 70, 22: 60, 33: 50 }),
        raceWeek(2, { 11: 120, 22: 125, 33: 90 }),
        raceWeek(3, { 11: 200, 22: 130, 33: 100 }, false),
      ]),
      MEMBERS,
    );
    expect(gaps(race)).toEqual([
      [22, 1, 125, null, 5],
      [11, 2, 120, 5, 30],
      [33, 3, 90, 30, null],
    ]);
  });

  it("reads equal totals as a gap of 0, and leaves out a member without a total that week", () => {
    const race = leagueRace(
      raceScoreboard([
        raceWeek(1, { 11: 70, 22: 60, 33: 50, 44: 40 }),
        raceWeek(2, { 11: 90, 22: 80, 33: 80 }),
      ]),
      [...MEMBERS, raceMember(44)],
    );
    expect(gaps(race)).toEqual([
      [11, 1, 90, null, 10],
      [22, 2, 80, 10, 0],
      [33, 2, 80, 0, null],
    ]);
  });

  it("states no gap where the table's places put a higher total behind", () => {
    const table = [
      { ...raceMember(11), rank: 1, movement: "same" as const, movement_places: 0 },
      { ...raceMember(22), rank: 2, movement: "same" as const, movement_places: 0 },
      RACE_SYSTEM,
    ];
    const race = leagueRace(
      raceScoreboard([raceWeek(1, { 11: 60, 22: 50 }), raceWeek(2, { 11: 100, 22: 110 })]),
      table,
      2,
    );
    expect(gaps(race)).toEqual([
      [11, 1, 100, null, null],
      [22, 2, 110, null, null],
    ]);
  });
});

describe("the shipped trees", () => {
  for (const { path, root } of shippedTrees()) {
    const scoreboardPath = join(root, "scoreboard.json");
    it(`${path}: the last settled week's places are the published table's`, () => {
      if (!existsSync(scoreboardPath)) return;
      const board = (
        JSON.parse(readFileSync(scoreboardPath, "utf-8")) as LeagueViewEnvelope<Scoreboard>
      ).payload;
      const table = (
        JSON.parse(
          readFileSync(join(root, "members.json"), "utf-8"),
        ) as LeagueViewEnvelope<LeagueMembers>
      ).payload;
      const race = leagueRace(board, table.members, table.scored_gameweek);
      if (race === null || race.gameweeks[race.gameweeks.length - 1] !== table.scored_gameweek)
        return;
      for (const row of table.members.filter((item) => item.member_kind === "human")) {
        const line = race.lines.find((item) => item.entryId === row.entry_id)!;
        expect([row.entry_id, line.ranks[line.ranks.length - 1]]).toEqual([row.entry_id, row.rank]);
        expect(line.totals[line.totals.length - 1]).toBe(row.total_points);
      }
      // Each gap is the difference of the two totals the table publishes for the neighbours.
      const totals = new Map(table.members.map((row) => [row.entry_id, row.total_points]));
      const gaps = neighbourGaps(race);
      gaps.forEach((gap, index) => {
        expect(gap.total).toBe(totals.get(gap.entryId));
        const next = gaps[index + 1];
        if (next) expect(gap.behind).toBe(totals.get(gap.entryId)! - totals.get(next.entryId)!);
      });
    });
  }
});
