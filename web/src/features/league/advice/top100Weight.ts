/** Personal preferences; the published calculation keeps its own declared weight. */
export const TOP100_WEIGHTS: readonly number[] = [0, 5, 10, 20, 30, 40, 50];

export const TOP100_MESSAGES = {
  tr: {
    label: "Top100 etkisi",
    published: "Yayınlanan ayarı kullan",
    help: "Önceki haftanın Top100 ilk 11 tercihlerini ne kadar dikkate alalım? %0 kapatır. Seçilen oran, 100 takımın tamamının seçtiği oyuncuya uygulanabilecek en yüksek artıştır; puan kazancı garantisi değildir.",
    offline: "Kişisel oran için hesaplama servisi gerekli.",
    unavailable:
      "Bu haftanın hesaplama verisinde doğrulanmış Top100 seçimleri yok. Yayınlanan ayarı kullanabilir veya verinin güncellenmesini bekleyebilirsin.",
    result: (weight: number, personal: boolean) =>
      `Top100 etkisi: en fazla %${weight} · ${personal ? "kişisel seçim" : "yayınlanan ayar"}`,
  },
  en: {
    label: "Top100 influence",
    published: "Use published setting",
    help: "How much should last week's Top100 starting XI choices influence the recommendation? 0% turns it off. The selected percentage is the maximum uplift for a player picked by all 100 teams, not a guaranteed points gain.",
    offline: "A personal weight requires the compute service.",
    unavailable:
      "This week's calculation has no verified Top100 selections. Use the published setting or wait for updated inputs.",
    result: (weight: number, personal: boolean) =>
      `Top100 influence: up to ${weight}% · ${personal ? "personal choice" : "published setting"}`,
  },
};
