import { describe, expect, it } from "vitest";
import { AS_A_CHANCE } from "./honesty";

describe("the shared product-copy honesty guard", () => {
  it.each([
    "chance",
    "likelihood",
    "odds",
    "probability",
    "probabilities",
    "quantile",
    "spread",
    "percentage",
    "25%",
    "P(0.5)",
    "olasılık",
    "olasılığı",
    "olasılığını",
    "olasılıkla",
    "ihtimal",
    "ihtimali",
    "şans",
    "yüzde",
    "kantil",
    "yayılım",
  ])("rejects %s, including Turkish inflections", (word) => {
    expect(word).toMatch(AS_A_CHANCE);
  });

  // The three price and stat lines this guard was extended to catch, exactly as they were
  // rendered on the live site, in both languages.
  it.each([
    "P(behind) 32% → 18%",
    "P(geride) %46 → %27",
    "P(5+ ahead) 14% · cost 1.8 points",
    "P(5+ önde) %19 · maliyet 1,5 puan",
    "Lower 10% Tail 42.3",
    "Alt %10 Kuyruk 42,3",
    "Lower Tail: Not Evaluated",
    "Alt Kuyruk Değerlendirilmedi",
    "Aims to reduce the chance of falling behind in the league.",
    "Lig içinde geride kalma ihtimalini azaltmayı hedefler.",
  ])("rejects the copy that used to be published: %s", (line) => {
    expect(line).toMatch(AS_A_CHANCE);
  });

  // A bare per cent sign is still a violation on its own; only ownership wording excuses one.
  it.each(["32%", "%32", "90% [12%, 30%]", "yüzdesi", "yüzdelik"])(
    "rejects a per cent sign in no other company: %s",
    (line) => {
      expect(line).toMatch(AS_A_CHANCE);
    },
  );

  it.each([
    "Free transfers: unknown",
    "Ücretsiz transfer: bilinmiyor",
    "No chip information",
    "Chip bilgisi yok",
    "Captain shortfall",
    "Kaptan açığı",
    "cost 1.8 points",
    "maliyet 1,5 puan",
    "No rival budget, no measured cost",
    "Rakip bütçesi yok, ölçülmüş maliyet yok",
  ])("accepts factual copy: %s", (copy) => {
    expect(copy).not.toMatch(AS_A_CHANCE);
  });

  // Ownership share is a fact the game publishes, so the per cent sign that carries it is not
  // a claim of ours. The exception is wording, not a list of blessed strings.
  it.each([
    "starters owned by 12% or less",
    "%12 veya daha az sahiplikli ilk 11 oyuncuları",
    "; the starting eleven averages 34% ownership",
    "; ilk on birin ortalama sahipliği %34",
  ])("accepts an ownership share: %s", (copy) => {
    expect(copy).not.toMatch(AS_A_CHANCE);
  });

  // "yüzden" means therefore and merely begins with the six letters of "yüzde".
  it.each([
    "İlk oyun haftasında kadro sıfırdan kurulur; bu yüzden yapılacak transfer yoktur.",
    "Bu yayın sıralamada bir komşu belirlemedi, o yüzden yerine bir rakip seçilmiyor.",
  ])("accepts the causal word yüzden: %s", (copy) => {
    expect(copy).not.toMatch(AS_A_CHANCE);
  });

  // "Kuyruk" is a distribution tail; "Kuyrukta" is the compute queue, and "detail" is English.
  it.each(["Kuyrukta", "Record Details", "This record does not provide enough plan detail."])(
    "accepts a word that merely contains one: %s",
    (copy) => {
      expect(copy).not.toMatch(AS_A_CHANCE);
    },
  );
});
