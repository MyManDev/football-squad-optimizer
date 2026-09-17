/**
 * A chosen chip's plan is read only at the one path the producer writes for that member
 * and that chip.
 */

import { describe, expect, it } from "vitest";

import { loadEntryAdviceChip } from "./data";
import { LeagueDataError } from "./dataErrors";

describe("loadEntryAdviceChip", () => {
  it("refuses any path or chip other than the member's own", async () => {
    const refused: [string, string][] = [
      ["advice/202/saf-puan/1/chip-bboost.json", "bboost"],
      ["advice/101/saf-puan/1/chip-bboost.json", "wildcard"],
      ["advice/101/saf-puan/1/chip-limitless.json", "limitless"],
      ["advice/101/saf-puan/3/chip-bboost.json", "bboost"],
      ["advice/101/ortak-koru/1/chip-bboost.json", "bboost"],
      ["advice/101/saf-puan/1/chip-bboost-hoca-sozu.json", "bboost"],
      ["advice/101/saf-puan/1.json", "bboost"],
      ["advice/101/saf-puan/1/../../index.json", "bboost"],
    ];
    for (const [path, chip] of refused) {
      await expect(loadEntryAdviceChip(101, path, chip)).rejects.toBeInstanceOf(LeagueDataError);
    }
  });

  it("reads the member's own chip plan", async () => {
    for (const chip of ["wildcard", "freehit", "bboost", "3xc"] as const) {
      const plan = await loadEntryAdviceChip(101, `advice/101/saf-puan/1/chip-${chip}.json`, chip);
      expect(plan.payload.entry_id).toBe(101);
      expect(plan.payload.chip).toBe(chip);
      expect(plan.payload.chip_choice?.chip).toBe(chip);
      expect(plan.payload.top100).toBeUndefined();
      expect(plan.payload.evidence).toBeUndefined();
    }
  });
});
