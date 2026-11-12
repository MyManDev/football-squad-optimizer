/**
 * Saturday of the synthetic GW10 week (`liveWeek.ts`) told as eight reads, one per Yenile, for
 * the tests of how LIVE moves when a read brings a change. Never a member capture.
 *
 * The member's fifteen are `testPicks()`: the captain is 10 and the vice 7, both of club 2.
 *
 * 1. 12:00, before the kickoffs: the first read, a starting point.
 * 2. 12:45, the 12:30 match (101, clubs 1 and 2) under way: six picks kick off.
 * 3. 13:00, the captain scores (a forward's 4, twice) and the vice assists (3).
 * 4. 13:10, a card to a defender (2): his point goes.
 * 5. 14:50, 101 past its window, FPL not yet finished: its bonus is still to come; club 2 kept
 *    its goal unconceded.
 * 6. 15:30, 101 finished with its bonus, and the 15:00 match (102, clubs 3 and 4) under way:
 *    seven counted picks' points change at once, and an eighth pick changes group.
 * 7. 17:00, 102 finished; the forward 11 never played.
 * 8. 19:45, the week final: 103 played, and 11 gives way to the first reserve, 13.
 *
 * The points follow the 2026-27 rules the board's moments use (a forward's goal 4, an assist 3,
 * a card -1, a defender's unconceded match 4 and a midfielder's 1, appearance 1 then 2), so
 * Canlı puan after a read's moments land is the read's own total.
 */

import type { WeekActivity } from "../features/liveScore/weekActivity";
import type { LiveBoardInput } from "../features/league/live/liveBoard";
import { testActivity, testFixtures, testPicks, testWeek, type TestPick } from "./liveWeek";

export type BeatMoment = "goal" | "assist" | "card" | "substitution";

export type BeatName =
  "before" | "kickoff" | "goal" | "card" | "over" | "bonus" | "second" | "final";

export interface LiveBeat {
  name: BeatName;
  /** The read's source time. */
  at: string;
  /** What the GOL board raises for the read, in order. */
  moments: readonly BeatMoment[];
  /** The live document as the forwarder answers it. */
  document: WeekActivity;
  /** Every input of `liveBoard` for the read, for tests that score it directly. */
  input: LiveBoardInput;
}

/** A pick as one read says him: minutes, points, a card, goals and assists. */
interface Said {
  minutes: number;
  points: number;
  card?: boolean;
  goals?: number;
  assists?: number;
}

interface BeatPlan {
  name: BeatName;
  at: string;
  moments: readonly BeatMoment[];
  inPlay: number[];
  finished: number[];
  /** The picks this read says something new of; the rest stay as the read before said. */
  said: Record<number, Said>;
}

const KICKED_OFF = { minutes: 15, points: 1 };

const PLANS: readonly BeatPlan[] = [
  { name: "before", at: "2026-11-21T12:00:00Z", moments: [], inPlay: [], finished: [], said: {} },
  {
    name: "kickoff",
    at: "2026-11-21T12:45:00Z",
    moments: [],
    inPlay: [101],
    finished: [],
    said: {
      1: KICKED_OFF,
      2: KICKED_OFF,
      3: KICKED_OFF,
      6: KICKED_OFF,
      7: KICKED_OFF,
      10: KICKED_OFF,
    },
  },
  {
    name: "goal",
    at: "2026-11-21T13:00:00Z",
    moments: ["goal", "assist"],
    inPlay: [101],
    finished: [],
    said: {
      1: { minutes: 30, points: 1 },
      2: { minutes: 30, points: 1 },
      3: { minutes: 30, points: 1 },
      6: { minutes: 30, points: 1 },
      7: { minutes: 30, points: 4, assists: 1 },
      10: { minutes: 30, points: 5, goals: 1 },
    },
  },
  {
    name: "card",
    at: "2026-11-21T13:10:00Z",
    moments: ["card"],
    inPlay: [101],
    finished: [],
    said: {
      1: { minutes: 40, points: 1 },
      2: { minutes: 40, points: 0, card: true },
      3: { minutes: 40, points: 1 },
      6: { minutes: 40, points: 1 },
      7: { minutes: 40, points: 4, assists: 1 },
      10: { minutes: 40, points: 5, goals: 1 },
    },
  },
  {
    name: "over",
    at: "2026-11-21T14:50:00Z",
    moments: [],
    inPlay: [101],
    finished: [],
    said: {
      1: { minutes: 90, points: 2 },
      2: { minutes: 90, points: 1, card: true },
      3: { minutes: 90, points: 6 },
      6: { minutes: 90, points: 2 },
      7: { minutes: 90, points: 6, assists: 1 },
      10: { minutes: 90, points: 6, goals: 1 },
    },
  },
  {
    name: "bonus",
    at: "2026-11-21T15:30:00Z",
    moments: [],
    inPlay: [102],
    finished: [101],
    said: {
      3: { minutes: 90, points: 7 },
      6: { minutes: 90, points: 3 },
      7: { minutes: 90, points: 8, assists: 1 },
      10: { minutes: 90, points: 9, goals: 1 },
      4: { minutes: 30, points: 1 },
      5: { minutes: 30, points: 1 },
      8: { minutes: 30, points: 1 },
      12: { minutes: 30, points: 1 },
    },
  },
  {
    name: "second",
    at: "2026-11-21T17:00:00Z",
    moments: [],
    inPlay: [],
    finished: [101, 102],
    said: {
      4: { minutes: 90, points: 6 },
      5: { minutes: 90, points: 6 },
      8: { minutes: 90, points: 3 },
      12: { minutes: 90, points: 6 },
    },
  },
  {
    name: "final",
    at: "2026-11-21T19:45:00Z",
    moments: ["substitution"],
    inPlay: [],
    finished: [101, 102, 103],
    said: {
      9: { minutes: 90, points: 2 },
      13: { minutes: 90, points: 2 },
      14: { minutes: 90, points: 2 },
      15: { minutes: 90, points: 2 },
    },
  },
];

/** The eight reads of the match day, in order; each a whole document of its own. */
export function liveBeats(): LiveBeat[] {
  const now = new Map<number, Said>();
  return PLANS.map((plan) => {
    for (const [id, said] of Object.entries(plan.said)) now.set(Number(id), said);
    const picks: TestPick[] = testPicks().map((pick) => {
      const said = now.get(pick.id);
      return said === undefined
        ? pick
        : { ...pick, minutes: said.minutes, points: said.points, card: said.card ?? false };
    });
    const fixtures = testFixtures().map((fixture) => ({
      ...fixture,
      finished: plan.finished.includes(fixture.id),
    }));
    const input = testWeek({ picks, fixtures, sourceTime: plan.at });
    const tally = (kind: "goals" | "assists") =>
      Object.fromEntries([...now].map(([id, said]) => [id, said[kind] ?? 0]));
    const activity = testActivity(input, {
      inPlay: plan.inPlay,
      goals: tally("goals"),
      assists: tally("assists"),
    });
    return {
      name: plan.name,
      at: plan.at,
      moments: plan.moments,
      document: { contract_version: "week_activity_v1", week: input.live, activity },
      input: { ...input, activity },
    };
  });
}

/** The beat named `name`. */
export function liveBeat(name: BeatName): LiveBeat {
  return liveBeats().find((beat) => beat.name === name)!;
}
