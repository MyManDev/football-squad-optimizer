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
  });
  it("counts down in days and hours, and closes", () => {
    const now = new Date("2026-08-19T10:00:00Z");
    expect(countdown("2026-08-21T17:30:00Z", now)).toBe("2d 07:30");
    expect(countdown("2026-08-19T11:05:00Z", now)).toBe("01:05");
    expect(countdown("2026-08-19T09:00:00Z", now)).toBe("closed");
    expect(countdown("not a date", now)).toBe("");
    expect(countdown("2026-08-21T17:30:00Z", now, "tr")).toBe("2g 07:30");
    expect(countdown("2026-08-19T09:00:00Z", now, "tr")).toBe("kapandı");
  });
  it("shortens digests", () => {
    expect(shortDigest("abcdefghijklmnop", 8)).toBe("abcdefgh…");
    expect(shortDigest("abc", 8)).toBe("abc");
  });
});
