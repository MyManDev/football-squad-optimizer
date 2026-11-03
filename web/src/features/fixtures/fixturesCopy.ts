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
  generalView: string;
  teamView: string;
  /** The names of the page's three choices, for assistive technology. */
  viewLegend: string;
  weekLegend: string;
  clubLegend: string;
  /** A club's match at home or away, in words, where the page prints a letter. */
  atHome: string;
  away: string;
  versus: string;
  unscheduled: string;
  noFixtures: string;
  pageTitle: string;
  noneAhead: string;
  notPublished: string;
  unscheduledCount: (count: number) => string;
  /** The calendar file of the upcoming deadlines: its button, the sentence beside it and
   * the words each event carries in the calendar. */
  calendarAction: string;
  calendarSummary: (gameweek: number) => string;
  calendarDescription: (link: string) => string;
}

const en: FixturesCopy = {
  generalView: "General fixtures",
  teamView: "Team fixtures",
  viewLegend: "Fixtures view",
  weekLegend: "Gameweek",
  clubLegend: "Club",
  atHome: "at home",
  away: "away",
  versus: "v",
  unscheduled: "TBC",
  noFixtures: "No fixtures in this gameweek.",
  pageTitle: "Fixtures",
  noneAhead: "No fixtures left to play.",
  notPublished: "No fixture list has been published yet.",
  unscheduledCount: (count) =>
    count === 1
      ? "1 postponed fixture has no new gameweek yet."
      : `${count} postponed fixtures have no new gameweek yet.`,
  calendarAction: "Add deadlines to your calendar",
  calendarSummary: (gameweek) => `FPL GW${gameweek} deadline`,
  calendarDescription: (link) => `Open SquadOpt before the deadline: ${link}`,
};

const tr: FixturesCopy = {
  generalView: "Genel fikstür",
  teamView: "Takım fikstürü",
  viewLegend: "Fikstür görünümü",
  weekLegend: "Oyun haftası",
  clubLegend: "Takım",
  atHome: "evinde",
  away: "deplasmanda",
  versus: "-",
  unscheduled: "Belli değil",
  noFixtures: "Bu oyun haftasında maç yok.",
  pageTitle: "Fikstür",
  noneAhead: "Oynanacak maç kalmadı.",
  notPublished: "Henüz yayımlanmış bir fikstür yok.",
  unscheduledCount: (count) => `Ertelenen ${count} maçın yeni oyun haftası henüz belli değil.`,
  calendarAction: "Deadline'ları takvime ekle",
  calendarSummary: (gameweek) => `FPL ${gameweek}. hafta son tarihi`,
  calendarDescription: (link) => `Deadline'dan önce SquadOpt'u açın: ${link}`,
};

export const FIXTURES_COPY: Record<Language, FixturesCopy> = { en, tr };
