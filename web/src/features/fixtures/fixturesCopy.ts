import type { Language } from "../../i18n/messages";

/**
 * The fixture panels' copy, in both languages.
 *
 * It lives beside the components that read it, so it loads with the panels' own chunk and
 * not with every first visit. The honesty sweep (`i18n/messagesNoProbability.test.ts`)
 * walks it entry by entry, functions called.
 *
 * What it may say: who plays whom, when, and what the score was. It names no favourite, no
 * difficulty and no expectation about a match.
 */
export interface FixturesCopy {
  thisWeek: string;
  nextWeek: string;
  deadline: (when: string) => string;
  versus: string;
  unscheduled: string;
  noFixtures: string;
  pastLink: string;
  summary: string;
  pageTitle: string;
  pageLede: string;
  pastTitle: string;
  noPast: string;
  notPublished: string;
  unscheduledCount: (count: number) => string;
  capturedAt: (when: string) => string;
}

const en: FixturesCopy = {
  thisWeek: "This week",
  nextWeek: "Next week",
  deadline: (when) => `Deadline ${when}`,
  versus: "v",
  unscheduled: "TBC",
  noFixtures: "No fixtures in this gameweek.",
  pastLink: "Past gameweeks",
  summary: "Fixtures: this week and next",
  pageTitle: "Fixtures",
  pageLede: "The schedule and the results, as the game published them. Times are your local time.",
  pastTitle: "Past gameweeks",
  noPast: "No gameweek has been played yet.",
  notPublished: "No fixture list has been published yet.",
  unscheduledCount: (count) =>
    count === 1
      ? "1 postponed fixture has no new gameweek yet and is not listed."
      : `${count} postponed fixtures have no new gameweek yet and are not listed.`,
  capturedAt: (when) => `As recorded on ${when}.`,
};

const tr: FixturesCopy = {
  thisWeek: "Bu hafta",
  nextWeek: "Gelecek hafta",
  deadline: (when) => `Son tarih ${when}`,
  versus: "-",
  unscheduled: "Belli değil",
  noFixtures: "Bu oyun haftasında maç yok.",
  pastLink: "Geçmiş haftalar",
  summary: "Fikstür: bu hafta ve gelecek hafta",
  pageTitle: "Fikstür",
  pageLede: "Oyunun yayımladığı maç programı ve sonuçlar. Saatler bulunduğunuz yerin saatidir.",
  pastTitle: "Geçmiş haftalar",
  noPast: "Henüz oynanmış bir oyun haftası yok.",
  notPublished: "Henüz yayımlanmış bir fikstür yok.",
  unscheduledCount: (count) =>
    `Ertelenen ${count} maçın yeni oyun haftası henüz belli değil; listede yer almıyor.`,
  capturedAt: (when) => `${when} tarihli kayda göre.`,
};

export const FIXTURES_COPY: Record<Language, FixturesCopy> = { en, tr };
