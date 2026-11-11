import { describe, expect, it } from "vitest";

import { advanceLiveMarks, type LiveRead } from "./liveEvents";

const PICKS = [11, 12, 13];
const at = (minute: number) => new Date(Date.UTC(2026, 10, 21, 15, minute)).toISOString();

function read(
  minute: number,
  rows: { element: number; fixture?: number; goals?: number; assists?: number }[],
  cards: number[] = [],
  identity = "entry:11",
): LiveRead {
  return {
    identity,
    sourceTime: at(minute),
    elements: [...PICKS, 99].map((element_id) => ({
      element_id,
      card_shown: cards.includes(element_id),
    })),
    activity: {
      in_play_fixtures: [7],
      appearances: rows.map(({ element, fixture = 7, goals = 0, assists = 0 }) => ({
        element_id: element,
        fixture_id: fixture,
        minutes: 60,
        goals,
        assists,
      })),
    },
  };
}

describe("advanceLiveMarks", () => {
  it("takes the first read of a week as its starting point, with no events", () => {
    const { marks, events } = advanceLiveMarks(null, read(1, [{ element: 11, goals: 2 }]), PICKS);
    expect(events).toEqual([]);
    expect(marks.counts.get("11:7:goal")).toBe(2);
  });

  it("names the goals, assists and cards a newer read adds, in pick order", () => {
    const first = advanceLiveMarks(null, read(1, [{ element: 11 }, { element: 12 }]), PICKS).marks;
    const { events } = advanceLiveMarks(
      first,
      read(
        2,
        [
          { element: 11, assists: 1 },
          { element: 12, goals: 2 },
          { element: 99, goals: 1 },
        ],
        [13],
      ),
      PICKS,
    );
    expect(events).toEqual([
      { kind: "assist", elementId: 11, count: 1 },
      { kind: "goal", elementId: 12, count: 2 },
      { kind: "card", elementId: 13, count: 1 },
    ]);
  });

  it("adds a double week's fixtures together for one event", () => {
    const first = advanceLiveMarks(
      null,
      read(1, [
        { element: 11, fixture: 7 },
        { element: 11, fixture: 8 },
      ]),
      PICKS,
    ).marks;
    const { events } = advanceLiveMarks(
      first,
      read(2, [
        { element: 11, fixture: 7, goals: 1 },
        { element: 11, fixture: 8, goals: 1 },
      ]),
      PICKS,
    );
    expect(events).toEqual([{ kind: "goal", elementId: 11, count: 2 }]);
  });

  it("adds nothing for a read that is not newer, and keeps its marks", () => {
    const first = advanceLiveMarks(null, read(5, [{ element: 11 }]), PICKS).marks;
    for (const minute of [5, 4]) {
      const result = advanceLiveMarks(first, read(minute, [{ element: 11, goals: 1 }]), PICKS);
      expect(result.events).toEqual([]);
      expect(result.marks).toBe(first);
    }
  });

  it("never plays a goal twice: a correction keeps the highest count", () => {
    let marks = advanceLiveMarks(null, read(1, [{ element: 11 }]), PICKS).marks;
    let result = advanceLiveMarks(marks, read(2, [{ element: 11, goals: 1 }]), PICKS);
    expect(result.events).toHaveLength(1);
    marks = result.marks;
    result = advanceLiveMarks(marks, read(3, [{ element: 11, goals: 0 }]), PICKS);
    expect(result.events).toEqual([]);
    result = advanceLiveMarks(result.marks, read(4, [{ element: 11, goals: 1 }]), PICKS);
    expect(result.events).toEqual([]);
    result = advanceLiveMarks(result.marks, read(5, [{ element: 11, goals: 2 }]), PICKS);
    expect(result.events).toEqual([{ kind: "goal", elementId: 11, count: 1 }]);
  });

  it("keeps the marks through a read without event detail, so its return replays nothing", () => {
    const first = advanceLiveMarks(null, read(1, [{ element: 11, goals: 1 }]), PICKS).marks;
    const blind = advanceLiveMarks(first, { ...read(2, []), activity: null }, PICKS);
    expect(blind.events).toEqual([]);
    const back = advanceLiveMarks(blind.marks, read(3, [{ element: 11, goals: 1 }]), PICKS);
    expect(back.events).toEqual([]);
  });

  it("names a card once", () => {
    const first = advanceLiveMarks(null, read(1, [], []), PICKS).marks;
    const shown = advanceLiveMarks(first, read(2, [], [12]), PICKS);
    expect(shown.events).toEqual([{ kind: "card", elementId: 12, count: 1 }]);
    expect(advanceLiveMarks(shown.marks, read(3, [], [12]), PICKS).events).toEqual([]);
  });

  it("starts afresh for another member or week, and refuses a read without a time", () => {
    const first = advanceLiveMarks(null, read(1, [{ element: 11 }]), PICKS).marks;
    const other = advanceLiveMarks(
      first,
      read(2, [{ element: 11, goals: 1 }], [], "entry:12"),
      PICKS,
    );
    expect(other.events).toEqual([]);
    const timeless = advanceLiveMarks(
      first,
      { ...read(3, [{ element: 11, goals: 3 }]), sourceTime: "never" },
      PICKS,
    );
    expect(timeless).toEqual({ marks: first, events: [] });
  });
});
