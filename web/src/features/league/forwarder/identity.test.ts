import { describe, expect, it } from "vitest";

import { BUNDLE_EXAMPLES } from "../../../fixtures/forwarder";
import type { FplEntryBundle } from "./documents";
import { bundleMatchesTable } from "./identity";

const { free_hit_walk_back: freeHit, late_joiner: lateJoiner } = BUNDLE_EXAMPLES;

const withPicks = (bundle: FplEntryBundle, weeks: number[]): FplEntryBundle => ({
  ...bundle,
  picks: weeks.map((event) => ({
    ...bundle.picks.at(-1)!,
    entry_history: { ...bundle.picks.at(-1)!.entry_history, event },
  })),
});

describe("a bundle and a device table", () => {
  it.each([
    ["the Free Hit walk-back", freeHit, 101],
    ["the late joiner", lateJoiner, 202],
  ] as const)("combine for %s when the picks are the table gameweek minus 1", (_, bundle, id) => {
    expect(bundleMatchesTable(bundle, { gameweek: 10 }, id)).toEqual({
      ok: true,
      held_gameweek: 9,
    });
  });

  it("are another member's when the bundle or its entry names another id", () => {
    expect(bundleMatchesTable(freeHit, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "entry_mismatch",
    });
    const named = { ...freeHit, entry: { ...freeHit.entry, id: 202 } };
    expect(bundleMatchesTable(named, { gameweek: 10 }, 101)).toEqual({
      ok: false,
      reason: "entry_mismatch",
    });
  });

  it("do not combine across table gameweeks, even when the picks would fit", () => {
    // A table of gameweek 9 plans from gameweek 8's picks; the bundle for 10 holds them too,
    // under a Free Hit, but it was asked for another table.
    expect(bundleMatchesTable(freeHit, { gameweek: 9 }, 101)).toEqual({
      ok: false,
      reason: "table_gameweek_mismatch",
    });
    expect(bundleMatchesTable(freeHit, { gameweek: 11 }, 101)).toEqual({
      ok: false,
      reason: "table_gameweek_mismatch",
    });
  });

  it("do not combine when the newest picks are another week's", () => {
    const early = withPicks(lateJoiner, [8]);
    expect(bundleMatchesTable(early, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "picks_gameweek_mismatch",
    });
    const late = withPicks(lateJoiner, [9, 10]);
    expect(bundleMatchesTable(late, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "picks_gameweek_mismatch",
    });
    const none = { ...lateJoiner, picks: [] };
    expect(bundleMatchesTable(none, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "picks_gameweek_mismatch",
    });
  });

  it("do not combine when the history has no row for the held week", () => {
    const history = {
      ...lateJoiner.history,
      current: lateJoiner.history.current.filter((row) => row.event !== 9),
    };
    expect(bundleMatchesTable({ ...lateJoiner, history }, { gameweek: 10 }, 202)).toEqual({
      ok: false,
      reason: "history_missing_week",
    });
  });

  it("combine when the history already has the week after, as it does once that deadline passes", () => {
    const history = {
      ...lateJoiner.history,
      current: [
        ...lateJoiner.history.current,
        { event: 10, event_transfers: 0, event_transfers_cost: 0, bank: 5 },
      ],
    };
    expect(bundleMatchesTable({ ...lateJoiner, history }, { gameweek: 10 }, 202)).toEqual({
      ok: true,
      held_gameweek: 9,
    });
  });
});
