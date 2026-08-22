import { describe, expect, it } from "vitest";

import { countdown, percent, pounds, shortDigest, signedPoints } from "./format";

describe("format", () => {
  it("formats tenths as pounds", () => {
    expect(pounds(1000)).toBe("£100.0m");
    expect(pounds(55)).toBe("£5.5m");
    expect(pounds(-5)).toBe("-£0.5m");
  });
  it("signs points and formats probabilities", () => {
    expect(signedPoints(1.25)).toBe("+1.3");
    expect(signedPoints(-2)).toBe("−2.0");
    expect(signedPoints(0)).toBe("0.0");
    expect(percent(0.4)).toBe("40%");
    expect(percent(0.74, 0, "tr-TR")).toBe("%74");
    expect(percent(0.74, 0, "en-GB")).toBe("74%");
  });
  it("counts down in days and hours, and closes", () => {
    const now = new Date("2026-08-19T10:00:00Z");
    const en = { closed: "closed", day: "d" };
    const tr = { closed: "kapandı", day: "g" };
    expect(countdown("2026-08-21T17:30:00Z", now, en)).toEqual({
      isClosed: false,
      text: "2d 07:30",
    });
    expect(countdown("2026-08-19T11:05:00Z", now, en)).toEqual({
      isClosed: false,
      text: "01:05",
    });
    expect(countdown("2026-08-19T09:00:00Z", now, en)).toEqual({
      isClosed: true,
      text: "closed",
    });
    expect(countdown("not a date", now, en)).toEqual({ isClosed: false, text: "" });
    expect(countdown("2026-08-21T17:30:00Z", now, tr).text).toBe("2g 07:30");
    expect(countdown("2026-08-19T09:00:00Z", now, tr)).toEqual({
      isClosed: true,
      text: "kapandı",
    });
  });
  it("shortens digests", () => {
    expect(shortDigest("abcdefghijklmnop", 8)).toBe("abcdefgh…");
    expect(shortDigest("abc", 8)).toBe("abc");
  });
});
