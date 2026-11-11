import { afterEach, describe, expect, it, vi } from "vitest";

import {
  testActivity,
  testFixtures,
  testPicks,
  testWeek,
  type TestFixture,
  type TestPick,
} from "../../../testSupport/liveWeek";
import { MATCH_WINDOW_MS } from "../../liveScore/liveWindow";
import type { MemberWeek } from "../../liveScore/weekLive";
import {
  advanceRecap,
  appearancePoints,
  liveBoard,
  lookedAt,
  RECAP_ROWS,
  recapItems,
  rowPoints,
  stateOf,
  type LiveBoard,
  type LiveRecap,
} from "./liveBoard";

afterEach(() => vi.useRealTimers());

/** The picks with `changes` made to some of them by id. */
function picksWith(changes: Record<number, Partial<TestPick>>): TestPick[] {
  return testPicks().map((pick) => ({ ...pick, ...changes[pick.id] }));
}

function fixturesWith(changes: Record<number, Partial<TestFixture>>): TestFixture[] {
  return testFixtures().map((fixture) => ({ ...fixture, ...changes[fixture.id] }));
}

function board(...args: Parameters<typeof testWeek>): LiveBoard {
  const built = liveBoard(testWeek(...args));
  if (built === null) throw new Error("the synthetic week did not score");
  return built;
}

const row = (built: LiveBoard, id: number) => built.rows.find((item) => item.elementId === id)!;

// Every match over, so each state below is read at full time.
const OVER = fixturesWith({ 101: { finished: true }, 102: { finished: true } });

describe("a pick's appearance points", () => {
  it("are none without minutes, one under sixty and two from sixty", () => {
    expect([0, 1, 59, 60, 90].map(appearancePoints)).toEqual([0, 1, 1, 2, 2]);
  });

  it("make a state of one or more up, minus one or less down, and none neutral", () => {
    expect([2, 1, 0, -1, -3].map(stateOf)).toEqual(["up", "up", "neutral", "down", "down"]);
  });
});

describe("the state of each position, from FPL's own points", () => {
  it.each([
    ["a defender on 9 points over 90 minutes", 3, { points: 9, minutes: 90 }, 7, "up"],
    ["a keeper with two conceded and six saves", 1, { points: 3, minutes: 90 }, 1, "up"],
    [
      "a midfielder off at 45 with a yellow card",
      6,
      { points: 0, minutes: 45, card: true },
      -1,
      "down",
    ],
    ["a forward's 90-minute blank", 10, { points: 2, minutes: 90 }, 0, "neutral"],
    ["a card from the bench", 7, { points: -1, minutes: 0, card: true }, -1, "down"],
  ] as const)("%s", (_name, id, change, net, state) => {
    const built = board({ picks: picksWith({ [id]: change }), fixtures: OVER });
    expect(row(built, id)).toMatchObject({ net, state });
  });

  it("follows a defender's clean sheet and the two goals against it", () => {
    const at = (points: number) =>
      row(board({ picks: picksWith({ 2: { points, minutes: 75 } }), fixtures: OVER }), 2);
    expect([at(6), at(2), at(1)].map((pick) => [pick.net, pick.state])).toEqual([
      [4, "up"],
      [0, "neutral"],
      [-1, "down"],
    ]);
  });

  it("draws no state for a pick who has not played and has nothing against him", () => {
    const built = board({ fixtures: OVER });
    expect(row(built, 5)).toMatchObject({ minutes: 0, net: null, state: null });
  });

  it("draws no state before his match has kicked off", () => {
    const built = board({ picks: picksWith({ 9: { points: 0, minutes: 0 } }) });
    expect(row(built, 9)).toMatchObject({ phase: "upcoming", started: false, state: null });
  });
});

describe("a double week", () => {
  const fixtures = [
    ...testFixtures(),
    { id: 104, home: 1, away: 5, kickoff: "2026-11-22T14:00:00Z", finished: true },
  ].map((fixture) => ({ ...fixture, finished: true }));
  const picks = picksWith({ 2: { points: 6, minutes: 140 } });

  it("takes each fixture's minutes from the read's detail: 70 and 70 is four", () => {
    const input = testWeek({ picks, fixtures, sourceTime: "2026-11-22T18:00:00Z" });
    const activity = testActivity(input, { minutes: { 2: { 101: 70, 104: 70 } } });
    const built = liveBoard({ ...input, activity })!;
    expect(row(built, 2)).toMatchObject({ net: 2, state: "up" });
    expect(row(built, 2).fixtures.map((fixture) => fixture.minutes)).toEqual([70, 70]);
  });

  it("draws no state where the read has no detail", () => {
    const built = board({ picks, fixtures, sourceTime: "2026-11-22T18:00:00Z" });
    expect(row(built, 2)).toMatchObject({ net: null, state: null, points: 6 });
  });

  it("stands in the group of the fixture still to come", () => {
    const later = fixtures.map((fixture) =>
      fixture.id === 104 ? { ...fixture, finished: false } : fixture,
    );
    const built = board({ picks, fixtures: later, sourceTime: "2026-11-21T20:00:00Z" });
    expect(row(built, 2)).toMatchObject({ group: "upcoming", started: true });
    expect(row(built, 2).fixture?.id).toBe(104);
  });
});

describe("the phases at the read's source time", () => {
  it("puts each of the eleven by its match and the bench apart", () => {
    const input = testWeek({ fixtures: fixturesWith({ 101: { finished: true } }) });
    const built = liveBoard({ ...input, activity: testActivity(input, { inPlay: [102] }) })!;
    expect(built.groups.finished.map((pick) => pick.elementId)).toEqual([10, 1, 2, 3, 6, 7]);
    expect(built.groups.playing.map((pick) => pick.elementId)).toEqual([4, 5, 8, 11]);
    expect(built.groups.upcoming.map((pick) => pick.elementId)).toEqual([9]);
    expect(built.groups.bench.map((pick) => pick.elementId)).toEqual([12, 13, 14, 15]);
    expect(built).toMatchObject({ matchesOver: 1, matchesTotal: 3, inPlay: true });
  });

  it("calls a match played from its kickoff where the read has no detail", () => {
    const built = board();
    expect(built.groups.playing.map((pick) => pick.elementId)).toEqual([4, 5, 8, 11]);
    expect(row(built, 1).phase).toBe("finished");
    expect(built.matchesOver).toBe(1);
  });

  it("follows FPL's in-play list where the read has detail", () => {
    const input = testWeek();
    const built = liveBoard({ ...input, activity: testActivity(input, { inPlay: [] }) })!;
    expect(row(built, 4).phase).toBe("upcoming");
    expect(row(built, 1).phase).toBe("finished");
  });

  it("calls a match over past its window, though FPL has not finished it", () => {
    const kickoff = Date.parse("2026-11-21T15:00:00Z");
    const before = new Date(kickoff + MATCH_WINDOW_MS - 60_000).toISOString();
    const after = new Date(kickoff + MATCH_WINDOW_MS).toISOString();
    expect(row(board({ sourceTime: before }), 4).phase).toBe("playing");
    const past = board({ sourceTime: after });
    expect(row(past, 4).phase).toBe("finished");
    expect(past.inPlay).toBe(false);
    expect(past.final).toBe(false);
  });

  it("never moves a group with the clock, only with a read", () => {
    const input = testWeek();
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse("2026-11-21T15:30:00Z"));
    const first = liveBoard(input)!;
    vi.setSystemTime(Date.parse("2026-11-23T10:00:00Z"));
    expect(liveBoard(input)!.groups).toEqual(first.groups);
  });

  it("names the opponent and the kickoff of the current fixture", () => {
    const built = board({ sourceTime: "2026-11-21T09:00:00Z" });
    expect(row(built, 4).fixture).toMatchObject({
      opponent: "C4",
      kickoff: "2026-11-21T15:00:00Z",
      phase: "upcoming",
    });
    expect(row(built, 5).fixture?.opponent).toBe("C3");
    expect(row(built, 4).code).toBe("C3");
  });
});

describe("the facts that are neither up nor down", () => {
  it("says Oynamadı only once the club's match is finished", () => {
    expect(row(board(), 5).fact).toBeNull();
    expect(row(board({ fixtures: OVER }), 5).fact).toBe("didNotPlay");
    // A card is a part in the match.
    const carded = board({ fixtures: OVER, picks: picksWith({ 5: { card: true, points: -1 } }) });
    expect(row(carded, 5).fact).toBeNull();
  });

  it("says Maç yok for a club with no fixture this week", () => {
    const built = board({ picks: picksWith({ 12: { club: 7 } }) });
    expect(row(built, 12)).toMatchObject({
      fact: "noMatch",
      phase: null,
      fixture: null,
      started: false,
    });
  });
});

describe("what the official scorer counts", () => {
  it("doubles the captain, counts the eleven and leaves the bench out", () => {
    const picks = picksWith({ 10: { points: 5, minutes: 90 }, 7: { points: 2, minutes: 90 } });
    const built = board({ picks, fixtures: OVER });
    expect(row(built, 10)).toMatchObject({ armband: "captain", multiplier: 2, counted: true });
    expect(rowPoints(row(built, 10))).toBe(10);
    expect(row(built, 7)).toMatchObject({ armband: "vice", multiplier: 1 });
    expect(row(built, 13)).toMatchObject({ counted: false, multiplier: 0 });
  });

  it("passes the armband to the vice, with the triple captain's three", () => {
    const picks = picksWith({ 10: { minutes: 0 }, 7: { points: 4, minutes: 90 } });
    const built = board({ picks, fixtures: OVER, member: { active_chip: "3xc" } });
    expect(built.captain).toBe(7);
    expect(row(built, 7)).toMatchObject({ armband: "captain", multiplier: 3 });
    expect(row(built, 10).armband).toBeNull();
  });

  it("marks an automatic substitution on both rows once the club is finished", () => {
    // Every other starter played, so the forward is the one the reserve replaces.
    const played = Object.fromEntries(
      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((id) => [id, { points: 2, minutes: 90 }]),
    );
    const picks = picksWith({ ...played, 11: { minutes: 0 }, 13: { points: 2, minutes: 90 } });
    const built = board({ picks, fixtures: OVER });
    expect(row(built, 11)).toMatchObject({ autosub: "out", counted: false });
    expect(row(built, 13)).toMatchObject({ autosub: "in", counted: true, group: "bench" });
  });

  it("counts the bench under the bench boost", () => {
    const built = board({ member: { active_chip: "bboost" } });
    expect(built.rows.every((pick) => pick.counted)).toBe(true);
    expect(built.chip).toBe("bboost");
  });

  it("counts the states of counted picks and the picks still to finish", () => {
    const picks = picksWith({
      1: { points: 8, minutes: 90 },
      3: { points: 0, minutes: 90 },
      14: { club: 3, points: -1, card: true },
    });
    const built = board({ picks, fixtures: fixturesWith({ 101: { finished: true } }) });
    // The keeper is up and the defender down; the reserve's card is his own, not the team's.
    expect(row(built, 14).state).toBe("down");
    expect([built.doingWell, built.struggling]).toEqual([1, 1]);
    // The eleven with a match still to finish: four playing and one to play.
    expect(built.left).toBe(5);
  });

  it("is final once FPL has finished every fixture, and its net takes the hit", () => {
    const fixtures = testFixtures().map((fixture) => ({ ...fixture, finished: true }));
    const picks = picksWith({ 1: { points: 6, minutes: 90 } });
    const built = board({ picks, fixtures, member: { transfer_cost: 4 } });
    expect(built).toMatchObject({ final: true, gross: 6, net: 2, transferCost: 4 });
    expect(built.matchesOver).toBe(3);
  });
});

describe("Son bakıştan beri", () => {
  /** A read at `minute` past 15:29 with the picks changed, its goals and assists as given. */
  function read(
    minute: number,
    changes: Record<number, Partial<TestPick>> = {},
    {
      member = {},
      fixtures = testFixtures(),
      goals = {},
      assists = {},
      detail = true,
    }: {
      member?: Partial<MemberWeek>;
      fixtures?: TestFixture[];
      goals?: Record<number, number>;
      assists?: Record<number, number>;
      detail?: boolean;
    } = {},
  ): LiveBoard {
    const sourceTime = new Date(Date.parse("2026-11-21T15:29:00Z") + minute * 60_000).toISOString();
    const input = testWeek({ sourceTime, picks: picksWith(changes), fixtures, member });
    const activity = detail ? testActivity(input, { inPlay: [102, 103], goals, assists }) : null;
    return liveBoard({ ...input, activity })!;
  }

  /** The recap after `boards` in turn. */
  const recapOf = (...boards: LiveBoard[]) =>
    boards.reduce<LiveRecap | null>((recap, board) => advanceRecap(recap, board), null);

  it("tells what the member's score takes: the captain's goal counts twice", () => {
    const member = { captain: 4, vice: 7 };
    const recap = recapOf(
      read(1, { 4: { points: 1, minutes: 40 } }, { member }),
      read(2, { 4: { points: 7, minutes: 41 } }, { member, goals: { 4: 1 } }),
    );
    expect(recapItems(recap)).toEqual([
      { elementId: 4, name: "P4", goals: 1, assists: 0, card: false, change: 12 },
    ]);
  });

  it("tells nothing of a reserve the score does not count, goal or clean sheet", () => {
    const recap = recapOf(
      read(1, { 13: { points: 1, minutes: 30 } }),
      read(2, { 13: { points: 7, minutes: 31 } }, { goals: { 13: 1 } }),
      read(3, { 13: { points: 11, minutes: 60 } }, { goals: { 13: 1 } }),
    );
    expect(recapItems(recap)).toEqual([]);
  });

  it("tells a reserve's goal under the bench boost", () => {
    const member = { active_chip: "bboost" as const };
    const recap = recapOf(
      read(1, { 13: { points: 1, minutes: 30 } }, { member }),
      read(2, { 13: { points: 7, minutes: 31 } }, { member, goals: { 13: 1 } }),
    );
    expect(recapItems(recap)).toEqual([
      { elementId: 13, name: "P13", goals: 1, assists: 0, card: false, change: 6 },
    ]);
  });

  it("adds the points of a reserve the read brings on", () => {
    // Every starter but the forward has played; the defender on the bench scored.
    const played = Object.fromEntries(
      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((id) => [id, { points: 2, minutes: 90 }]),
    );
    const changes = { ...played, 11: { minutes: 0 }, 13: { points: 7, minutes: 90 } };
    const over = (finished: boolean) =>
      testFixtures().map((fixture) => ({
        ...fixture,
        finished: fixture.id === 101 || (fixture.id === 102 && finished),
      }));
    const before = read(1, changes, { fixtures: over(false), goals: { 13: 1 } });
    const after = read(2, changes, { fixtures: over(true), goals: { 13: 1 } });
    expect(after.rows.find((row) => row.elementId === 13)?.autosub).toBe("in");
    // His goal was not the member's when he scored it; his points are once he comes on.
    expect(recapItems(recapOf(before, after))).toEqual([
      { elementId: 13, name: "P13", goals: 0, assists: 0, card: false, change: 7 },
    ]);
  });

  it("tells no old goal again after a read without event detail", () => {
    const scored = { 4: { points: 7, minutes: 40 } };
    const recap = recapOf(
      read(1, scored, { goals: { 4: 1 } }),
      read(2, scored, { detail: false }),
      read(3, scored, { goals: { 4: 1 } }),
    );
    expect(recapItems(recap)).toEqual([]);
  });

  it("holds what each read brought until the visitor looks again", () => {
    const first = read(1, { 4: { points: 1, minutes: 40 } });
    const goal = read(2, { 4: { points: 7, minutes: 41 } }, { goals: { 4: 1 } });
    const quiet = read(3, { 4: { points: 7, minutes: 42 } }, { goals: { 4: 1 } });
    const card = read(
      4,
      { 4: { points: 7, minutes: 43 }, 6: { points: -1, minutes: 30, card: true } },
      { goals: { 4: 1 } },
    );
    const held = recapOf(first, goal, quiet, card);
    expect(recapItems(held)).toEqual([
      { elementId: 4, name: "P4", goals: 1, assists: 0, card: false, change: 6 },
      { elementId: 6, name: "P6", goals: 0, assists: 0, card: true, change: -1 },
    ]);
    // Once looked at, only what a later read brings is told.
    const assist = read(
      5,
      { 4: { points: 10, minutes: 44 }, 6: { points: -1, minutes: 31, card: true } },
      { goals: { 4: 1 }, assists: { 4: 1 } },
    );
    expect(recapItems(advanceRecap(lookedAt(held), assist))).toEqual([
      { elementId: 4, name: "P4", goals: 0, assists: 1, card: false, change: 3 },
    ]);
  });

  it("starts at the first read and takes no read again, nor an older one", () => {
    const first = read(1, { 4: { points: 1, minutes: 40 } });
    const later = read(2, { 4: { points: 7, minutes: 41 } }, { goals: { 4: 1 } });
    expect(recapItems(recapOf(first))).toEqual([]);
    const recap = recapOf(first, later);
    expect(advanceRecap(recap, later)).toBe(recap);
    expect(advanceRecap(recap, first)).toBe(recap);
  });

  it("shows at most six rows, the biggest change first", () => {
    const changes = Object.fromEntries(
      [1, 2, 3, 4, 5, 6, 7, 8].map((id) => [id, { points: id, minutes: 30 }]),
    );
    const recap = recapItems(recapOf(read(1), read(2, changes)));
    expect(recap).toHaveLength(RECAP_ROWS);
    expect(recap.map((item) => item.elementId)).toEqual([8, 7, 6, 5, 4, 3]);
  });
});
