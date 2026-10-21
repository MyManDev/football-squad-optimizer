import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../fixtures/league";
import type { AdviceEvidenceItem } from "../features/league/types";

export const NEWS_ENTRY = 35249001;

/** Synthetic source-verified evidence, used only by the player-news tests. */
export function coachNewsFixture() {
  const squad = structuredClone(mockEntrySquadEnvelopes[NEWS_ENTRY]!);
  const document = structuredClone(mockEntryAdviceEnvelope(NEWS_ENTRY, "saf-puan", 1));
  const item: AdviceEvidenceItem = {
    player_id: squad.payload.starting_xi[0]!.player_id,
    name: squad.payload.starting_xi[0]!.name,
    disposition: "stated_expected_absent",
    role: "not_starting",
    speaker: "manager",
    published_at_utc: "2026-08-21T14:00:00Z",
    published_precision: "instant",
    club: "Liverpool",
    source_url: "https://club.example/news/team-update",
    fetched_at_utc: "2026-08-21T14:05:00Z",
    words: "He will not be available for this match.",
    words_status: "shown",
  };
  document.payload.evidence = {
    kind: "managers_word",
    rule_version: "managers_word_rule_v3",
    source_kind: "club_news_capture",
    source_label: "synthetic-test-capture",
    evidence_table: "synthetic-test-evidence.csv",
    clubs_covered: ["Liverpool"],
    binding: true,
    applied: [item],
  };
  return { squad, document, item };
}
