import type { Language } from "../../../i18n/messages";

/**
 * The manager's-word copy, in both languages.
 *
 * It lives beside the two components that read it, the decision controls and the advice
 * card, which load with the member page rather than with every first visit. Moving it out
 * of `MESSAGES` moves no guard: the honesty sweep (`i18n/messagesNoProbability.test.ts`)
 * walks this catalogue as well, entry by entry, called functions included.
 *
 * What the words may say is the envelope's: a role the rule gave a player, the club's own
 * words shown as a quote, and a price in expected points. Nothing here describes how
 * likely anything is.
 */
export interface EvidenceCopy {
  legend: string;
  switchLabel: string;
  onlyBaseline: string;
  title: string;
  coveredClubs: string;
  unchanged: string;
  changed: string;
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
  onlyBaseline: "Switch to the one-week Most points plan for this.",
  title: "What the club's page said",
  coveredClubs: "Clubs covered by the news",
  unchanged: "The club's page did not change this plan.",
  changed: "The club's page changed this plan.",
  speakers: {
    manager: "The manager",
    club_official: "A club official",
    club_statement: "A club statement",
  } as Record<string, string>,
  speakerUnknown: "The club",
  said: (speaker: string, when: string | null) => (when ? `${speaker}, ${when}.` : `${speaker}.`),
  source: "Source →",
  roles: { not_starting: "Out of the eleven", not_captain: "Not captain" } as Record<
    string,
    string
  >,
  cost: (points: string) => `Applying the club's word gives up ~${points} expected points.`,
  costAtMost: (points: string) =>
    `Applying the club's word gives up at most ${points} expected points.`,
  moveReason: "In the plan because of what the club's page said.",
};

const tr: EvidenceCopy = {
  legend: "Hocanın sözü",
  switchLabel: "Kulübün sayfasının dediğini uygula",
  onlyBaseline: "Bunun için bir haftalık En çok puan planına geç.",
  title: "Kulübün sayfası ne dedi",
  coveredClubs: "Haber kapsamındaki kulüpler",
  unchanged: "Kulübün sayfası bu planı değiştirmedi.",
  changed: "Kulübün sayfası bu planı değiştirdi.",
  speakers: {
    manager: "Teknik direktör",
    club_official: "Kulüp yetkilisi",
    club_statement: "Kulüp açıklaması",
  },
  speakerUnknown: "Kulüp",
  said: (speaker, when) => (when ? `${speaker}, ${when}.` : `${speaker}.`),
  source: "Kaynak →",
  roles: { not_starting: "On birin dışında", not_captain: "Kaptan değil" },
  cost: (points) => `Kulübün sözünü uygulamak ~${points} beklenen puandan vazgeçmek demek.`,
  costAtMost: (points) =>
    `Kulübün sözünü uygulamak en fazla ${points} beklenen puandan vazgeçmek demek.`,
  moveReason: "Kulübün sayfasının dediği için planda.",
};

export const EVIDENCE_COPY: Record<Language, EvidenceCopy> = { tr, en };

/**
 * The page's own check on a quote before it is shown. The producer withholds these
 * already (``QUOTE_WITHHELD_PATTERN``); a document from anywhere else is held to the same
 * list here, so the rule does not rest on one side of the wire.
 */
export const QUOTE_WITHHELD =
  /%|per\s?cent|percentage|probabilit|olasıl|\bP\(|chance|likelihood|odds|quantile|spread|\btail\b|ihtimal|şans|yüzde(?!n\b)|kantil|yayılım|\bkuyruk\b|\b50\s*[-/]\s*50\b|fifty[\s-]fifty/i;
