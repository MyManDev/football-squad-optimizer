/**
 * A Top 100 weighted plan is read only at the one path the producer writes for that
 * member, weight and switch.
 */

import { describe, expect, it } from "vitest";

import { loadEntryAdviceTop100 } from "./data";
import { LeagueDataError } from "./dataErrors";

describe("loadEntryAdviceTop100", () => {
  it("refuses any path, weight or switch other than the member's own", async () => {
    const refused: [string, number, boolean][] = [
      ["advice/202/saf-puan/1/top100-20.json", 20, false],
      ["advice/101/saf-puan/1/top100-20.json", 30, false],
      ["advice/101/saf-puan/1/top100-20.json", 20, true],
      ["advice/101/saf-puan/1/top100-20-hoca-sozu.json", 20, false],
      ["advice/101/saf-puan/1/top100-0.json", 0, false],
      ["advice/101/saf-puan/1/top100-15.json", 15, false],
      ["advice/101/saf-puan/1.json", 20, false],
      ["advice/101/saf-puan/1/../../index.json", 20, false],
    ];
    for (const [path, weight, word] of refused) {
      await expect(loadEntryAdviceTop100(101, path, weight, word)).rejects.toBeInstanceOf(
        LeagueDataError,
      );
    }
  });

  it("reads the member's own weighted plan, with and without the word", async () => {
    const plain = await loadEntryAdviceTop100(
      101,
      "advice/101/saf-puan/1/top100-20.json",
      20,
      false,
    );
    expect(plain.payload.entry_id).toBe(101);
    expect(plain.payload.top100?.weight).toBe(20);
    expect(plain.payload.evidence).toBeUndefined();

    const word = await loadEntryAdviceTop100(
      101,
      "advice/101/saf-puan/1/top100-50-hoca-sozu.json",
      50,
      true,
    );
    expect(word.payload.top100?.weight).toBe(50);
    expect(word.payload.evidence?.kind).toBe("managers_word");
  });
});
