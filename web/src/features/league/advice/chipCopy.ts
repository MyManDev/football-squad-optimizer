import type { Language } from "../../../i18n/messages";

/**
 * The chip choice copy, in both languages.
 *
 * It lives beside the components that read it, like the manager's-word and Top 100 copy,
 * so it loads with the member page and not with every first visit. The honesty sweep
 * (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions called.
 *
 * What it may say: what the chip week is expected to score above the member's own plan
 * without it, why the game keeps a chip off, and what to change to reach one. It never says
 * this is the week to play the chip, because what the chip would be worth in a later
 * gameweek is not measured anywhere.
 */
export interface ChipCopy {
  legend: string;
  none: string;
  onlyBaseline: string;
  blockedBySwitches: string;
  switchesOff: string;
  unavailableReasons: Record<string, string>;
  chipReasons: Record<string, string>;
  chipReasonLine: (name: string, reason: string) => string;
  title: string;
  gain: (points: string) => string;
  freeHit: string;
}

const en: ChipCopy = {
  legend: "Chip",
  none: "None",
  onlyBaseline: "Switch to the one-week Most points plan for this.",
  blockedBySwitches:
    "Switch the manager's word off and set the Top 100 influence to 0 to choose a chip.",
  switchesOff: "Choose None under Chip to use them.",
  unavailableReasons: {
    no_chip_left: "This member has no chip that can be played this gameweek.",
  },
  chipReasons: {
    already_played: "already played",
    window_not_open: "its window is not open this gameweek",
    free_hit_played_last_gameweek:
      "a Free Hit was played last gameweek, and the game does not allow two in a row",
  },
  chipReasonLine: (name, reason) => `${name}: ${reason}.`,
  title: "Chip choice",
  gain: (points) => `~${points} expected points this gameweek.`,
  freeHit:
    "A Free Hit squad is for this gameweek only; the squad you hold now returns at the next deadline.",
};

const tr: ChipCopy = {
  legend: "Çip",
  none: "Yok",
  onlyBaseline: "Bunun için bir haftalık En çok puan planına geç.",
  blockedBySwitches: "Çip seçmek için hocanın sözünü kapat ve Top 100 etkisini 0 yap.",
  switchesOff: "Bunları kullanmak için Çip bölümünde Yok'u seç.",
  unavailableReasons: {
    no_chip_left: "Bu üyenin bu hafta oynayabileceği çip yok.",
  },
  chipReasons: {
    already_played: "daha önce oynandı",
    window_not_open: "bu hafta oynanabileceği dönem açık değil",
    free_hit_played_last_gameweek:
      "geçen hafta Free Hit oynandı, oyun üst üste iki hafta oynatmıyor",
  },
  chipReasonLine: (name, reason) => `${name}: ${reason}.`,
  title: "Çip seçimi",
  gain: (points) => `Bu hafta ~${points} beklenen puan.`,
  freeHit:
    "Free Hit kadrosu yalnız bu hafta içindir; bir sonraki haftada şimdiki kadron geri gelir.",
};

export const CHIP_COPY: Record<Language, ChipCopy> = { tr, en };

/** The sentence for an index reason; a reason this page has no sentence for says nothing. */
export function chipsUnavailable(copy: ChipCopy, reason: string | null): string | null {
  return reason !== null && Object.hasOwn(copy.unavailableReasons, reason)
    ? (copy.unavailableReasons[reason] ?? null)
    : null;
}

/** Why the game keeps one chip off, in the member's language; any other code says nothing. */
export function chipReason(copy: ChipCopy, reason: string | undefined): string | null {
  return reason !== undefined && Object.hasOwn(copy.chipReasons, reason)
    ? (copy.chipReasons[reason] ?? null)
    : null;
}
