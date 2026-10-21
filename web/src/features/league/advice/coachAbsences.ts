import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import { QUOTE_WITHHELD } from "./evidenceCopy";
import { isInjurySourceInstant, safeInjurySourceUrl } from "./officialInjuryFacts";

export interface CoachAbsence {
  playerId: number;
  words: string;
  sourceUrl: string;
  publishedAt: string;
}

/** Only the current publication's source-verified, explicit manager absences. */
export function coachAbsences(
  document: LeagueViewEnvelope<EntryAdvice> | null | undefined,
  squad: LeagueViewEnvelope<EntrySquad>,
): ReadonlyMap<number, CoachAbsence> {
  const result = new Map<number, CoachAbsence>();
  const advice = document?.payload;
  const entry = squad.payload;
  if (
    !document ||
    !advice ||
    !entry.source_snapshot_id ||
    advice.source_snapshot_id !== entry.source_snapshot_id ||
    advice.league_id !== entry.league_id ||
    advice.entry_id !== entry.entry.entry_id ||
    advice.season !== entry.season ||
    advice.gameweek !== entry.gameweek ||
    advice.window !== 1 ||
    document.generated_at_utc !== squad.generated_at_utc ||
    !isInjurySourceInstant(document.generated_at_utc)
  )
    return result;
  const evidence = advice.evidence;
  if (
    evidence?.source_kind !== "club_news_capture" ||
    evidence.rule_version !== "managers_word_rule_v3"
  )
    return result;
  const counts = new Map<number, number>();
  for (const item of evidence.applied)
    counts.set(item.player_id, (counts.get(item.player_id) ?? 0) + 1);
  for (const item of evidence.applied) {
    if (
      counts.get(item.player_id) !== 1 ||
      item.speaker !== "manager" ||
      item.role !== "not_starting" ||
      item.disposition !== "stated_expected_absent" ||
      item.words_status !== "shown" ||
      !item.words?.trim() ||
      QUOTE_WITHHELD.test(item.words) ||
      !safeInjurySourceUrl(item.source_url) ||
      !isInjurySourceInstant(item.published_at_utc) ||
      item.published_precision !== "instant" ||
      !isInjurySourceInstant(item.fetched_at_utc) ||
      Date.parse(item.published_at_utc) > Date.parse(item.fetched_at_utc) ||
      Date.parse(item.fetched_at_utc) > Date.parse(document.generated_at_utc)
    )
      continue;
    try {
      const source = new URL(item.source_url ?? "");
      if (source.protocol !== "https:" || source.username || source.password) continue;
      result.set(item.player_id, {
        playerId: item.player_id,
        words: item.words,
        sourceUrl: source.href,
        publishedAt: item.published_at_utc,
      });
    } catch {
      // A malformed source cannot become a player warning.
    }
  }
  return result;
}
