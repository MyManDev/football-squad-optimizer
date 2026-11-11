/**
 * The member's bundle as the live week and LIVE read it, through the app's cache under the
 * forwarded gate's key: a refusal is read again, a bundle read in the last minute is served
 * from the cache, and a read that fails never replaces a bundle the gate draws its page from.
 * The live documents LIVE keeps, by the source time the member's live week shows, and the
 * capture's table LIVE takes from the phone bar's pill where the league's line names it.
 */

import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { testActivity, testWeek, TEST_WEEK } from "../../../testSupport/liveWeek";
import { PILL_BUNDLE, PILL_ENTRY, PILL_TABLE } from "../../../testSupport/livePillSite";
import type { DevicePlanDocument } from "../device/types";
import type { DevicePlanTableRef } from "../directory";
import type { BundleReason, ForwarderResult } from "../forwarder/client";
import type { FplEntryBundle } from "../forwarder/documents";
import { forwardedKeys } from "../forwarded/reads";
import {
  cachedBundle,
  createLiveRecord,
  newestReading,
  readingAt,
  sharedTable,
  type LiveReading,
} from "./liveSources";
import type { LeagueViewEnvelope } from "../types";

afterEach(() => vi.useRealTimers());

type Answer = ForwarderResult<FplEntryBundle, BundleReason>;
const GOOD: Answer = { ok: true, copy: null, document: PILL_BUNDLE };
const REFUSED: Answer = { ok: false, reason: "upstream_unavailable" };
const KEY = forwardedKeys.bundle(PILL_ENTRY, PILL_TABLE.gameweek);

/** A forwarder answering `answers` in turn, the last one again and again. */
function forwarder(answers: Answer[]) {
  let reads = 0;
  return {
    entryBundle: vi.fn(async () => answers[Math.min(reads++, answers.length - 1)]!),
  };
}

describe("a bundle read through the page's cache", () => {
  it("reads a refusal again, and gives the bundle that read brings", async () => {
    const client = new QueryClient();
    const site = forwarder([REFUSED, GOOD]);
    const read = cachedBundle(site, client);
    await expect(read(PILL_ENTRY, PILL_TABLE.gameweek)).resolves.toEqual(REFUSED);
    // Nothing of the refusal is kept for the gate's page to draw from.
    expect(client.getQueryData(KEY)).toBeUndefined();
    await expect(read(PILL_ENTRY, PILL_TABLE.gameweek)).resolves.toEqual(GOOD);
    expect(site.entryBundle).toHaveBeenCalledTimes(2);
    expect(client.getQueryData(KEY)).toEqual(GOOD);
  });

  it("serves a bundle read in the last minute from the cache", async () => {
    const client = new QueryClient();
    const site = forwarder([GOOD]);
    const read = cachedBundle(site, client);
    await read(PILL_ENTRY, PILL_TABLE.gameweek);
    await expect(read(PILL_ENTRY, PILL_TABLE.gameweek)).resolves.toEqual(GOOD);
    expect(site.entryBundle).toHaveBeenCalledTimes(1);
  });

  it("keeps a bundle the gate holds when a later read of it fails", async () => {
    const client = new QueryClient();
    // What the forwarded gate read ten minutes ago.
    client.setQueryData(KEY, GOOD, { updatedAt: Date.now() - 10 * 60_000 });
    const site = forwarder([REFUSED]);
    const read = cachedBundle(site, client);
    // The held bundle is old, so it is read again; the failed answer leaves it in place.
    await expect(read(PILL_ENTRY, PILL_TABLE.gameweek)).resolves.toEqual(GOOD);
    expect(site.entryBundle).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(KEY)).toEqual(GOOD);
    expect(client.getQueryState(KEY)?.status).toBe("error");
  });
});

/** The live document read at `sourceTime`, with its event detail or without it. */
function reading(sourceTime: string, detailed = false): LiveReading {
  const input = testWeek({ sourceTime });
  return { week: input.live, activity: detailed ? testActivity(input) : null };
}

describe("the live documents LIVE keeps", () => {
  it("finds each read by its source time, and the newest of the week", () => {
    const record = createLiveRecord();
    for (const time of ["2026-11-21T15:30:00Z", "2026-11-21T15:20:00Z", "2026-11-21T15:31:00Z"]) {
      record.record(reading(time));
    }
    const snapshot = record.snapshot();
    expect(readingAt(snapshot, TEST_WEEK, "2026-11-21T15:20:00Z")?.week.source_time).toBe(
      "2026-11-21T15:20:00Z",
    );
    expect(readingAt(snapshot, TEST_WEEK, "2026-11-21T15:25:00Z")).toBeNull();
    expect(readingAt(snapshot, TEST_WEEK + 1, "2026-11-21T15:30:00Z")).toBeNull();
    expect(newestReading(snapshot, TEST_WEEK)?.week.source_time).toBe("2026-11-21T15:31:00Z");
    expect(newestReading(snapshot, TEST_WEEK + 1)).toBeNull();
  });

  it("keeps the newest four of a week, and a read's detailed copy over its plain one", () => {
    const record = createLiveRecord();
    const listener = vi.fn();
    record.subscribe(listener);
    record.record(reading("2026-11-21T15:30:00Z"));
    record.record(reading("2026-11-21T15:30:00Z", true));
    // The plain copy after the detailed one changes nothing.
    record.record(reading("2026-11-21T15:30:00Z"));
    expect(listener).toHaveBeenCalledTimes(2);
    expect(
      readingAt(record.snapshot(), TEST_WEEK, "2026-11-21T15:30:00Z")?.activity,
    ).not.toBeNull();
    for (const minute of [31, 32, 33, 34]) record.record(reading(`2026-11-21T15:${minute}:00Z`));
    const kept = [...record.snapshot().readings.values()].map((held) => held.week.source_time);
    expect(kept.sort()).toEqual([
      "2026-11-21T15:31:00Z",
      "2026-11-21T15:32:00Z",
      "2026-11-21T15:33:00Z",
      "2026-11-21T15:34:00Z",
    ]);
  });
});

describe("the capture's table LIVE reads", () => {
  const REF: DevicePlanTableRef = {
    path: "device/capture-1/device-plan.json",
    sha256: "0".repeat(64),
  };
  const HELD = { payload: { gameweek: TEST_WEEK } } as LeagueViewEnvelope<DevicePlanDocument>;
  const OWN = { payload: { gameweek: TEST_WEEK } } as LeagueViewEnvelope<DevicePlanDocument>;
  const signal = new AbortController().signal;

  it("takes the table the phone bar's pill holds where the league's line names it", async () => {
    const client = new QueryClient();
    client.setQueryData(forwardedKeys.table(REF), HELD);
    const load = vi.fn(async () => OWN);
    const league = { leagueId: 352490, path: "league", devicePlan: REF };
    await expect(sharedTable(client, league, "capture-1", load)(signal)).resolves.toBe(HELD);
    expect(load).not.toHaveBeenCalled();
  });

  it("reads the league's tree for another capture, or where the line names no table", async () => {
    const client = new QueryClient();
    client.setQueryData(forwardedKeys.table(REF), HELD);
    const load = vi.fn(async () => OWN);
    const named = { leagueId: 352490, path: "league", devicePlan: REF };
    await expect(sharedTable(client, named, "capture-2", load)(signal)).resolves.toBe(OWN);
    await expect(
      sharedTable(client, { leagueId: 352490, path: "league" }, "capture-1", load)(signal),
    ).resolves.toBe(OWN);
    expect(load).toHaveBeenCalledTimes(2);
  });
});
