/** The per-tab member claim: kept in sessionStorage, read back exactly, never in localStorage. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readMemberClaim, subscribeMemberClaim, writeMemberClaim } from "./memberClaim";

const CLAIM = {
  leagueId: 352490,
  entryId: 35249001,
  managerName: "Deniz Aral",
  teamName: "North Stand Notes",
  leagueName: "SquadOpt Classic League",
};

beforeEach(() => {
  writeMemberClaim(null);
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("the member claim", () => {
  it("round-trips through the tab's sessionStorage and never touches localStorage", () => {
    writeMemberClaim(CLAIM);
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toEqual(CLAIM);
    expect(readMemberClaim()).toEqual(CLAIM);
    expect(localStorage.length).toBe(0);
  });

  it.each([
    ["text that is not JSON", "{not json"],
    ["an array", JSON.stringify([CLAIM])],
    ["missing ids", JSON.stringify({ managerName: "Deniz Aral" })],
    ["a zero league", JSON.stringify({ ...CLAIM, leagueId: 0 })],
    ["a negative entry", JSON.stringify({ ...CLAIM, entryId: -4 })],
    ["a fractional entry", JSON.stringify({ ...CLAIM, entryId: 1.5 })],
    ["an unsafe league", JSON.stringify({ ...CLAIM, leagueId: Number.MAX_SAFE_INTEGER + 2 })],
    ["ids written as text", JSON.stringify({ ...CLAIM, leagueId: "352490" })],
  ])("reads %s as nobody", (_, raw) => {
    sessionStorage.setItem("squadopt.member", raw);
    expect(readMemberClaim()).toBeNull();
  });

  it("keeps a name only when it is text, an empty one included", () => {
    sessionStorage.setItem(
      "squadopt.member",
      JSON.stringify({ ...CLAIM, managerName: 7, teamName: "", leagueName: { name: "x" } }),
    );
    expect(readMemberClaim()).toEqual({
      ...CLAIM,
      managerName: null,
      teamName: "",
      leagueName: null,
    });
  });

  it("removes the key when dropped and announces every write", () => {
    const heard = vi.fn();
    const stop = subscribeMemberClaim(heard);
    writeMemberClaim(CLAIM);
    writeMemberClaim(null);
    expect(sessionStorage.getItem("squadopt.member")).toBeNull();
    expect(readMemberClaim()).toBeNull();
    expect(heard).toHaveBeenCalledTimes(2);
    stop();
    writeMemberClaim(CLAIM);
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it("drops anything that is not a claim when asked to write it", () => {
    writeMemberClaim(CLAIM);
    writeMemberClaim({ ...CLAIM, entryId: 0 });
    expect(readMemberClaim()).toBeNull();
    expect(sessionStorage.getItem("squadopt.member")).toBeNull();
  });

  it("reads the same stored text as the same object", () => {
    writeMemberClaim(CLAIM);
    expect(readMemberClaim()).toBe(readMemberClaim());
  });

  it("keeps the claim in memory for the page's life when storage refuses it", async () => {
    vi.resetModules();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const fresh = await import("./memberClaim");
    expect(fresh.readMemberClaim()).toBeNull();
    fresh.writeMemberClaim(CLAIM);
    expect(fresh.readMemberClaim()).toEqual(CLAIM);
    fresh.writeMemberClaim(null);
    expect(fresh.readMemberClaim()).toBeNull();
  });

  it("forgets the selection older versions remembered across visits", async () => {
    localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: 35249001 }));
    vi.resetModules();
    await import("./memberClaim");
    expect(localStorage.getItem("squadopt.viewer")).toBeNull();
  });
});
