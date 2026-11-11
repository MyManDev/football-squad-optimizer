/**
 * The LIVE page's reads, beside the member's own live week (`useMemberLiveScore`, which
 * makes every live read: on open, on Yenile, and while one of the member's matches is
 * played). The page hands that hook the forwarder through `liveSources`, which:
 *
 * - keeps each live document a read brings (`LiveRecord`), so the page scores the member
 *   and the rival from the read the member's live week shows, and a refresh that brings
 *   nothing keeps the board shown;
 * - reads each bundle under the key the forwarded gate reads it by (`forwardedKeys.bundle`),
 *   so a bundle the gate holds is not read again and the member's is read once;
 * - reads the capture's table once, under a key the page reads it by as well.
 *
 * The queries below name a key and a read; whoever runs one gives it the league's read
 * policy (`queries.ts`).
 */

import type { QueryClient } from "@tanstack/react-query";

import type { LiveActivity } from "../../liveScore/weekActivity";
import type { WeekLive } from "../../liveScore/weekLive";
import type { DevicePlanDocument } from "../device/types";
import type {
  BundleReason,
  ForwarderClient,
  ForwarderReason,
  ForwarderResult,
} from "../forwarder/client";
import type { FplEntryBundle, FplEntrySeason } from "../forwarder/documents";
import { entryBundleQuery, ForwarderRefused, refusalOf } from "../forwarded/reads";
import { LEAGUE_READ } from "../queries";
import type { LeagueViewEnvelope } from "../types";
import type { MemberLiveDependencies } from "./useMemberLiveScore";

/** The forwarder routes the LIVE page reads. */
export type LiveForwarder = Pick<
  ForwarderClient,
  "entryBundle" | "liveWeek" | "liveActivity" | "entrySeason" | "h2hMatches"
>;

/** One live document as the page scores it. */
export interface LiveReading {
  week: WeekLive;
  activity: LiveActivity | null;
}

/**
 * The live documents read so far, the newest few of each gameweek by source time. The page
 * draws the one the member's live week shows (`readingAt` its source time), so the board, the
 * GOL moments that read brought and Canlı puan's hold all change in the same render.
 */
export interface LiveRecord {
  record(reading: LiveReading): void;
  /** A read of `gameweek` was answered, with a document or without one. */
  settle(gameweek: number): void;
  snapshot(): LiveSnapshot;
  subscribe(listener: () => void): () => void;
}

export interface LiveSnapshot {
  /** Keyed `gameweek|source time`. */
  readings: ReadonlyMap<string, LiveReading>;
  settled: ReadonlySet<number>;
}

/** At most this many documents of one gameweek are kept: the newest. */
const KEPT_READS = 4;

const readingKey = (gameweek: number, sourceTime: string) => `${gameweek}|${sourceTime}`;

/** The document of `gameweek` read at `sourceTime`, where it is kept. */
export function readingAt(
  snapshot: LiveSnapshot,
  gameweek: number,
  sourceTime: string,
): LiveReading | null {
  return snapshot.readings.get(readingKey(gameweek, sourceTime)) ?? null;
}

/** The newest document of `gameweek` read so far, or null. */
export function newestReading(snapshot: LiveSnapshot, gameweek: number): LiveReading | null {
  let newest: LiveReading | null = null;
  for (const reading of snapshot.readings.values()) {
    if (reading.week.gameweek !== gameweek) continue;
    if (
      newest === null ||
      Date.parse(reading.week.source_time) > Date.parse(newest.week.source_time)
    ) {
      newest = reading;
    }
  }
  return newest;
}

export function createLiveRecord(): LiveRecord {
  let snapshot: LiveSnapshot = { readings: new Map(), settled: new Set() };
  const listeners = new Set<() => void>();
  const change = (next: LiveSnapshot) => {
    snapshot = next;
    for (const listener of listeners) listener();
  };
  return {
    record(reading) {
      const gameweek = reading.week.gameweek;
      const key = readingKey(gameweek, reading.week.source_time);
      const kept = snapshot.readings.get(key);
      // The same read with its event detail is kept over a copy without it, never the reverse.
      if (kept !== undefined && !(kept.activity === null && reading.activity !== null)) return;
      const readings = new Map(snapshot.readings).set(key, reading);
      const week = [...readings.entries()]
        .filter(([, held]) => held.week.gameweek === gameweek)
        .sort(([, a], [, b]) => Date.parse(b.week.source_time) - Date.parse(a.week.source_time));
      for (const [old] of week.slice(KEPT_READS)) readings.delete(old);
      change({ ...snapshot, readings });
    },
    settle(gameweek) {
      if (snapshot.settled.has(gameweek)) return;
      change({ ...snapshot, settled: new Set(snapshot.settled).add(gameweek) });
    },
    snapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** One entry's bundle for a table gameweek, as the forwarded gate reads it. */
export function bundleQuery(
  forwarder: Pick<ForwarderClient, "entryBundle">,
  entryId: number,
  gameweek: number,
) {
  return entryBundleQuery(entryId, gameweek, forwarder.entryBundle.bind(forwarder));
}

/** One entry's season to date; a team FPL does not have, or a refusal, is null. */
export function seasonQuery(forwarder: LiveForwarder, entryId: number) {
  return {
    queryKey: ["fpl-entry-season", entryId] as const,
    queryFn: async ({ signal }: { signal: AbortSignal }): Promise<FplEntrySeason | null> => {
      const read = await forwarder.entrySeason(entryId, { signal });
      if (!read.ok && read.reason === "aborted") throw new ForwarderRefused(read.reason);
      return read.ok ? read.document : null;
    },
  };
}

/** The capture's table the member's squad names, read once for the page. */
export function tableQuery(
  load: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>,
  leagueId: number,
  capture: string | null,
) {
  return {
    queryKey: ["live-capture-table", leagueId, capture] as const,
    queryFn: ({ signal }: { signal: AbortSignal }) => load(signal),
  };
}

/**
 * A bundle read into the page's cache, or found there, under the league's read policy and
 * the forwarded gate's key: the gate, the phone bar's LIVE pill and the live week share one
 * read. A bundle held under a minute is taken as it is; an older one, or none, is read. A
 * refusal is never kept (the read throws it), so the next ask reads again, and a read that
 * fails leaves a bundle already held in place for the pages drawn from it.
 */
export function cachedBundle(
  forwarder: Pick<ForwarderClient, "entryBundle">,
  client: QueryClient,
): ForwarderClient["entryBundle"] {
  return async (entryId, gameweek) => {
    const query = bundleQuery(forwarder, entryId, gameweek);
    await client.prefetchQuery({ ...query, ...LEAGUE_READ });
    const held = client.getQueryData<ForwarderResult<FplEntryBundle, BundleReason>>(query.queryKey);
    if (held !== undefined) return held;
    const error = client.getQueryState(query.queryKey)?.error;
    return { ok: false, reason: refusalOf(error) as BundleReason };
  };
}

/**
 * The dependencies for the member's live week: the forwarder whose live reads are recorded
 * and whose bundles are read through the page's cache, and the table read through it too.
 */
export function liveSources({
  forwarder,
  record,
  client,
  loadTable,
  leagueId,
  capture,
}: {
  forwarder: LiveForwarder;
  record: LiveRecord;
  client: QueryClient;
  loadTable: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  leagueId: number;
  capture: string | null;
}): MemberLiveDependencies {
  /**
   * A live read, kept when it brings a document. It settles the week unless it was stopped,
   * or is the detailed view the forwarder does not serve, which the plain view follows.
   */
  const recorded = <T, R extends ForwarderReason>(
    gameweek: number,
    read: Promise<ForwarderResult<T, R>>,
    reading: (document: T) => LiveReading,
    followed: readonly ForwarderReason[] = [],
  ) =>
    read.then((answer) => {
      if (answer.ok) record.record(reading(answer.document));
      if (answer.ok || (answer.reason !== "aborted" && !followed.includes(answer.reason))) {
        record.settle(gameweek);
      }
      return answer;
    });
  const activity = forwarder.liveActivity?.bind(forwarder);
  return {
    forwarder: {
      entryBundle: cachedBundle(forwarder, client),
      liveWeek: (gameweek, options) =>
        recorded(gameweek, forwarder.liveWeek(gameweek, options), (week) => ({
          week,
          activity: null,
        })),
      ...(activity === undefined
        ? {}
        : {
            liveActivity: (gameweek: number, options?: { signal?: AbortSignal }) =>
              recorded(
                gameweek,
                activity(gameweek, options),
                (document) => ({ week: document.week, activity: document.activity }),
                ["not_found", "not_forwarder"],
              ),
          }),
    },
    loadTable: async () => {
      const query = tableQuery(loadTable, leagueId, capture);
      await client.prefetchQuery({ ...query, ...LEAGUE_READ });
      const table = client.getQueryData<LeagueViewEnvelope<DevicePlanDocument>>(query.queryKey);
      if (table === undefined) throw new Error("The capture's table could not be read.");
      return table;
    },
  };
}
