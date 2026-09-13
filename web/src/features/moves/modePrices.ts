import modePriceList from "../../../../docs/mode_price_list.json";

import type { Messages } from "../../i18n/messages";

export type PlayMode = "saf-puan" | "garantici" | "agresif" | "asiri-agresif";
export const WINDOWS = [1, 3, 5] as const;
export type WindowSize = (typeof WINDOWS)[number];

interface PriceCell {
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

// The grid prices the three competitive modes against the zero-point budget cell. Saf Puan
// is the control that grid was measured against, so it has no cell of its own: its cost is
// unmeasured, which the copy states in words rather than printing as zero.
const budgetZero = {
  agresif: artifact.grid.agresif["0.0"],
  asiriAgresif: artifact.grid.asiri_agresif["0.0"],
  garantici: artifact.grid.garantici["0.0"],
};

function decimal(value: number, locale: string): string {
  return value.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

// A price is a cost in expected points and nothing else.
function pointsPrice(copy: Messages["decision"]["modes"], cell: PriceCell, locale: string): string {
  return `${copy.cost} ${decimal(cell.mean_realized_cost, locale)} ${copy.points}`;
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
): readonly PlayModeOption[] {
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
      price: pointsPrice(copy, budgetZero.garantici, locale),
    },
    {
      value: "agresif",
      label: copy.aggressive,
      description: copy.aggressiveDescription,
      price: pointsPrice(copy, budgetZero.agresif, locale),
    },
    {
      value: "asiri-agresif",
      label: copy.extreme,
      description: copy.extremeDescription,
      price: pointsPrice(copy, budgetZero.asiriAgresif, locale),
    },
  ];
}

export const MODE_PRICE_FOLDS = budgetZero.garantici.folds;

export function isPlayMode(value: string | null): value is PlayMode {
  return ["saf-puan", "garantici", "agresif", "asiri-agresif"].includes(value ?? "");
}
