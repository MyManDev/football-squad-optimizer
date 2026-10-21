import type { Language } from "../../../i18n/messages";

/**
 * The chip timing card's copy, in both languages (#1003, decisions 3 and 5).
 *
 * It names, for each chip the member holds in the current half, the gameweek the rule
 * names and the expected points it adds there, the Triple Captain's player, or the last
 * gameweek of the chip's window, which is the game's own deadline. Nothing else: no
 * threshold, no calendar and no sentence about what the reading rests on.
 */
export interface ChipTimingCopy {
  title: string;
  thisWeek: string;
  gameweek: (gameweek: number) => string;
  notThisWeek: (lastGameweek: number) => string;
  captain: (name: string) => string;
}

const en: ChipTimingCopy = {
  title: "Chip timing",
  thisWeek: "This week",
  gameweek: (gameweek) => `Gameweek ${gameweek}`,
  notThisWeek: (lastGameweek) => `Not this week, until gameweek ${lastGameweek}`,
  captain: (name) => `${name} as captain`,
};

const tr: ChipTimingCopy = {
  title: "Çip zamanı",
  thisWeek: "Bu hafta",
  gameweek: (gameweek) => `${gameweek}. hafta`,
  notThisWeek: (lastGameweek) => `Bu hafta değil, ${lastGameweek}. haftaya kadar`,
  captain: (name) => `kaptan ${name}`,
};

export const CHIP_TIMING_COPY: Record<Language, ChipTimingCopy> = { tr, en };
