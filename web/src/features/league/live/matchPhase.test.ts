import { describe, expect, it } from "vitest";

import { testPicks, testWeek } from "../../../testSupport/liveWeek";
import { liveBoard } from "./liveBoard";
import { matchesOver } from "./matchPhase";
import { memberLiveScore } from "./memberLiveScore";

describe("the week's matches that are over", () => {
  // The evening of a played day: every match is past its window and every pick has played,
  // but FPL has checked no bonus yet, so none of its fixtures says `finished`.
  const input = testWeek({
    picks: testPicks().map((pick) => ({ ...pick, minutes: 90 })),
    sourceTime: "2026-11-21T22:00:00Z",
  });

  it("are counted by their window, not by FPL's bonus check", () => {
    expect(input.live.fixtures.every((fixture) => !fixture.finished)).toBe(true);
    expect(matchesOver(input)).toBe(3);
  });

  it("are one count on the member's live card and on the LIVE board", () => {
    const result = memberLiveScore(input);
    if (!result.ok) throw new Error(result.reason);
    // The score's own count waits for the bonus and stays what says the bonus is in.
    expect(result.live.score.fixtures_finished).toBe(0);
    expect(result.live.score.bonus_confirmed).toBe(false);
    expect(result.live.matchesOver).toBe(3);
    expect(liveBoard(input)!.matchesOver).toBe(result.live.matchesOver);
  });

  it("leave a match that has not kicked off out", () => {
    const early = testWeek({
      picks: testPicks().map((pick) => ({ ...pick, minutes: 0 })),
      sourceTime: "2026-11-21T12:00:00Z",
    });
    expect(matchesOver(early)).toBe(0);
  });
});
