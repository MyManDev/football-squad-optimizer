import { describe, expect, it } from "vitest";
import { coachNewsFixture } from "../../../testSupport/coachNews";
import type { AdviceEvidenceItem } from "../types";
import { coachAbsences } from "./coachAbsences";

describe("source-verified manager absences on players", () => {
  it("keeps the exact words and source from this publication", () => {
    const { squad, document, item } = coachNewsFixture();
    expect([...coachAbsences(document, squad).values()]).toEqual([
      {
        playerId: item.player_id,
        words: item.words,
        sourceUrl: item.source_url,
        publishedAt: item.published_at_utc,
      },
    ]);
  });

  it.each<Partial<AdviceEvidenceItem>>([
    { disposition: "stated_rotation_risk", role: "not_captain" },
    { disposition: "stated_full_match_unavailable" },
    { speaker: "club_statement" },
    { role: null },
    { words_status: "unresolved" },
    { words_status: "withheld_figure" },
    { words: " " },
    { words: "There is an 80% chance he misses the match." },
    { source_url: "javascript:alert(1)" },
    { source_url: "http://club.example/news" },
    { source_url: "https://user:password@club.example/news" },
    { source_url: "not a url" },
    { source_url: "https://club.example/news team" },
    { published_precision: "day" },
    { published_at_utc: "2026-08-22T05:00:00Z" },
    { published_at_utc: "yesterday" },
    { fetched_at_utc: "2026-08-23T00:00:00Z" },
  ])("does not turn incomplete or different evidence into an absence: %j", (change) => {
    const { squad, document, item } = coachNewsFixture();
    Object.assign(item, change);
    expect(coachAbsences(document, squad).size).toBe(0);
  });

  it.each(["synthetic_fixture", "unknown"])("refuses source kind %s", (kind) => {
    const { squad, document } = coachNewsFixture();
    document.payload.evidence!.source_kind = kind;
    expect(coachAbsences(document, squad).size).toBe(0);
  });

  it.each(["managers_word_rule_v1", "managers_word_rule_v2"])(
    "refuses the older rule %s",
    (rule) => {
      const { squad, document } = coachNewsFixture();
      document.payload.evidence!.rule_version = rule;
      expect(coachAbsences(document, squad).size).toBe(0);
    },
  );

  it.each(["league_id", "entry_id", "gameweek", "season", "source_snapshot_id", "window"] as const)(
    "refuses another %s",
    (key) => {
      const { squad, document } = coachNewsFixture();
      Object.assign(document.payload, {
        [key]: key === "season" || key === "source_snapshot_id" ? "other" : -1,
      });
      expect(coachAbsences(document, squad).size).toBe(0);
    },
  );

  it("refuses an older publication even for the same FPL snapshot", () => {
    const { squad, document } = coachNewsFixture();
    document.generated_at_utc = "2026-08-22T03:00:00Z";
    expect(coachAbsences(document, squad).size).toBe(0);
  });

  it("refuses conflicting duplicate statements", () => {
    const { squad, document, item } = coachNewsFixture();
    document.payload.evidence!.applied.push({ ...item, disposition: "stated_rotation_risk" });
    expect(coachAbsences(document, squad).size).toBe(0);
  });

  it("has no warning when the news document cannot be read", () => {
    const { squad } = coachNewsFixture();
    expect(coachAbsences(null, squad).size).toBe(0);
  });
});
