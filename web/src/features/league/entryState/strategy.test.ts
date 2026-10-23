import { describe, expect, it } from "vitest";
import { EntryStateError } from "./parsers";
import {
  chooseRival,
  STRATEGY_RULE_ID,
  suggestStrategy,
  WEEKLY_POINTS_DIFFERENTIAL_POINTS,
} from "./strategy";
import vectors from "./strategy-vectors.json";

it("keeps the accepted server rule and scale", () => {
  expect(STRATEGY_RULE_ID).toBe(vectors.rule_id);
  expect(WEEKLY_POINTS_DIFFERENTIAL_POINTS).toBe(vectors.weekly_points_differential_points);
});

describe("the production Python rival selection", () => {
  for (const row of vectors.rivals) {
    it(row.name, () => {
      const ranks = new Map(row.ranks.map(([id, rank]) => [id!, rank!]));
      const candidates = new Map(row.candidates.map((id) => [id, { id }]));
      const choose = () => chooseRival(row.entry_id, ranks, candidates);
      if ("refused" in row.expected) expect(choose).toThrow(EntryStateError);
      else {
        const answer = choose();
        expect(answer?.id ?? null).toBe(row.expected.entry_id);
        if (answer !== null) expect(answer).toBe(candidates.get(answer.id));
        expect(
          chooseRival(row.entry_id, new Map([...ranks].reverse()), candidates)?.id ?? null,
        ).toBe(row.expected.entry_id);
      }
    });
  }
});

describe("the production Python suggestion for every week and band edge", () => {
  for (const row of vectors.suggestions)
    it(`week ${row.input.gameweek}, gap ${row.input.points_ahead_of_rival}`, () => {
      expect(suggestStrategy(row.input)).toEqual(row.expected);
    });
});

it.each([NaN, Infinity, -Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1, true, "2", null])(
  "refuses a malformed or imprecise integer: %j",
  (value) => {
    const input = vectors.suggestions[0]!.input;
    for (const field of Object.keys(input))
      expect(() => suggestStrategy({ ...input, [field]: value })).toThrow(EntryStateError);
    expect(() => chooseRival(value as number, new Map(), new Map())).toThrow(EntryStateError);
    expect(() => chooseRival(10, new Map([[10, value as number]]), new Map())).toThrow(
      EntryStateError,
    );
  },
);
