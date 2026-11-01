import type { Language } from "../../i18n/messages";

/**
 * The fixtures page's copy, in both languages.
 *
 * It lives beside the components that read it, so it loads with the page's own chunk and
 * not with every first visit. The honesty sweep (`i18n/messagesNoProbability.test.ts`)
 * walks it entry by entry, functions called.
 *
 * What it may say: who plays whom, when, and what the score was, and how to take the
 * deadlines into a calendar. It names no favourite, no difficulty and no expectation about a
 * match.
 */
export interface FixturesCopy {
  thisWeek: string;
  nextWeek: string;
  versus: string;
  unscheduled: string;
  noFixtures: string;
  pageTitle: string;
  pastTitle: string;
  noPast: string;
  notPublished: string;
  unscheduledCount: (count: number) => string;
  /** The calendar file of the upcoming deadlines: its button, the sentence beside it and
   * the words each event carries in the calendar. */
  calendarAction: string;
  calendarSummary: (gameweek: number) => string;
  calendarDescription: (link: string) => string;
}

const en: FixturesCopy = {
  thisWeek: "Upcoming gameweek",
  nextWeek: "Following gameweek",
  versus: "v",
  unscheduled: "TBC",
  noFixtures: "No fixtures in this gameweek.",
  pageTitle: "Fixtures",
  pastTitle: "Past gameweeks",
  noPast: "No gameweek has been played yet.",
  notPublished: "No fixture list has been published yet.",
  unscheduledCount: (count) =>
    count === 1
      ? "1 postponed fixture has no new gameweek yet and is not listed."
      : `${count} postponed fixtures have no new gameweek yet and are not listed.`,
  calendarAction: "Add deadlines to your calendar",
  calendarSummary: (gameweek) => `FPL GW${gameweek} deadline`,
  calendarDescription: (link) => `Open SquadOpt before the deadline: ${link}`,
};

const tr: FixturesCopy = {
  thisWeek: "Oynanacak hafta",
  nextWeek: "Gelecek hafta",
  versus: "-",
  unscheduled: "Belli değil",
  noFixtures: "Bu oyun haftasında maç yok.",
  pageTitle: "Fikstür",
  pastTitle: "Geçmiş haftalar",
  noPast: "Henüz oynanmış bir oyun haftası yok.",
  notPublished: "Henüz yayımlanmış bir fikstür yok.",
  unscheduledCount: (count) =>
    `Ertelenen ${count} maçın yeni oyun haftası henüz belli değil; listede yer almıyor.`,
  calendarAction: "Deadline'ları takvime ekle",
  calendarSummary: (gameweek) => `FPL ${gameweek}. hafta son tarihi`,
  calendarDescription: (link) => `Deadline'dan önce SquadOpt'u açın: ${link}`,
};

export const FIXTURES_COPY: Record<Language, FixturesCopy> = { en, tr };
