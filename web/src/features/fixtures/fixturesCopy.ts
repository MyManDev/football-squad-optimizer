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
  pageLede: string;
  pastTitle: string;
  noPast: string;
  notPublished: string;
  unscheduledCount: (count: number) => string;
  /** The calendar file of the upcoming deadlines: its button, the sentence beside it and
   * the words each event carries in the calendar. */
  calendarAction: string;
  calendarNote: string;
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
  pageLede: "The schedule and the results, as the game published them. Times are your local time.",
  pastTitle: "Past gameweeks",
  noPast: "No gameweek has been played yet.",
  notPublished: "No fixture list has been published yet.",
  unscheduledCount: (count) =>
    count === 1
      ? "1 postponed fixture has no new gameweek yet and is not listed."
      : `${count} postponed fixtures have no new gameweek yet and are not listed.`,
  calendarAction: "Add deadlines to your calendar",
  calendarNote:
    "Your calendar app reminds you two hours before each deadline. If a deadline moves, download the file again.",
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
  pageLede: "Oyunun yayımladığı maç programı ve sonuçlar. Saatler bulunduğunuz yerin saatidir.",
  pastTitle: "Geçmiş haftalar",
  noPast: "Henüz oynanmış bir oyun haftası yok.",
  notPublished: "Henüz yayımlanmış bir fikstür yok.",
  unscheduledCount: (count) =>
    `Ertelenen ${count} maçın yeni oyun haftası henüz belli değil; listede yer almıyor.`,
  calendarAction: "Deadline'ları takvime ekle",
  calendarNote:
    "Takvim uygulamanız her deadline'dan iki saat önce hatırlatır. Bir deadline değişirse dosyayı yeniden indirin.",
  calendarSummary: (gameweek) => `FPL ${gameweek}. hafta son tarihi`,
  calendarDescription: (link) => `Deadline'dan önce SquadOpt'u açın: ${link}`,
};

export const FIXTURES_COPY: Record<Language, FixturesCopy> = { en, tr };
