import { describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { canComputeAdvice, selectedAdviceRequest } from "./adviceSelection";

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const HUMANS = MEMBERS.filter((member) => member.member_kind === "human");
const ENTRY = HUMANS[0]!.entry_id;
const RIVAL = HUMANS[1]!.entry_id;

describe("advice selection", () => {
  it("removes a rival from pure-points requests and carries the page's season and week", () => {
    const request = selectedAdviceRequest(
      new URLSearchParams(`rival=${RIVAL}`),
      352490,
      ENTRY,
      MEMBERS,
      { season: "2026-27", gameweek: 3 },
    );

    expect(request).toEqual({
      leagueId: 352490,
      entryId: ENTRY,
      strategy: "saf-puan",
      window: 1,
      rivalEntryId: null,
      season: "2026-27",
      gameweek: 3,
    });
    expect(canComputeAdvice(request)).toBe(true);
  });

  it("preserves research selections without treating them as computable aliases", () => {
    const request = selectedAdviceRequest(
      new URLSearchParams(`mode=garantici&window=3&rival=${RIVAL}`),
      352490,
      ENTRY,
      MEMBERS,
    );

    expect(request).toMatchObject({ strategy: "garantici", window: 3, rivalEntryId: RIVAL });
    expect(canComputeAdvice(request)).toBe(false);
  });

  it("gives a rival strategy the producer's default rival when none is named", () => {
    const request = selectedAdviceRequest(
      new URLSearchParams("mode=ortak-koru"),
      352490,
      ENTRY,
      MEMBERS,
      undefined,
      RIVAL,
    );
    expect(request).toMatchObject({ strategy: "ortak-koru", window: 1, rivalEntryId: RIVAL });
    expect(canComputeAdvice(request)).toBe(true);
  });

  it("keeps a named rival that is a league member and drops one that is not", () => {
    const other = HUMANS[2]!.entry_id;
    const named = selectedAdviceRequest(
      new URLSearchParams(`mode=fark-yarat&rival=${other}`),
      352490,
      ENTRY,
      MEMBERS,
      undefined,
      RIVAL,
    );
    expect(named.rivalEntryId).toBe(other);
    const stranger = selectedAdviceRequest(
      new URLSearchParams("mode=fark-yarat&rival=999999"),
      352490,
      ENTRY,
      MEMBERS,
      undefined,
      RIVAL,
    );
    expect(stranger.rivalEntryId).toBe(RIVAL);
  });

  it("cannot compute a rival strategy without any rival, nor a longer window", () => {
    const alone = selectedAdviceRequest(new URLSearchParams("mode=ortak-koru"), 352490, ENTRY, []);
    expect(alone.rivalEntryId).toBeNull();
    expect(canComputeAdvice(alone)).toBe(false);
    const long = selectedAdviceRequest(
      new URLSearchParams(`mode=ortak-koru&window=3&rival=${RIVAL}`),
      352490,
      ENTRY,
      MEMBERS,
    );
    expect(canComputeAdvice(long)).toBe(false);
  });
});
