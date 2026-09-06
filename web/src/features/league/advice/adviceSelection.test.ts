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
});
