import { describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import {
  availableWindows,
  canComputeAdvice,
  selectedAdviceRequest,
  resolvePublishedAdvice,
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

  it("offers no windows without an index and honors the explicit legacy index window", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    expect(availableWindows(index, "saf-puan")).toEqual([1, 3, 5]);
    expect(availableWindows(index, "ortak-koru")).toEqual([1]);
    expect(availableWindows(null, "saf-puan")).toEqual([]);
    expect(availableWindows({ ...index, windows: undefined }, "saf-puan")).toEqual([1]);
    expect(availableWindows({ ...index, windows: { "saf-puan": [1, 3] } }, "saf-puan")).toEqual([
      1, 3,
    ]);
  });
});

describe("index-authoritative advice selection", () => {
  const index = mockEntryAdviceIndex(ENTRY).payload;
  const resolve = (params: string, publication = index) =>
    resolvePublishedAdvice(
      new URLSearchParams(params),
      index.league_id,
      ENTRY,
      MEMBERS,
      publication,
      { season: index.season, gameweek: index.gameweek },
    );

  it("resolves only listed standard pure-points windows and strips rival", () => {
    for (const window of [1, 3, 5]) {
      expect(resolve(`window=${window}&rival=${RIVAL}`)).toMatchObject({
        status: "ready",
        path: `advice/${ENTRY}/saf-puan/${window}.json`,
        request: { rivalEntryId: null },
      });
    }
  });
  it.each([
    "mode=garantici",
    "mode=made-up",
    "window=9",
    "mode=ortak-koru&window=3",
    "mode=fark-yarat&rival=99999999",
    `mode=fark-yarat&rival=${ENTRY}`,
  ])("rejects unsupported URL/template %s", (params) => {
    expect(resolve(params)).toMatchObject({ status: "not-listed", path: null });
  });
  it("requires a computed pair with the exact member, strategy, week and rival path", () => {
    const row = index.computed[0]!;
    const params = `mode=${row.strategy}&rival=${row.rival_entry_id}`;
    expect(resolve(params)).toMatchObject({ status: "ready", path: row.path });
    for (const path of [
      "https://other.example/plan.json",
      "../plan.json",
      `advice/${ENTRY}/fark-yarat/1/vs-999999.json`,
    ]) {
      expect(resolve(params, { ...index, computed: [{ ...row, path }] })).toMatchObject({
        status: "not-listed",
        path: null,
      });
    }
    expect(resolve(params, { ...index, computed: [] }).path).toBeNull();
    expect(resolve(params, { ...index, rival_entry_ids: [] }).path).toBeNull();
  });
  it("distinguishes no index, empty index, wrong context and a declared failure", () => {
    expect(resolvePublishedAdvice(new URLSearchParams(), 352490, ENTRY, MEMBERS, null).status).toBe(
      "index-missing",
    );
    expect(resolve("", { ...index, strategies: [], computed: [], windows: {} })).toMatchObject({
      status: "not-listed",
      path: null,
    });
    expect(resolve("", { ...index, entry_id: ENTRY + 1 }).status).toBe("index-error");
    const unavailable = index.unavailable[0]!;
    expect(
      resolve(`mode=${unavailable.strategy}&rival=${unavailable.rival_entry_id}`),
    ).toMatchObject({
      status: "declared-unavailable",
      reason: unavailable.reason,
      path: null,
    });
  });
  it("keeps each declared window when one rival pair has multiple exact computed paths", () => {
    const pair = index.computed[0]!;
    const three = `advice/${ENTRY}/${pair.strategy}/3/vs-${pair.rival_entry_id}.json`;
    const publication = {
      ...index,
      windows: { ...index.windows, [pair.strategy]: [1, 3] as (1 | 3)[] },
      computed: [...index.computed, { ...pair, path: three }],
    };
    for (const window of [1, 3]) {
      const selection = resolve(
        `mode=${pair.strategy}&rival=${pair.rival_entry_id}&window=${window}`,
        publication,
      );
      expect(selection).toMatchObject({ status: "ready", path: window === 1 ? pair.path : three });
      expect(canComputeAdvice(selection.request)).toBe(window === 1);
    }
  });
});
