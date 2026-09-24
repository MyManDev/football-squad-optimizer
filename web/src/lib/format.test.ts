import { describe, expect, it } from "vitest";

import {
  countdown,
  deadlineLong,
  deadlineShort,
  money,
  percent,
  pounds,
  shortDigest,
  signedPoints,
} from "./format";

describe("format", () => {
  it("formats tenths as pounds", () => {
    expect(pounds(1000)).toBe("£100.0m");
    expect(pounds(55)).toBe("£5.5m");
    expect(pounds(-5)).toBe("-£0.5m");
  });
  it("writes money in the reader's notation, one decimal, from tenths", () => {
    // The league's own way of writing a bank: comma decimal, no currency sign.
    expect(money(8, "tr-TR")).toBe("0,8m");
    expect(money(1014, "tr-TR")).toBe("101,4m");
    expect(money(0, "tr-TR")).toBe("0,0m");
    expect(money(8, "en-GB")).toBe("£0.8m");
    expect(money(1000)).toBe("£100.0m");
    expect(money(-5, "tr-TR")).toBe("-0,5m");
    expect(money(-5, "en-GB")).toBe("-£0.5m");
    // Large values are not grouped: '1000,0m', never '1.000,0m'.
    expect(money(10000, "tr-TR")).toBe("1000,0m");
  });
  it("writes a deadline in Istanbul time, long and short, in both languages", () => {
    // The GW6 deadline as fixtures.json publishes it: 10:00 UTC is 13:00 in Istanbul.
    const deadline = "2026-10-10T10:00:00Z";
    expect(deadlineLong(deadline, "tr-TR")).toBe("10 Ekim Cumartesi · 13:00");
    expect(deadlineShort(deadline, "tr-TR")).toBe("10 Eki Cmt 13:00");
    expect(deadlineLong(deadline, "en-GB")).toBe("Saturday 10 October · 13:00");
    expect(deadlineShort(deadline, "en-GB")).toBe("Sat 10 Oct 13:00");
  });
  it("takes the date from Istanbul, not from UTC or the device", () => {
    // 22:30 UTC on Saturday is already 01:30 on Sunday in Istanbul.
    expect(deadlineLong("2026-10-10T22:30:00Z", "tr-TR")).toBe("11 Ekim Pazar · 01:30");
    expect(deadlineShort("2026-10-10T22:30:00Z", "en-GB")).toBe("Sun 11 Oct 01:30");
    // Hours keep two digits and midnight is 00, never 24.
    expect(deadlineShort("2026-12-31T21:00:00Z", "tr-TR")).toBe("1 Oca Cum 00:00");
  });
  it("returns an unreadable deadline as it was given", () => {
    expect(deadlineLong("not a date", "tr-TR")).toBe("not a date");
    expect(deadlineShort("", "en-GB")).toBe("");
  });
  it("signs points and formats probabilities", () => {
    expect(signedPoints(1.25)).toBe("+1.3");
    expect(signedPoints(-2)).toBe("−2.0");
    expect(signedPoints(0)).toBe("0.0");
    expect(percent(0.4)).toBe("40%");
    expect(percent(0.74, 0, "tr-TR")).toBe("%74");
    expect(percent(0.74, 0, "en-GB")).toBe("74%");
  });
  it("never signs a figure that rounds to zero", () => {
    // A minus in front of a zero reads as a loss the printed digits do not show. The
    // sign belongs to the number after rounding, not to the number before it.
    expect(signedPoints(-0.04)).toBe("0.0");
    expect(signedPoints(0.04)).toBe("0.0");
    expect(signedPoints(-0)).toBe("0.0");
    expect(signedPoints(-0.004, 2)).toBe("0.00");
    expect(signedPoints(-0.04, 2)).toBe("−0.04");
    expect(signedPoints(-0.06)).toBe("−0.1");
    expect(signedPoints(-0.04, 1, "tr-TR")).toBe("0,0");
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
