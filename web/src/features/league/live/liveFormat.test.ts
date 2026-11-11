import { describe, expect, it } from "vitest";

import { clockTime, kickoffShort, signedWhole, wholePoints } from "./liveFormat";

const ISTANBUL = "Europe/Istanbul";

describe("the LIVE page's values", () => {
  it("write a kickoff as its weekday and time in the reader's language and zone", () => {
    expect(kickoffShort("2026-11-21T12:00:00Z", "tr-TR", ISTANBUL)).toBe("Cmt 15:00");
    expect(kickoffShort("2026-11-22T13:30:00Z", "en-GB", "Europe/London")).toBe("Sun 13:30");
    expect(kickoffShort("not a time", "tr-TR")).toBe("not a time");
  });

  it("write a read's time of day", () => {
    expect(clockTime("2026-11-21T12:42:10Z", "tr-TR", ISTANBUL)).toBe("15:42");
  });

  it("write whole points with the signed figures' minus, and a sign where one is asked", () => {
    expect([47, 0, -1].map((value) => wholePoints(value, "tr-TR"))).toEqual(["47", "0", "−1"]);
    expect([8, 0, -12].map((value) => signedWhole(value, "en-GB"))).toEqual(["+8", "0", "−12"]);
  });

  it("never print a per cent sign", () => {
    const printed = [
      kickoffShort("2026-11-21T12:00:00Z", "tr-TR"),
      clockTime("2026-11-21T12:00:00Z", "en-GB"),
      wholePoints(1234, "tr-TR"),
      signedWhole(-7, "tr-TR"),
    ];
    expect(printed.some((text) => text.includes("%"))).toBe(false);
  });
});
