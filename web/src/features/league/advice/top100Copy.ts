import type { Language } from "../../../i18n/messages";

/**
 * The Top 100 influence copy, in both languages.
 *
 * It lives beside the components that read it, like the manager's-word copy, so it loads
 * with the member page and not with every first visit. The honesty sweep
 * (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions called.
 *
 * What it may say: what the setting does to the points the plan is chosen on, what it gives
 * up, and whether it moved the plan. It never writes the weight as a share, never names a
 * best setting, and never states a weighted number as the member's own.
 */
export interface Top100Copy {
  windowComparisonTitle: string;
  windowSelectedTotal: string;
  windowPureTotal: string;
  legend: string;
  zero: string;
  help: string;
  strategyCost: (points: string) => string;
  strategyCostAtMost: (points: string) => string;
  title: string;
  unchanged: string;
  changed: string;
  cost: (points: string) => string;
  costAtMost: (points: string) => string;
  combinedCost: (points: string) => string;
  combinedCostAtMost: (points: string) => string;
  moveReason: string;
}

const en: Top100Copy = {
  windowComparisonTitle: "Window totals",
  windowSelectedTotal: "Selected plan",
  windowPureTotal: "Pure-points plan",
  legend: "Top 100 influence",
  zero: "0 (off)",
  help: "Players in last week's Top 100 starting elevens count for more in proportion to how many of those teams started them. 0 switches it off.",
  strategyCost: (points) =>
    `This strategy and this setting together give up ~${points} expected points.`,
  strategyCostAtMost: (points) =>
    `This strategy and this setting together give up at most ${points} expected points.`,
  title: "Top 100 influence",
  unchanged: "This setting did not change your plan this week.",
  changed: "This setting changed your plan.",
  cost: (points) => `This setting gives up ~${points} expected points.`,
  costAtMost: (points) => `This setting gives up at most ${points} expected points.`,
  combinedCost: (points) =>
    `The manager's word and this setting together give up ~${points} expected points.`,
  combinedCostAtMost: (points) =>
    `The manager's word and this setting together give up at most ${points} expected points.`,
  moveReason: "In the plan because of the Top 100 influence.",
};

const tr: Top100Copy = {
  windowComparisonTitle: "Pencere toplamları",
  windowSelectedTotal: "Seçilen plan",
  windowPureTotal: "Saf puan planı",
  legend: "Top 100 etkisi",
  zero: "0 (kapalı)",
  help: "Önceki haftada Top 100 takımlarının ilk 11'ine aldığı oyuncular, onları ilk 11'ine alan takım sayısıyla orantılı olarak daha değerli sayılır. 0 etkiyi kapatır.",
  strategyCost: (points) =>
    `Bu strateji ve bu ayar birlikte ~${points} beklenen puandan vazgeçmek demek.`,
  strategyCostAtMost: (points) =>
    `Bu strateji ve bu ayar birlikte en fazla ${points} beklenen puandan vazgeçmek demek.`,
  title: "Top 100 etkisi",
  unchanged: "Bu ayar bu hafta planını değiştirmedi.",
  changed: "Bu ayar planını değiştirdi.",
  cost: (points) => `Bu ayar ~${points} beklenen puandan vazgeçmek demek.`,
  costAtMost: (points) => `Bu ayar en fazla ${points} beklenen puandan vazgeçmek demek.`,
  combinedCost: (points) =>
    `Hocanın sözü ve bu ayar birlikte ~${points} beklenen puandan vazgeçmek demek.`,
  combinedCostAtMost: (points) =>
    `Hocanın sözü ve bu ayar birlikte en fazla ${points} beklenen puandan vazgeçmek demek.`,
  moveReason: "Top 100 etkisi nedeniyle planda.",
};

export const TOP100_COPY: Record<Language, Top100Copy> = { tr, en };
