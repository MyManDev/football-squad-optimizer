import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fixtureDay, fixtureTime } from "./kickoff";

describe("a kickoff in Istanbul", () => {
  beforeEach(() => {
    vi.stubEnv("TZ", "Europe/Istanbul");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("prints the local day, past midnight", () => {
    expect(fixtureDay("2026-09-20T22:30:00Z", "tr-TR")).toBe("21 Eyl Pzt");
    expect(fixtureDay("2026-09-20T22:30:00Z", "en-GB")).toBe("Mon 21 Sept");
  });

  it("prints a 24-hour local time", () => {
    expect(fixtureTime("2026-09-20T13:00:00Z", "tr-TR")).toBe("16:00");
    expect(fixtureTime("2026-09-20T13:00:00Z", "en-GB")).toBe("16:00");
  });
});
