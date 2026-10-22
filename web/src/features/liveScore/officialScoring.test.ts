import { describe, expect, it } from "vitest";

import { scoreMemberWeek } from "./officialScoring";
import vectors from "./officialScoring.vectors.json";

type VectorInput = (typeof vectors.cases)[number]["input"];
type Input = Omit<VectorInput, "members"> & { members: VectorInput["members"][number][] };
const copy = (name = "normal-week"): Input =>
  structuredClone(vectors.cases.find((item) => item.name === name)!.input);
const score = (input: Input) => scoreMemberWeek(input, input.members[0]);
const player = (input: Input, id: number) =>
  input.elements.find((element) => element.element_id === id)!;
const finish = (input: Input) => {
  input.fixtures.forEach((fixture) => {
    fixture.finished = true;
  });
  return score(input);
};

describe("the Python official scoring reference", () => {
  it.each(vectors.cases)("equals $name exactly", ({ input, expected }) => {
    expect(score(input)).toMatchObject(expected);
    expect(score(input)).toEqual(score(structuredClone(input)));
  });
});

describe("a gameweek in progress", () => {
  it("waits for every fixture of an absent starter's club", () => {
    const input = copy("goalkeeper-swap");
    input.fixtures.push({ id: 62, home_club: 1, away_club: 3, finished: false });
    expect(score(input)).toMatchObject({
      refused: false,
      autosubs: [],
      bonus_confirmed: false,
      fixtures_finished: 1,
      fixtures_total: 2,
    });
    expect(finish(input)).toMatchObject(
      vectors.cases.find((c) => c.name === "goalkeeper-swap")!.expected,
    );
    expect(score(input)).toMatchObject({ autosubs: [[1, 12]] });
  });

  it("stops the outfield bench at the first pending reserve, then uses the finished reference", () => {
    const input = copy("absent-reserve-skipped");
    const reserve = input.members[0]!.pick_order.slice(11).find(
      (id) => player(input, id).position !== "GK",
    )!;
    player(input, reserve).club = 3;
    input.fixtures.push({ id: 62, home_club: 3, away_club: 4, finished: false });
    expect(score(input)).toMatchObject({ autosubs: [] });
    expect(finish(input)).toMatchObject(
      vectors.cases.find((c) => c.name === "absent-reserve-skipped")!.expected,
    );
  });

  it("does not let a pending reserve goalkeeper block an outfield change", () => {
    const input = copy("outfield-bench-order");
    Object.assign(player(input, 12), { minutes: 0, points: 0, club: 3 });
    input.fixtures.push({ id: 62, home_club: 3, away_club: 4, finished: false });
    const result = score(input);
    expect(result.refused).toBe(false);
    if (!result.refused) expect(result.autosubs.length).toBeGreaterThan(0);
    expect(finish(input)).toMatchObject(
      vectors.cases.find((c) => c.name === "outfield-bench-order")!.expected,
    );
  });

  it("keeps the captain until his final fixture and the pending vice after that", () => {
    const input = copy("captain-and-vice-absent");
    const { captain, vice } = input.members[0]!;
    player(input, captain).club = 3;
    player(input, vice).club = 4;
    input.fixtures.push({ id: 62, home_club: 3, away_club: 5, finished: false });
    input.fixtures.push({ id: 63, home_club: 4, away_club: 6, finished: false });
    expect(score(input)).toMatchObject({ captain, captain_bonus_points: 0 });
    input.fixtures[1]!.finished = true;
    expect(score(input)).toMatchObject({ captain: vice, captain_bonus_points: 0 });
    expect(finish(input)).toMatchObject({
      ...vectors.cases.find((c) => c.name === "captain-and-vice-absent")!.expected,
      captain: null,
    });
  });

  it("counts a zero-minute card immediately without inventing captain minutes", () => {
    const input = copy("zero-minute-captain-card");
    input.fixtures[0]!.finished = false;
    expect(score(input)).toMatchObject({ captain: input.members[0]!.captain });
    expect(finish(input)).toMatchObject(
      vectors.cases.find((c) => c.name === "zero-minute-captain-card")!.expected,
    );
    expect(score(input)).toMatchObject({ captain: input.members[0]!.vice });
  });

  it("does not mutate any source block", () => {
    const input = copy("triple-captain-absent");
    const kept = structuredClone(input);
    score(input);
    expect(input).toEqual(kept);
  });

  it("sums signed integer points exactly before checking the output range", () => {
    const input = copy();
    player(input, 1).points = Number.MAX_SAFE_INTEGER;
    player(input, 2).points = 2;
    player(input, 3).points = -Number.MAX_SAFE_INTEGER;
    expect(score(input)).toMatchObject({ refused: false, gross: 11, net: 11 });
  });
});

describe("input refusals", () => {
  const bad = [
    [
      "missing pick",
      (input: Input) => {
        input.elements.pop();
      },
    ],
    [
      "unknown position",
      (input: Input) => {
        Object.assign(input.elements[0]!, { position: undefined });
      },
    ],
    [
      "unknown club",
      (input: Input) => {
        Object.assign(input.elements[0]!, { club: undefined });
      },
    ],
    [
      "duplicate element",
      (input: Input) => {
        input.elements.push({ ...input.elements[0]! });
      },
    ],
    [
      "duplicate fixture",
      (input: Input) => {
        input.fixtures.push({ ...input.fixtures[0]! });
      },
    ],
    [
      "duplicate member",
      (input: Input) => {
        input.members.push({ ...input.members[0]! });
      },
    ],
    [
      "duplicate pick",
      (input: Input) => {
        input.members[0]!.pick_order[1] = input.members[0]!.pick_order[0]!;
      },
    ],
    [
      "wrong week",
      (input: Input) => {
        input.members[0]!.gameweek += 1;
      },
    ],
    [
      "invalid formation",
      (input: Input) => {
        input.elements[0]!.position = "DEF";
      },
    ],
    [
      "benched captain",
      (input: Input) => {
        input.members[0]!.captain = 12;
      },
    ],
    [
      "identical captains",
      (input: Input) => {
        input.members[0]!.vice = input.members[0]!.captain;
      },
    ],
    [
      "impossible instant",
      (input: Input) => {
        input.source_time = "2026-02-31T12:00:00Z";
      },
    ],
    [
      "offset instant",
      (input: Input) => {
        input.source_time = "2026-10-12T22:00:00+00:00";
      },
    ],
    [
      "boolean points",
      (input: Input) => {
        Object.assign(input.elements[0]!, { points: true });
      },
    ],
    [
      "fractional points",
      (input: Input) => {
        input.elements[0]!.points = 1.5;
      },
    ],
    [
      "negative minutes",
      (input: Input) => {
        input.elements[0]!.minutes = -1;
      },
    ],
    [
      "unknown field",
      (input: Input) => {
        Object.assign(input, { surprise: 1 });
      },
    ],
    [
      "overflow",
      (input: Input) => {
        input.elements.forEach((element) => {
          element.points = Number.MAX_SAFE_INTEGER;
        });
      },
    ],
  ] as const;
  it.each(bad)("refuses %s", (_, mutate) => {
    const input = copy();
    mutate(input);
    expect(score(input)).toMatchObject({ refused: true });
  });
  it.each([null, [], {}, "<html>not data</html>"])("refuses malformed input %j", (input) => {
    expect(scoreMemberWeek(input, null)).toEqual({ refused: true, reason: "invalid_week" });
  });
});
