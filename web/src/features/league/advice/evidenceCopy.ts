import type { Language } from "../../../i18n/messages";

/**
 * The manager's-word copy, in both languages.
 *
 * It lives beside the two components that read it, the decision controls and the advice
 * card, which load with the member page rather than with every first visit. Moving it out
 * of `MESSAGES` moves no guard: the honesty sweep (`i18n/messagesNoProbability.test.ts`)
 * walks this catalogue as well, entry by entry, called functions included.
 *
 * What the words may say is the envelope's: a rule that is declared and not measured, a
 * role the rule gave a player, the club's own words shown as a quote, and a price in
 * expected points. Nothing here describes how likely anything is.
 */
export interface EvidenceCopy {
  legend: string;
  switchLabel: string;
  unavailableReasons: Record<string, string>;
  onlyBaseline: string;
  sourceExample: string;
  sourceCapture: string;
  title: string;
  intro: (clubs: number) => string;
  unchanged: string;
  changed: string;
  wordsUnresolved: string;
  wordsWithheld: string;
  speakers: Record<string, string>;
  speakerUnknown: string;
  said: (speaker: string, when: string | null) => string;
  source: string;
  roles: Record<string, string>;
  cost: (points: string) => string;
  costAtMost: (points: string) => string;
  moveReason: string;
}

const en: EvidenceCopy = {
  legend: "The manager's word",
  switchLabel: "Apply what the club's page said",
  unavailableReasons: {
    no_evidence_this_run: "No club news was read for this publish.",
    not_solved_for_member: "Not solved for this member in this publish.",
  },
  onlyBaseline: "One-week pure-points plan only.",
  sourceExample: "Example data: not a real club page.",
  sourceCapture: "Read from registered club pages before this data snapshot.",
  title: "What the club's page said",
  intro: (clubs: number) =>
    `Declared rule, not measured: a stated absence keeps a player out of the eleven, a stated doubt off the armband. Clubs read: ${clubs}.`,
  unchanged: "The club's page did not change this plan.",
  changed: "The club's page changed this plan; the cost is stated above.",
  wordsUnresolved: "The cited words could not be resolved.",
  wordsWithheld: "The quote carries wording this site does not publish; read it at the source.",
  speakers: {
    manager: "The manager",
    club_official: "A club official",
    club_statement: "A club statement",
    unattributed: "Speaker not named",
  } as Record<string, string>,
  speakerUnknown: "The club",
  said: (speaker: string, when: string | null) => (when ? `${speaker}, ${when}.` : `${speaker}.`),
  source: "Source →",
  roles: { not_starting: "Out of the eleven", not_captain: "Not captain" } as Record<
    string,
    string
  >,
  cost: (points: string) =>
    `Applying the club's word gives up ~${points} expected points against the pure-points pick, hits included.`,
  costAtMost: (points: string) =>
    `Applying the club's word gives up at most ${points} expected points against the pure-points pick, hits included.`,
  moveReason: "In the plan because of what the club's page said.",
};

const tr: EvidenceCopy = {
  legend: "Hocanın sözü",
  switchLabel: "Kulübün sayfasının dediğini uygula",
  unavailableReasons: {
    no_evidence_this_run: "Bu yayında kulüp haberi okunmadı.",
    not_solved_for_member: "Bu yayında bu üye için çözülmedi.",
  },
  onlyBaseline: "Yalnız bir haftalık saf puan planında.",
  sourceExample: "Örnek veri: gerçek bir kulüp sayfası değil.",
  sourceCapture: "Bu veri çekiminden önce kayıtlı kulüp sayfalarından okundu.",
  title: "Kulübün sayfası ne dedi",
  intro: (clubs) =>
    `Beyan edilmiş kural, ölçülmemiş: söylenmiş yokluk on birin, söylenmiş şüphe kaptanlığın dışında tutar. Okunan kulüp: ${clubs}.`,
  unchanged: "Kulübün sayfası bu planı değiştirmedi.",
  changed: "Kulübün sayfası bu planı değiştirdi; bedeli yukarıda yazılı.",
  wordsUnresolved: "Alıntı çözülemedi.",
  wordsWithheld: "Alıntı bu sitenin yayımlamadığı bir ifade içeriyor; kaynağından okuyun.",
  speakers: {
    manager: "Teknik direktör",
    club_official: "Kulüp yetkilisi",
    club_statement: "Kulüp açıklaması",
    unattributed: "Konuşan belirtilmemiş",
  },
  speakerUnknown: "Kulüp",
  said: (speaker, when) => (when ? `${speaker}, ${when}.` : `${speaker}.`),
  source: "Kaynak →",
  roles: { not_starting: "On birin dışında", not_captain: "Kaptan değil" },
  cost: (points) =>
    `Kulübün sözünü uygulamak saf puan seçimine göre ~${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  costAtMost: (points) =>
    `Kulübün sözünü uygulamak saf puan seçimine göre en fazla ${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  moveReason: "Kulübün sayfasının dediği için planda.",
};

export const EVIDENCE_COPY: Record<Language, EvidenceCopy> = { tr, en };

/** The sentence for an index reason; an unknown code reads as "nothing was read". */
export function evidenceUnavailable(copy: EvidenceCopy, reason: string | null): string {
  return (
    (reason !== null ? copy.unavailableReasons[reason] : undefined) ??
    copy.unavailableReasons.no_evidence_this_run
  );
}

/**
 * The page's own check on a quote before it is shown. The producer withholds these
 * already (``QUOTE_WITHHELD_PATTERN``); a document from anywhere else is held to the same
 * list here, so the rule does not rest on one side of the wire.
 */
export const QUOTE_WITHHELD =
  /%|per\s?cent|percentage|probabilit|olasıl|\bP\(|chance|likelihood|odds|quantile|spread|\btail\b|ihtimal|şans|yüzde(?!n\b)|kantil|yayılım|\bkuyruk\b|\b50\s*[-/]\s*50\b|fifty[\s-]fifty/i;
