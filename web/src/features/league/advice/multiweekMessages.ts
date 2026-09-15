// Loaded with the member route so multiweek copy does not enlarge the entry bundle.
const en = {
  windowComparisonTitle: "Same-window plan comparison",
  windowStrategyDescriptions: {
    "ortak-koru":
      "At least 9 captured rival XI players in our first-week fifteen. No relaxation or later-week constraint.",
    "fark-yarat":
      "At most 5 captured rival XI players in our first-week fifteen. No relaxation or later-week constraint.",
  },
  windowFirstNet: "First week · net",
  windowTotalNet: (weeks: number) => `${weeks} weeks · net total`,
  windowDifference: (value: string) => `Difference from pure points: ${value}`,
  windowRivalBasis: (rival: string, week: number, actual: number, target: string) =>
    `${rival}, captured GW${week} XI: ${actual} in our first-week fifteen; target ${target}.`,
  windowComparisonNote: "Net: XI + captain − hits; returned-plan difference, not proven cost.",
};

const tr: typeof en = {
  windowComparisonTitle: "Aynı pencere için plan karşılaştırması",
  windowStrategyDescriptions: {
    "ortak-koru":
      "Rakibin kayıtlı ilk 11'inden ilk hafta 15'imizde en az 9 oyuncu. Sınır gevşetilmez, sonraki haftalara uygulanmaz.",
    "fark-yarat":
      "Rakibin kayıtlı ilk 11'inden ilk hafta 15'imizde en fazla 5 oyuncu. Sınır gevşetilmez, sonraki haftalara uygulanmaz.",
  },
  windowFirstNet: "İlk hafta · net",
  windowTotalNet: (weeks) => `${weeks} hafta · net toplam`,
  windowDifference: (value) => `Saf puana göre fark: ${value}`,
  windowRivalBasis: (rival, week, actual, target) =>
    `${rival}, H${week} kayıtlı ilk 11: ilk hafta 15'imizde ${actual} ortak; hedef ${target}.`,
  windowComparisonNote:
    "Net: ilk 11 + kaptan − cezalar; bulunan planların farkı, kesin maliyet değil.",
};

export const MULTIWEEK_MESSAGES = { en, tr };
