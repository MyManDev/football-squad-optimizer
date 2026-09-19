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

  it("reads a window's or a rival strategy's setting only at its own path", async () => {
    const window = { strategy: "saf-puan", window: 3, rivalEntryId: null };
    const plan = await loadEntryAdviceTop100(
      101,
      "advice/101/saf-puan/3/top100-20.json",
      20,
      false,
      undefined,
      window,
    );
    expect(plan.payload.window).toBe(3);
    expect(plan.payload.top100?.weight).toBe(20);
    const rival = { strategy: "ortak-koru", window: 5, rivalEntryId: 202 };
    const against = await loadEntryAdviceTop100(
      101,
      "advice/101/ortak-koru/5/vs-202/top100-40.json",
      40,
      false,
      undefined,
      rival,
    );
    expect(against.payload.mode).toBe("ortak-koru");
    for (const [path, word, target] of [
      ["advice/101/saf-puan/3/top100-20.json", true, window],
      ["advice/101/saf-puan/5/top100-20.json", false, window],
      ["advice/101/ortak-koru/5/vs-303/top100-40.json", false, rival],
      ["advice/101/ortak-koru/5/vs-202/top100-40.json", false, { ...rival, window: 7 }],
      ["advice/101/../x/5/vs-202/top100-40.json", false, { ...rival, strategy: "../x" }],
    ] as const) {
      await expect(
        loadEntryAdviceTop100(101, path, path.includes("-40") ? 40 : 20, word, undefined, target),
      ).rejects.toBeInstanceOf(LeagueDataError);
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
