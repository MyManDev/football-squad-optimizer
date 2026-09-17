/**
 * The switched-on plan is read only at the one path an index may name for a member.
 */

import { describe, expect, it } from "vitest";

import { loadEntryAdviceEvidence } from "./data";
import { LeagueDataError } from "./dataErrors";

describe("loadEntryAdviceEvidence", () => {
  it("refuses any path other than the member's own switched-on plan", async () => {
    await expect(
      loadEntryAdviceEvidence(101, "advice/202/saf-puan/1/hoca-sozu.json"),
    ).rejects.toBeInstanceOf(LeagueDataError);
    await expect(loadEntryAdviceEvidence(101, "advice/101/saf-puan/1.json")).rejects.toBeInstanceOf(
      LeagueDataError,
    );
    await expect(
      loadEntryAdviceEvidence(101, "advice/101/saf-puan/1/../../../index.json"),
    ).rejects.toBeInstanceOf(LeagueDataError);
  });

  it("reads the member's own switched-on plan, which carries its evidence", async () => {
    const envelope = await loadEntryAdviceEvidence(101, "advice/101/saf-puan/1/hoca-sozu.json");
    expect(envelope.payload.entry_id).toBe(101);
    expect(envelope.payload.mode).toBe("saf-puan");
    expect(envelope.payload.window).toBe(1);
    expect(envelope.payload.evidence?.kind).toBe("managers_word");
  });
});
