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

  it.each([
    "Free transfers: unknown",
    "Ücretsiz transfer: bilinmiyor",
    "No chip information",
    "Chip bilgisi yok",
    "Captain shortfall",
    "Kaptan açığı",
  ])("accepts factual copy: %s", (copy) => {
    expect(copy).not.toMatch(AS_A_CHANCE);
  });
});
