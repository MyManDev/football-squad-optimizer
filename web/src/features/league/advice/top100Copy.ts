import type { Language } from "../../../i18n/messages";

/**
 * The Top 100 influence copy, in both languages.
 *
 * It lives beside the components that read it, like the manager's-word copy, so it loads
 * with the member page and not with every first visit. The honesty sweep
 * (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions called.
 *
 * What it may say: the setting is a preference, what it does to the points the plan is
 * chosen on, what it gives up in the base model, and that no gain from it was measured.
 * It never writes the weight as a share, never names a best setting, and never states a
 * weighted number as the member's own.
 */
export interface Top100Copy {
  legend: string;
  zero: string;
  help: string;
  published: string;
  onlyBaseline: string;
  notOffered: string;
  unavailableReasons: Record<string, string>;
  wordNotSolved: string;
  title: string;
  weightLine: (weight: number) => string;
  notStart: string;
  saturation: string;
  honesty: string;
  unchanged: string;
  changed: string;
  cost: (points: string) => string;
  costAtMost: (points: string) => string;
  combinedCost: (points: string) => string;
  combinedCostAtMost: (points: string) => string;
  unproven: string;
  moveReason: string;
  limit: (weight: number) => string;
}

const en: Top100Copy = {
  legend: "Top 100 influence",
  zero: "0 (published plan)",
  help: "Players in last week's Top 100 starting elevens get extra points in proportion to how many of those teams picked them: a player all 100 teams picked gets the setting's value in points for every 100 base points. The plan is chosen on those points and every number on the card is the base model's. 0 switches it off and shows the published plan.",
  published: "This week's published plan carries no Top 100 influence (0).",
  onlyBaseline: "One-week pure-points plan only.",
  notOffered:
    "The setting in the link is not offered for this member in this publish; the plan at 0 is shown.",
  unavailableReasons: {
    no_top100_this_run: "This publish read no Top 100 selections; only 0 is available.",
    top100_inputs_refused:
      "This publish could not verify the Top 100 selections; only 0 is available.",
    published_plan_carries_top100:
      "This publish's plan already carries a Top 100 influence; the settings are off.",
    not_solved_for_member: "No setting was solved for this member in this publish.",
  },
  wordNotSolved: "Settings without a file for the manager's word are off while the word is on.",
  title: "Top 100 influence",
  weightLine: (weight) => `Setting: ${weight} (your choice).`,
  notStart:
    "This is the Top 100 teams' previous-week choice of eleven, not a measurement of whether a player will start.",
  saturation: "A higher setting can return the same plan.",
  honesty:
    "This is the price of a preference; no points gain from this setting has been measured. The points on the card are the base model's, without the setting.",
  unchanged: "This setting did not change your plan this week.",
  changed: "This setting changed your plan; the price is stated above.",
  cost: (points) =>
    `This setting gives up ~${points} expected points in the base model against the pure-points plan at 0, hits included.`,
  costAtMost: (points) =>
    `This setting gives up at most ${points} expected points in the base model against the pure-points plan at 0, hits included.`,
  combinedCost: (points) =>
    `The manager's word and this setting together give up ~${points} expected points in the base model against the pure-points plan with both off, hits included.`,
  combinedCostAtMost: (points) =>
    `The manager's word and this setting together give up at most ${points} expected points in the base model against the pure-points plan with both off, hits included.`,
  unproven:
    "The solver found this plan without finishing its proof, so the price above is stated as at most.",
  moveReason: "In the plan because of the Top 100 influence.",
  limit: (weight) =>
    `The plan was chosen with the Top 100 influence at ${weight}; every expected-points number here is the base model's, without it.`,
};

const tr: Top100Copy = {
  legend: "Top 100 etkisi",
  zero: "0 (yayınlanan plan)",
  help: "Önceki haftada Top 100 takımlarının ilk 11'ine aldığı oyunculara, onları alan takım sayısıyla orantılı ek puan konur: 100 takımın hepsinin aldığı oyuncuda her 100 temel puana ayar kadar puan. Plan bu puanlarla seçilir, karttaki her sayı temel modelindir. 0 kapatır ve yayınlanan planı gösterir.",
  published: "Bu hafta yayınlanan plan Top 100 etkisi içermez (0).",
  onlyBaseline: "Yalnız bir haftalık saf puan planında.",
  notOffered: "Bağlantıdaki ayar bu yayında bu üye için sunulmuyor; 0 ayarlı plan gösteriliyor.",
  unavailableReasons: {
    no_top100_this_run: "Bu yayında Top 100 seçimleri okunmadı; yalnız 0 var.",
    top100_inputs_refused: "Bu yayında Top 100 seçimleri doğrulanamadı; yalnız 0 var.",
    published_plan_carries_top100:
      "Bu yayının planı zaten bir Top 100 etkisi içeriyor; ayarlar kapalı.",
    not_solved_for_member: "Bu yayında bu üye için hiçbir ayar çözülmedi.",
  },
  wordNotSolved: "Hocanın sözü açıkken, söz için dosyası olmayan ayarlar kapalı.",
  title: "Top 100 etkisi",
  weightLine: (weight) => `Ayar: ${weight} (senin seçimin).`,
  notStart:
    "Bu, Top 100 takımlarının önceki haftaki ilk 11 tercihidir; oyuncunun maçta başlayıp başlamayacağının ölçümü değildir.",
  saturation: "Daha yüksek bir ayar aynı planı verebilir.",
  honesty:
    "Bu bir tercihin bedelidir; bu ayarın puan kazandırdığı ölçülmedi. Karttaki puanlar ayarsız temel modelin puanlarıdır.",
  unchanged: "Bu ayar bu hafta planını değiştirmedi.",
  changed: "Bu ayar planını değiştirdi; bedeli yukarıda yazılı.",
  cost: (points) =>
    `Bu ayar, 0 ayarlı saf puan planına göre temel modelde ~${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  costAtMost: (points) =>
    `Bu ayar, 0 ayarlı saf puan planına göre temel modelde en fazla ${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  combinedCost: (points) =>
    `Hocanın sözü ve bu ayar birlikte, ikisi de kapalı saf puan planına göre temel modelde ~${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  combinedCostAtMost: (points) =>
    `Hocanın sözü ve bu ayar birlikte, ikisi de kapalı saf puan planına göre temel modelde en fazla ${points} beklenen puandan vazgeçmek demek, cezalar dahil.`,
  unproven: "Çözücü bu planı ispatını bitirmeden buldu; bedel yukarıda en fazla olarak yazılı.",
  moveReason: "Top 100 etkisi nedeniyle planda.",
  limit: (weight) =>
    `Plan Top 100 etkisi ${weight} iken seçildi; buradaki her beklenen puan, etki olmadan temel modelindir.`,
};

export const TOP100_COPY: Record<Language, Top100Copy> = { tr, en };

/** The sentence for an index reason; an unknown code reads as "nothing was read". */
export function top100Unavailable(copy: Top100Copy, reason: string | null): string {
  return (
    (reason !== null ? copy.unavailableReasons[reason] : undefined) ??
    copy.unavailableReasons.no_top100_this_run
  );
}

/**
 * The producer's stated limit for a weighted document, with its weight read back. The
 * sentence carries a number, so it cannot be a key in the fixed stated-limits table.
 */
const TOP100_LIMIT =
  /^The plan was chosen with the Top 100 influence at (5|10|20|30|40|50); every expected-points number in this document is the base model's, without it\.$/;

export function top100LimitWeight(sentence: string): number | null {
  const match = TOP100_LIMIT.exec(sentence);
  return match ? Number(match[1]) : null;
}
