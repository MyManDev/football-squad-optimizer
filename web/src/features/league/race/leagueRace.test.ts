/**
 * The league race's places (#1135): one timeline with a rank change, ties sharing a place,
 * unsettled weeks left out, and the shipped tree's last settled week matching the league
 * table the tree publishes, place for place.
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
import { leagueRace, placesMoved } from "./leagueRace";

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
      const race = leagueRace(board, table.members);
      if (race === null || race.gameweeks[race.gameweeks.length - 1] !== table.scored_gameweek)
        return;
      for (const row of table.members.filter((item) => item.member_kind === "human")) {
        const line = race.lines.find((item) => item.entryId === row.entry_id)!;
        expect([row.entry_id, line.ranks[line.ranks.length - 1]]).toEqual([row.entry_id, row.rank]);
        expect(line.totals[line.totals.length - 1]).toBe(row.total_points);
      }
    });
  }
});
