/** Integer transition witnesses remain legal; fractional buy/sell cycles do not. */
import { describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/horizons.json";
import { horizonProblem } from "./lp/horizon";
import type { LpRow } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

const document = fixture.document as unknown as DevicePlanDocument;
const entry = fixture.members[0]!.entry as DevicePlanEntry;

function satisfied(row: LpRow, values: Record<string, number>) {
  const value = row.terms.reduce((sum, term) => sum + term.coefficient * values[term.variable]!, 0);
  return row.sense === "="
    ? value === row.rhs
    : row.sense === "<="
      ? value <= row.rhs
      : value >= row.rhs;
}

it("keeps every binary continuity transition for an original and an arriving player", () => {
  const problem = horizonProblem(document, entry, 3);
  for (const index of [0, document.players.findIndex((p) => !entry.held.includes(p.id))]) {
    const held = Number(entry.held.includes(document.players[index]!.id));
    for (const week of [0, 1])
      for (const previous of week === 0 ? [held] : [0, 1])
        for (const selected of [0, 1])
          for (const incoming of [0, 1])
            for (const outgoing of [0, 1]) {
              if (selected - previous !== incoming - outgoing || incoming + outgoing > 1) continue;
              const values = {
                [`s${week}_${index}`]: selected,
                [`s${week - 1}_${index}`]: previous,
                [`i${week}_${index}`]: incoming,
              };
              for (const name of ["arrival_held", "arrival_new"])
                expect(
                  satisfied(
                    problem.rows.find((r) => r.name === `${name}${week}_${index}`)!,
                    values,
                  ),
                ).toBe(true);
            }
  }
});

it("cuts fractional cycles at both previously absent and previously held players", () => {
  const problem = horizonProblem(document, entry, 3);
  const rows = (name: string) => problem.rows.find((r) => r.name === `${name}1_0`)!;
  const absent = { s0_0: 0, s1_0: 0, i1_0: 0.5, o1_0: 0.5 };
  const held = { ...absent, s0_0: 1, s1_0: 1 };
  for (const witness of [absent, held]) {
    expect(satisfied(rows("continuity"), witness)).toBe(true);
    expect(satisfied(rows("one_direction"), witness)).toBe(true);
  }
  expect(satisfied(rows("arrival_held"), absent)).toBe(false);
  expect(satisfied(rows("arrival_new"), held)).toBe(false);
});

describe.each([0, 1, 5])("reachable free-transfer states at cap %i", (cap) => {
  for (let initial = 0; initial <= cap; initial += 1)
    it(`preserves every five-week move history from FT${initial}`, () => {
      const problem = horizonProblem(
        { ...document, rules: { ...document.rules, max_free_transfers: cap } },
        { ...entry, free_transfers: initial },
        5,
      );
      for (let history = 0; history < 32; history += 1) {
        let free = initial;
        for (let week = 0; week < 5; week += 1) {
          const moves = (history >> week) & 1;
          const paid = Math.max(0, moves - free);
          const next = Math.min(cap, free - Math.min(moves, free) + 1);
          for (const [prefix, value] of [
            ["f", free],
            ["n", next],
          ] as const) {
            const bound = problem.generals.find((b) => b.variable === `${prefix}${week}`)!;
            expect(value).toBeGreaterThanOrEqual(bound.lower);
            expect(value).toBeLessThanOrEqual(bound.upper);
          }
          const proof = problem.rows.find((r) => r.name === `paid_impossible${week}`);
          if (proof) expect(satisfied(proof, { [`p${week}`]: paid })).toBe(true);
          expect(
            satisfied(
              problem.rows.find((r) => r.name === `next_monotone${week}`)!,
              {
                [`f${week}`]: free,
                [`n${week}`]: next,
              },
            ),
          ).toBe(true);
          free = next;
        }
      }
    });
});
