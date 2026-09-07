import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import {
  availableWindows,
  canComputeAdvice,
  publishedSelection,
  selectedAdviceRequest,
} from "./adviceSelection";

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

  it("cannot compute a rival strategy without any rival, nor over a longer window", () => {
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

  it("computes pure points at three and five weeks", () => {
    for (const window of [3, 5]) {
      const request = selectedAdviceRequest(
        new URLSearchParams(`window=${window}`),
        352490,
        ENTRY,
        MEMBERS,
      );
      expect(request).toMatchObject({ strategy: "saf-puan", window, rivalEntryId: null });
      expect(canComputeAdvice(request)).toBe(true);
    }
  });

  it("answers a carried-over window at a week the index lists for the strategy", () => {
    // A five-week window chosen under pure points, then a rival strategy: the producer
    // writes every rival strategy at one week, so the request must name that file rather
    // than one nobody wrote.
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const request = selectedAdviceRequest(
      publishedSelection(new URLSearchParams("mode=ortak-koru&window=5"), index),
      352490,
      ENTRY,
      MEMBERS,
      undefined,
      RIVAL,
    );

    expect(request).toMatchObject({ strategy: "ortak-koru", window: 1, rivalEntryId: RIVAL });
    expect(canComputeAdvice(request)).toBe(true);
  });

  it("leaves a listed window, and a strategy the index says nothing about, as asked", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    expect(publishedSelection(new URLSearchParams("window=5"), index).get("window")).toBe("5");
    // A legacy play mode is shown from the published tree; the index does not govern it.
    expect(
      publishedSelection(new URLSearchParams("mode=garantici&window=3"), index).get("window"),
    ).toBe("3");
    // Nothing published means nothing to clamp against: the URL stands.
    expect(
      publishedSelection(new URLSearchParams("mode=ortak-koru&window=3"), null).get("window"),
    ).toBe("3");
  });

  it("offers the windows the index lists, and one week without an index", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    expect(availableWindows(index, "saf-puan")).toEqual([1, 3, 5]);
    expect(availableWindows(index, "ortak-koru")).toEqual([1]);
    expect(availableWindows(null, "saf-puan")).toEqual([1]);
    expect(availableWindows({ ...index, windows: undefined }, "saf-puan")).toEqual([1]);
    expect(availableWindows({ ...index, windows: { "saf-puan": [1, 3] } }, "saf-puan")).toEqual([
      1, 3,
    ]);
  });
});
