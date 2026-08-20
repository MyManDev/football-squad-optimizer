import modePriceList from "../../../../docs/mode_price_list.json";

export type PlayMode = "saf-puan" | "garantici" | "agresif" | "asiri-agresif";

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

function wholePercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function decimal(value: number): string {
  return value.toFixed(1).replace(".", ",");
}

export interface PlayModeOption {
  description: string;
  label: string;
  price: string;
  value: PlayMode;
}

export const PLAY_MODES: readonly PlayModeOption[] = [
  {
    value: "saf-puan",
    label: "Saf Puan",
    description: "Rakipten bağımsız en yüksek beklenen puanı hedefler.",
    price: "Rakip bütçesi yok",
  },
  {
    value: "garantici",
    label: "Garantici",
    description: "Lig içinde geride kalma ihtimalini azaltmayı hedefler.",
    price: `P(geride) ${wholePercent(budgetZero.agresif.behind)} → ${wholePercent(budgetZero.garantici.behind)}`,
  },
  {
    value: "agresif",
    label: "Agresif",
    description: "Rakibin önüne geçmeye odaklanan dengeli rekabet modu.",
    price: `P(geride) ${wholePercent(budgetZero.agresif.behind)} · maliyet ${decimal(budgetZero.agresif.mean_realized_cost)} puan`,
  },
  {
    value: "asiri-agresif",
    label: "Aşırı Agresif",
    description: "Beş puandan büyük fark yaratabilecek daha sert kararları arar.",
    price: `P(5+ önde) ${wholePercent(budgetZero.asiriAgresif.ahead_by_more_than_five)} · maliyet ${decimal(budgetZero.asiriAgresif.mean_realized_cost)} puan`,
  },
];

export const MODE_PRICE_FOLDS = budgetZero.garantici.folds;

export function isPlayMode(value: string | null): value is PlayMode {
  return PLAY_MODES.some((mode) => mode.value === value);
}
