import modePriceList from "../../../../docs/mode_price_list.json";

import type { Messages } from "../../i18n/messages";

export type PlayMode = "saf-puan" | "garantici" | "agresif" | "asiri-agresif";
export const WINDOWS = [1, 3, 5] as const;
export type WindowSize = (typeof WINDOWS)[number];
export type ModePriceStyle = "measured" | "point-cost";

interface PriceCell {
  ahead_by_more_than_five: number;
  behind: number;
  folds: number;
  mean_realized_cost: number;
}

interface ModePriceArtifact {
  grid: {
    agresif: Record<string, PriceCell>;
    asiri_agresif: Record<string, PriceCell>;
    garantici: Record<string, PriceCell>;
  };
}

const artifact = modePriceList as ModePriceArtifact;
const budgetZero = {
  agresif: artifact.grid.agresif["0.0"],
  asiriAgresif: artifact.grid.asiri_agresif["0.0"],
  garantici: artifact.grid.garantici["0.0"],
};

function wholePercent(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}

function decimal(value: number, locale: string): string {
  return value.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export interface PlayModeOption {
  description: string;
  label: string;
  price: string;
  value: PlayMode;
}

export function getPlayModes(
  copy: Messages["decision"]["modes"],
  locale: string,
  priceStyle: ModePriceStyle = "measured",
): readonly PlayModeOption[] {
  if (priceStyle === "point-cost") {
    return [
      {
        value: "saf-puan",
        label: copy.pure,
        description: copy.pureDescription,
        price: copy.expectedPointCost(decimal(0, locale)),
      },
      {
        value: "garantici",
        label: copy.safe,
        description: copy.safeDescription,
        price: copy.expectedPointCost(decimal(budgetZero.garantici.mean_realized_cost, locale)),
      },
      {
        value: "agresif",
        label: copy.aggressive,
        description: copy.aggressiveDescription,
        price: copy.expectedPointCost(decimal(budgetZero.agresif.mean_realized_cost, locale)),
      },
      {
        value: "asiri-agresif",
        label: copy.extreme,
        description: copy.extremeDescription,
        price: copy.expectedPointCost(decimal(budgetZero.asiriAgresif.mean_realized_cost, locale)),
      },
    ];
  }
  return [
    {
      value: "saf-puan",
      label: copy.pure,
      description: copy.pureDescription,
      price: copy.purePrice,
    },
    {
      value: "garantici",
      label: copy.safe,
      description: copy.safeDescription,
      price: `${copy.behind} ${wholePercent(budgetZero.agresif.behind, locale)} → ${wholePercent(budgetZero.garantici.behind, locale)}`,
    },
    {
      value: "agresif",
      label: copy.aggressive,
      description: copy.aggressiveDescription,
      price: `${copy.behind} ${wholePercent(budgetZero.agresif.behind, locale)} · ${copy.cost} ${decimal(budgetZero.agresif.mean_realized_cost, locale)} ${copy.points}`,
    },
    {
      value: "asiri-agresif",
      label: copy.extreme,
      description: copy.extremeDescription,
      price: `${copy.aheadFive} ${wholePercent(budgetZero.asiriAgresif.ahead_by_more_than_five, locale)} · ${copy.cost} ${decimal(budgetZero.asiriAgresif.mean_realized_cost, locale)} ${copy.points}`,
    },
  ];
}

export const MODE_PRICE_FOLDS = budgetZero.garantici.folds;

export function isPlayMode(value: string | null): value is PlayMode {
  return ["saf-puan", "garantici", "agresif", "asiri-agresif"].includes(value ?? "");
}
