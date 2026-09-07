/**
 * The loaders address the producer's tree by strategy and window: a three-week
 * pure-points request reads `advice/{id}/saf-puan/3.json` — in tests, the example of
 * exactly that document — and the index names the windows the producer wrote.
 */

import { describe, expect, it } from "vitest";

import { loadEntryAdvice, loadEntryAdviceIndex } from "./data";

const ENTRY = 35249001;

describe("league advice loaders", () => {
  it.each([1, 3, 5] as const)("loads the pure-points document for window %i", async (window) => {
    const envelope = await loadEntryAdvice(ENTRY, "saf-puan", window);
    expect(envelope.contract_version).toBe("provisional_league_ui_v1");
    expect(envelope.payload).toMatchObject({ entry_id: ENTRY, mode: "saf-puan", window });
    if (window === 1) {
      expect(envelope.payload.plan_weeks).toBeUndefined();
    } else {
      expect(envelope.payload.plan_weeks).toHaveLength(window);
      expect(envelope.payload.stated_limits?.length).toBeGreaterThan(0);
    }
  });

  it("lists the windows the producer wrote per strategy", async () => {
    const index = (await loadEntryAdviceIndex(ENTRY)).payload;
    expect(index.windows).toEqual({ "saf-puan": [1, 3, 5], "ortak-koru": [1], "fark-yarat": [1] });
    expect(index.window).toBe(1);
  });
});
