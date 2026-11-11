import { describe, expect, it } from "vitest";

import { testPicks, testWeek, type TestPick } from "../../../testSupport/liveWeek";
import { scoreMemberWeek } from "../../liveScore/officialScoring";
import vectors from "../../liveScore/officialScoring.vectors.json";
import type { MemberWeek, WeekElement, WeekLive } from "../../liveScore/weekLive";
import { mockMembers } from "../../../fixtures/league";
import { liveBoard, pickMultiplier, type LiveBoard, type LiveRow } from "./liveBoard";
import { duelStatus, leagueTotalsBefore, liveDuel } from "./liveDuel";

type Vector = (typeof vectors.cases)[number];
type Week = WeekLive;
/** A vector's elements, each with its position and club, as the vectors state them. */
type Resolved = WeekElement & { club: number };

/**
 * A side of the duel as the official scorer scores it, in the board's shape: each pick's
 * points, and his multiplier by the board's own rule (`pickMultiplier`) from the scorer's
 * verdict.
 */
function scoredSide(week: Week, member: MemberWeek): LiveBoard | null {
  const score = scoreMemberWeek(week, member);
  if (score.refused) return null;
  const points = new Map(week.elements.map((element) => [element.element_id, element.points]));
  const rows = member.pick_order.map((elementId, index) => {
    const multiplier = pickMultiplier(
      elementId,
      new Set(score.counted),
      score.captain,
      member.active_chip,
    );
    return { elementId, pick: index + 1, points: points.get(elementId)!, multiplier };
  });
  return {
    net: score.net,
    transferCost: score.transfer_cost,
    left: 0,
    rows: rows as LiveRow[],
  } as LiveBoard;
}

/** Case `b`'s week moved beside case `a`'s: its ids, fixtures and clubs offset so none meet. */
function disjoint(a: Vector, b: Vector): { week: Week; member: MemberWeek; rival: MemberWeek } {
  const offset = (id: number) => id + 1000;
  const moved = b.input.members[0]! as MemberWeek;
  return {
    week: {
      ...(a.input as unknown as Week),
      fixtures: [
        ...a.input.fixtures,
        ...b.input.fixtures.map((fixture) => ({
          ...fixture,
          id: offset(fixture.id),
          home_club: offset(fixture.home_club),
          away_club: offset(fixture.away_club),
        })),
      ],
      elements: [
        ...(a.input.elements as Resolved[]),
        ...(b.input.elements as Resolved[]).map((element) => ({
          ...element,
          element_id: offset(element.element_id),
          club: offset(element.club),
        })),
      ],
    },
    member: a.input.members[0]! as MemberWeek,
    rival: {
      ...moved,
      pick_order: moved.pick_order.map(offset),
      captain: offset(moved.captain),
      vice: offset(moved.vice),
    },
  };
}

const pairs = vectors.cases.flatMap((a) => vectors.cases.map((b) => [a, b] as const));

/** Σ swing − (hit_member − hit_rival), which must be the margin. */
function swingTotal(member: LiveBoard, rival: LiveBoard): number {
  const duel = liveDuel(member, rival);
  const swings = [...duel.yours, ...duel.theirs].reduce((sum, swing) => sum + swing.swing, 0);
  return swings - (member.transferCost - rival.transferCost);
}

describe("the duel's invariant over the official scorer's vectors", () => {
  /** Every pair the scorer scores on both sides, and the pairs where the sums disagree. */
  function check(sides: (a: Vector, b: Vector) => [Week, MemberWeek, MemberWeek]) {
    let checked = 0;
    const broken: string[] = [];
    for (const [a, b] of pairs) {
      const [week, member, rival] = sides(a, b);
      const you = scoredSide(week, member);
      const them = scoredSide(week, rival);
      if (you === null || them === null) continue;
      checked += 1;
      if (swingTotal(you, them) !== you.net - them.net) {
        broken.push(`${a.name} against ${b.name}`);
      }
    }
    return { checked, broken };
  }

  it("holds for every pair with no player in common", () => {
    const { checked, broken } = check((a, b) => {
      const { week, member, rival } = disjoint(a, b);
      return [week, member, rival];
    });
    expect(broken).toEqual([]);
    // Only the vectors the scorer refuses (an unknown chip) sit out.
    expect(checked).toBe((vectors.cases.length - 1) ** 2);
  });

  it("holds for every pair on the same players, with the rival's armbands swapped", () => {
    const { checked, broken } = check((a, b) => {
      const other = b.input.members[0]! as MemberWeek;
      return [
        a.input as unknown as Week,
        a.input.members[0]! as MemberWeek,
        { ...other, captain: other.vice, vice: other.captain },
      ];
    });
    expect(broken).toEqual([]);
    expect(checked).toBe((vectors.cases.length - 1) ** 2);
  });
});

/** The member's board and a rival's from the same synthetic read. */
function sides(
  changes: Record<number, Partial<TestPick>>,
  rival: Partial<MemberWeek>,
  member: Partial<MemberWeek> = {},
): [LiveBoard, LiveBoard] {
  const picks = testPicks().map((pick) => ({ ...pick, ...changes[pick.id] }));
  const fixtures = [
    { id: 101, home: 1, away: 2, kickoff: "2026-11-21T12:30:00Z", finished: true },
    { id: 102, home: 3, away: 4, kickoff: "2026-11-21T15:00:00Z", finished: true },
    { id: 103, home: 5, away: 6, kickoff: "2026-11-21T17:30:00Z", finished: false },
  ];
  const input = testWeek({ picks, fixtures, member });
  const theirs = testWeek({ picks, fixtures, member: { entry_id: 202, ...rival } });
  return [liveBoard(input)!, liveBoard(theirs)!];
}

const played = Object.fromEntries(
  [1, 2, 3, 4, 5, 6, 7, 8, 10, 11].map((id) => [id, { points: 2, minutes: 90 }]),
);

describe("the duel of two boards of one read", () => {
  it("is the captain alone where only the armbands differ", () => {
    const [member, rival] = sides(
      { ...played, 10: { points: 9, minutes: 90 } },
      { captain: 7, vice: 10 },
    );
    const duel = liveDuel(member, rival);
    // Double the forward against double the midfielder: 9 against 2.
    expect(duel.yours.map((swing) => [swing.elementId, swing.swing])).toEqual([[10, 9]]);
    expect(duel.theirs.map((swing) => [swing.elementId, swing.swing])).toEqual([[7, -2]]);
    expect(duel).toMatchObject({ margin: 7, status: "ahead", shared: 13 });
  });

  it("takes three of the triple captain", () => {
    const [member, rival] = sides(
      { ...played, 10: { points: 5, minutes: 90 } },
      {},
      { active_chip: "3xc" },
    );
    const duel = liveDuel(member, rival);
    expect(duel.yours).toMatchObject([{ elementId: 10, member: 3, rival: 2, swing: 5 }]);
    expect(duel.margin).toBe(5);
  });

  it("counts the bench of a bench boost against a bench that does not count", () => {
    const [member, rival] = sides(
      { ...played, 12: { points: 1, minutes: 90 }, 13: { points: 3, minutes: 90 } },
      {},
      { active_chip: "bboost" },
    );
    const duel = liveDuel(member, rival);
    expect(duel.yours.map((swing) => [swing.elementId, swing.swing])).toEqual([
      [13, 3],
      [12, 1],
      [14, 0],
      [15, 0],
    ]);
    expect(duel.margin).toBe(4);
  });

  it("follows an automatic substitution that changes a multiplier", () => {
    // The rival starts the reserve forward over the forward who did not play.
    const order = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 12, 13, 14, 11];
    const [member, rival] = sides(
      { ...played, 11: { points: 0, minutes: 0 }, 13: { points: 6, minutes: 90 } },
      { pick_order: order },
    );
    // The member's defender comes on for the forward; the rival's bench stays out.
    expect(member.rows.find((row) => row.elementId === 13)?.autosub).toBe("in");
    const duel = liveDuel(member, rival);
    expect(duel.yours.map((swing) => swing.elementId)).toContain(13);
    expect(swingTotal(member, rival)).toBe(member.net - rival.net);
  });

  it("is level, ahead or behind from the two nets", () => {
    expect([duelStatus(3), duelStatus(0), duelStatus(-2)]).toEqual(["ahead", "level", "behind"]);
  });

  it("gives the total gap from the totals before the week and both live nets", () => {
    const [member, rival] = sides(
      { ...played, 10: { points: 9, minutes: 90 } },
      { captain: 7, vice: 10 },
    );
    expect(liveDuel(member, rival, { member: 500, rival: 520 }).totalGap).toBe(
      500 + member.net - (520 + rival.net),
    );
    expect(liveDuel(member, rival).totalGap).toBeNull();
  });
});

describe("two members' league totals before the live week", () => {
  // North Stand Notes: 132 in all, 74 that week with no hit; Half Space: 127, 68 and a hit of 4.
  const table = (scored: number | null) => ({
    scored_gameweek: scored,
    members: mockMembers.map((member) =>
      member.entry_id === 35249002 ? { ...member, transfer_cost: 4 } : member,
    ),
  });

  it("are the table's totals where it was scored through the week before", () => {
    expect(leagueTotalsBefore(table(9), 10, 35249001, 35249002)).toEqual({
      member: 132,
      rival: 127,
    });
  });

  it("are the table's totals less the week's own net where it was scored through the week", () => {
    expect(leagueTotalsBefore(table(10), 10, 35249001, 35249002)).toEqual({
      member: 132 - 74,
      rival: 127 - (68 - 4),
    });
  });

  it("are none from a table scored through another week, or from none at all", () => {
    expect(leagueTotalsBefore(table(8), 10, 35249001, 35249002)).toBeNull();
    // A forwarded league's table: FPL updates it while the week is played.
    expect(leagueTotalsBefore(table(null), 10, 35249001, 35249002)).toBeNull();
    expect(leagueTotalsBefore(null, 10, 35249001, 35249002)).toBeNull();
  });

  it("are none for a member the table has no total or week for", () => {
    expect(leagueTotalsBefore(table(9), 10, 35249001, 99)).toBeNull();
    const unscored = {
      scored_gameweek: 10,
      members: mockMembers.map((member) => ({ ...member, gameweek_points: null })),
    };
    expect(leagueTotalsBefore(unscored, 10, 35249001, 35249002)).toBeNull();
  });
});
