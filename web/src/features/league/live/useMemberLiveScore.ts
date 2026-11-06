/**
 * The member's live week as #1008 decides it: read when the page opens and again when the
 * member presses refresh, never on a timer. The first read asks the forwarder for the
 * member's bundle (its current week), then for that week's live points and the capture's
 * table together; a refresh asks for the live points alone. A read that gives no document,
 * or a week that cannot be scored, shows nothing: no card, and no sentence in its place.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import type { LiveActivity } from "../../liveScore/weekActivity";
import type { MemberWeek, WeekLive } from "../../liveScore/weekLive";
import type { DevicePlanDocument } from "../device/types";
import { forwarder as siteForwarder, type ForwarderClient } from "../forwarder/client";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { memberLiveScore, type MemberLiveScore } from "./memberLiveScore";

export interface MemberLiveDependencies {
  /** The forwarder's bundle and live reads; the site's own client unless a test injects one. */
  forwarder?: Pick<ForwarderClient, "entryBundle" | "liveWeek" | "liveActivity">;
  /** Reads the capture's table; the tree's own read unless a test injects one. */
  loadTable?: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
}

export interface MemberLive {
  /** The week to show, or null while it is read and whenever there is none. */
  shown: MemberLiveScore | null;
  /** Whether a refresh is being read; the shown week stays until it answers. */
  refreshing: boolean;
  refresh: () => void;
}

/** What a refresh reads the live points against: the member's week and the table. */
interface Held {
  identity: string;
  member: MemberWeek;
  table: DevicePlanDocument;
}

/** The week to show from one live document, or null where it cannot be scored. */
interface LiveReading {
  week: WeekLive;
  activity: LiveActivity | null;
}

async function readLive(
  forwarder: NonNullable<MemberLiveDependencies["forwarder"]>,
  gameweek: number,
  signal: AbortSignal,
): Promise<LiveReading | null> {
  if (forwarder.liveActivity) {
    const result = await forwarder.liveActivity(gameweek, { signal });
    if (result.ok) return { week: result.document.week, activity: result.document.activity };
    if (result.reason !== "not_found" && result.reason !== "not_forwarder") return null;
    if (signal.aborted) return null;
  }
  const result = await forwarder.liveWeek(gameweek, { signal });
  return result.ok ? { week: result.document, activity: null } : null;
}

function scored(
  reading: LiveReading,
  held: Held,
  fixtures: FixturesPayload,
): MemberLiveScore | null {
  try {
    const result = memberLiveScore({
      live: reading.week,
      activity: reading.activity,
      ...held,
      fixtures,
    });
    return result.ok ? result.live : null;
  } catch {
    return null;
  }
}

/**
 * `squad` is the member's published entry document: its entry, its gameweek (the table
 * gameweek the bundle is asked for) and its capture (whose table names the element ids).
 * `fixtures` is the site's calendar, for each club's id.
 */
export function useMemberLiveScore(
  squad: EntrySquad,
  fixtures: FixturesPayload,
  dependencies: MemberLiveDependencies = {},
): MemberLive {
  const { tree } = useLeague();
  const capture = squad.source_snapshot_id ?? null;
  const identity = JSON.stringify([squad.entry.entry_id, squad.season, squad.gameweek, capture]);
  // The reads and the calendar as this render has them, for reads that start later.
  const latest = {
    forwarder: dependencies.forwarder ?? siteForwarder,
    loadTable:
      dependencies.loadTable ?? ((signal: AbortSignal) => tree.devicePlan(capture, { signal })),
    fixtures,
  };
  const sources = useRef(latest);
  useEffect(() => {
    sources.current = latest;
  });
  const [state, setState] = useState<{
    identity: string;
    shown: MemberLiveScore | null;
    refreshing: boolean;
  }>({
    identity,
    shown: null,
    refreshing: false,
  });
  if (state.identity !== identity) {
    setState({ identity, shown: null, refreshing: false });
  }
  const held = useRef<Held | null>(null);
  // The read in flight, the page's first or a refresh, ended when the page leaves.
  const reading = useRef<AbortController | null>(null);

  const entryId = squad.entry.entry_id;
  const gameweek = squad.gameweek;
  useEffect(() => {
    reading.current?.abort();
    held.current = null;
    const read = new AbortController();
    reading.current = read;
    const { forwarder, loadTable } = sources.current;
    const first = async () => {
      const bundle = await forwarder.entryBundle(entryId, gameweek, { signal: read.signal });
      if (read.signal.aborted || !bundle.ok || bundle.document.current_week === null) return;
      const member = bundle.document.current_week;
      const [live, table] = await Promise.all([
        readLive(forwarder, member.gameweek, read.signal),
        loadTable(read.signal).then(
          (envelope) => envelope.payload,
          () => null,
        ),
      ]);
      if (read.signal.aborted || live === null || table === null) return;
      held.current = { identity, member, table };
      const shown = scored(live, held.current, sources.current.fixtures);
      if (shown !== null) setState({ identity, shown, refreshing: false });
    };
    // The client answers every failure as a refusal; anything else also shows nothing.
    first().catch(() => undefined);
    return () => read.abort();
  }, [entryId, gameweek, capture, identity]);

  const refresh = useCallback(() => {
    const inputs = held.current;
    if (inputs === null || inputs.identity !== identity) return;
    reading.current?.abort();
    const read = new AbortController();
    reading.current = read;
    setState((current) => ({ ...current, refreshing: true }));
    void readLive(sources.current.forwarder, inputs.member.gameweek, read.signal)
      .catch(() => null)
      .then((live) => {
        if (read.signal.aborted) return;
        // A refresh the source does not answer leaves no card, as the first read does.
        const shown = live === null ? null : scored(live, inputs, sources.current.fixtures);
        setState((current) => {
          const older =
            current.identity === identity &&
            current.shown !== null &&
            shown !== null &&
            Date.parse(shown.score.source_time) < Date.parse(current.shown.score.source_time);
          return { identity, shown: older ? current.shown : shown, refreshing: false };
        });
      });
  }, [identity]);

  useEffect(() => () => reading.current?.abort(), []);

  return {
    shown: state.identity === identity ? state.shown : null,
    refreshing: state.identity === identity && state.refreshing,
    refresh,
  };
}
