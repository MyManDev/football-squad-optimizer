/** The one identity interface: the league entered, the member claimed in it, and the roster check. */

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readMemberClaim, writeMemberClaim } from "./memberClaim";
import { readChosenLeague, writeChosenLeague } from "./useChosenLeague";
import { useLeagueIdentity, type Roster } from "./useLeagueIdentity";

const A = 352490;
const B = 7;
const DENIZ = {
  leagueId: A,
  entryId: 35249001,
  managerName: "Deniz Aral",
  teamName: "North Stand Notes",
  leagueName: "SquadOpt Classic League",
};
const ROSTER: Roster = {
  leagueName: "SquadOpt Classic League",
  entries: [
    { entryId: 35249001, managerName: "Deniz Aral", teamName: "North Stand Notes" },
    { entryId: 35249002, managerName: "Mert Işık", teamName: "Half Space" },
  ],
};

beforeEach(() => {
  writeMemberClaim(null);
  writeChosenLeague(null);
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Counts the claim's writes from here on. */
function countClaimWrites() {
  const heard = vi.fn();
  window.addEventListener("squadopt:member-changed", heard);
  return heard;
}

describe("the visitor's identity", () => {
  it("is nobody in no league before anything is entered", () => {
    const { result } = renderHook(() => useLeagueIdentity());
    expect(result.current).toMatchObject({ leagueId: null, member: null, status: "no-league" });
  });

  it("enters a league, then claims a member in it as a self-selected, unverified member", () => {
    const { result } = renderHook(() => useLeagueIdentity());
    act(() => result.current.chooseLeague(A));
    expect(result.current).toMatchObject({ leagueId: A, member: null, status: "unclaimed" });
    act(() => result.current.claimMember(DENIZ));
    expect(result.current.status).toBe("claimed");
    expect(result.current.member).toEqual({
      ...DENIZ,
      verified: false,
      source: "self-selected",
    });
  });

  it("reads the claim back from the tab's storage after the module is loaded again", async () => {
    writeMemberClaim(DENIZ);
    vi.resetModules();
    const fresh = await import("./useLeagueIdentity");
    const { result } = renderHook(() => fresh.useLeagueIdentity(A));
    expect(result.current.member?.entryId).toBe(DENIZ.entryId);
    expect(result.current.status).toBe("claimed");
  });

  it("is nobody in another league than the one the claim was made in", () => {
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity(B));
    expect(result.current).toMatchObject({ leagueId: B, member: null, status: "unclaimed" });
    // The claim itself stands until a league is chosen.
    expect(readMemberClaim()).toEqual(DENIZ);
  });

  it("drops a claim made in another league on choosing one, and keeps its own league's", () => {
    writeChosenLeague(A);
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity());
    act(() => result.current.chooseLeague(A));
    expect(readMemberClaim()).toEqual(DENIZ);
    act(() => result.current.chooseLeague(B));
    expect(readMemberClaim()).toBeNull();
    expect(readChosenLeague()).toBe(B);
  });

  it("writes and announces nothing when the league chosen is the current one", () => {
    writeChosenLeague(A);
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity());
    const claims = countClaimWrites();
    const leagues = vi.fn();
    window.addEventListener("squadopt:league-changed", leagues);
    act(() => result.current.chooseLeague(A));
    expect(claims).not.toHaveBeenCalled();
    expect(leagues).not.toHaveBeenCalled();
    window.removeEventListener("squadopt:member-changed", claims);
    window.removeEventListener("squadopt:league-changed", leagues);
  });

  it("drops the claim on change, so the next league page asks again", () => {
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity(A));
    act(() => result.current.change());
    expect(result.current).toMatchObject({ member: null, status: "unclaimed" });
    expect(sessionStorage.getItem("squadopt.member")).toBeNull();
  });
});

describe("the current league", () => {
  it("is the address's when one is given", () => {
    writeChosenLeague(B);
    writeMemberClaim(DENIZ);
    expect(renderHook(() => useLeagueIdentity(5)).result.current.leagueId).toBe(5);
  });

  it("is the claim's league over the chosen one without an address", () => {
    writeChosenLeague(B);
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity());
    expect(result.current.leagueId).toBe(A);
    expect(result.current.member?.entryId).toBe(DENIZ.entryId);
  });

  it("stays on the claim's league when another tab chooses another league", () => {
    writeChosenLeague(A);
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity());
    act(() => {
      localStorage.setItem("squadopt.league", String(B));
      window.dispatchEvent(new StorageEvent("storage", { key: "squadopt.league" }));
    });
    expect(readChosenLeague()).toBe(B);
    expect(result.current.leagueId).toBe(A);
    expect(result.current.status).toBe("claimed");
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toEqual(DENIZ);
  });
});

describe("the roster check", () => {
  it("keeps a claim while the roster is still being read", () => {
    writeMemberClaim(DENIZ);
    const { result } = renderHook(() => useLeagueIdentity(A, undefined));
    expect(result.current.status).toBe("claimed");
  });

  it("drops a claim the roster does not hold", () => {
    writeMemberClaim({ ...DENIZ, entryId: 99999999 });
    const { result } = renderHook(() => useLeagueIdentity(A, ROSTER));
    expect(result.current.status).toBe("unclaimed");
    expect(sessionStorage.getItem("squadopt.member")).toBeNull();
  });

  it("writes changed names back once", () => {
    writeMemberClaim({ ...DENIZ, managerName: "Old", teamName: "Old FC", leagueName: "Old" });
    const writes = countClaimWrites();
    const { result, rerender } = renderHook(() => useLeagueIdentity(A, ROSTER));
    expect(result.current.member).toMatchObject({
      managerName: "Deniz Aral",
      teamName: "North Stand Notes",
      leagueName: "SquadOpt Classic League",
    });
    rerender();
    expect(writes).toHaveBeenCalledTimes(1);
    window.removeEventListener("squadopt:member-changed", writes);
  });

  it("does not loop on empty names", () => {
    const roster: Roster = {
      leagueName: "",
      entries: [{ entryId: DENIZ.entryId, managerName: "", teamName: null }],
    };
    writeMemberClaim({ ...DENIZ, managerName: "", teamName: null, leagueName: "" });
    const writes = countClaimWrites();
    const { result, rerender } = renderHook(() => useLeagueIdentity(A, roster));
    rerender();
    expect(writes).not.toHaveBeenCalled();
    expect(result.current.status).toBe("claimed");
    window.removeEventListener("squadopt:member-changed", writes);
  });
});
