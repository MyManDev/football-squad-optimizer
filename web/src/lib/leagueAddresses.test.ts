import { describe, expect, it } from "vitest";

import { isLiveAddress } from "./leagueAddresses";

describe("a LIVE address", () => {
  it("is a member's LIVE page, with or without a closing slash", () => {
    expect(isLiveAddress("/league/352490/members/35249001/live")).toBe(true);
    expect(isLiveAddress("/league/352490/members/35249001/live/")).toBe(true);
    expect(isLiveAddress("/league/members/35249001/live")).toBe(true);
  });

  it("is no other page of the member's", () => {
    expect(isLiveAddress("/league/352490/members/35249001")).toBe(false);
    expect(isLiveAddress("/league/352490/members/35249001/history")).toBe(false);
    expect(isLiveAddress("/league/352490/members/35249001/live/more")).toBe(false);
  });
});
