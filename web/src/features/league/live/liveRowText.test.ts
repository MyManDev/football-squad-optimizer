/**
 * The line under a LIVE row's name: the opponent, then the kickoff before the match or the
 * minutes once it has started, and in a double week read without event detail, never the
 * week's minutes on one of its matches.
 */

import { describe, expect, it } from "vitest";

import { MESSAGES } from "../../../i18n/messages";
import type { MemberWeek } from "../../liveScore/weekLive";
import { testActivity, testFixtures, testPicks, testWeek } from "../../../testSupport/liveWeek";
import { liveBoard } from "./liveBoard";
import { kickoffShort } from "./liveFormat";
import { rowLabel, subLine } from "./liveRowText";

const copy = MESSAGES.tr.live;
const LATE = "2026-11-21T19:45:00Z";

/** Player 1, of club 1, at `sourceTime`: 90 minutes in the 12:30 match, and club 1 plays again. */
function keeper(sourceTime: string, double = true) {
  const fixtures = double
    ? [...testFixtures(), { id: 104, home: 1, away: 6, kickoff: LATE, finished: false }]
    : testFixtures();
  const board = liveBoard(
    testWeek({
      sourceTime,
      fixtures,
      picks: testPicks().map((pick) =>
        pick.id === 1 ? { ...pick, points: 2, minutes: 90 } : pick,
      ),
    }),
  );
  return board!.rows.find((row) => row.elementId === 1)!;
}

describe("the line under a row's name", () => {
  it("gives the minutes of a single match once it has started", () => {
    expect(subLine(keeper("2026-11-21T13:30:00Z", false), copy, "tr-TR")).toBe(
      `C2 · ${copy.minutes("90")}`,
    );
  });

  it("gives a double week's second match its kickoff before it, without detail", () => {
    const row = keeper("2026-11-21T15:30:00Z");
    expect(row.fixture?.id).toBe(104);
    expect(subLine(row, copy, "tr-TR")).toBe(`C6 · ${kickoffShort(LATE, "tr-TR")}`);
  });

  it("gives a double week's match no minutes while it is played, without detail", () => {
    const row = keeper("2026-11-21T20:15:00Z");
    expect(row.fixture?.phase).toBe("playing");
    expect(subLine(row, copy, "tr-TR")).toBe("C6");
  });
});

describe("a row's events", () => {
  /** Every pick played; reserve 14, not brought on, scored. */
  function reserveScored(chip: MemberWeek["active_chip"]) {
    const input = testWeek({
      sourceTime: LATE,
      picks: testPicks().map((pick) => ({ ...pick, minutes: 90, points: pick.id === 14 ? 7 : 2 })),
      member: { active_chip: chip },
    });
    const board = liveBoard({ ...input, activity: testActivity(input, { goals: { 14: 1 } }) });
    return board!.rows.find((row) => row.elementId === 14)!;
  }

  it("tells no goal and no state of a reserve the scorer does not count", () => {
    const row = reserveScored(null);
    expect(row.counted).toBe(false);
    const label = rowLabel(row, MESSAGES.tr, "tr-TR");
    expect(label).not.toContain(copy.goal);
    expect(label).not.toContain(copy.doingWell);
  });

  it("tells the bench's goals under the bench boost, which counts it", () => {
    const row = reserveScored("bboost");
    expect(row.counted).toBe(true);
    expect(rowLabel(row, MESSAGES.tr, "tr-TR")).toContain(`${copy.goal} 1`);
  });
});
