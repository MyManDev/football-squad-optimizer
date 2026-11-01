/**
 * The member's live week as #1008 decides it: read when the page opens and again when the
 * member presses refresh, never on a timer. The first read asks the forwarder for the
 * member's bundle (its current week), then for that week's live points and the capture's
 * table together; a refresh asks for the live points alone. A read that gives no document,
 * or a week that cannot be scored, shows nothing: no card, and no sentence in its place.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import type { MemberWeek, WeekLive } from "../../liveScore/weekLive";
import type { DevicePlanDocument } from "../device/types";
import { forwarder as siteForwarder, type ForwarderClient } from "../forwarder/client";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { memberLiveScore, type MemberLiveScore } from "./memberLiveScore";

export interface MemberLiveDependencies {
  /** The forwarder's bundle and live reads; the site's own client unless a test injects one. */
  forwarder?: Pick<ForwarderClient, "entryBundle" | "liveWeek">;
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
  member: MemberWeek;
  table: DevicePlanDocument;
}

/** The week to show from one live document, or null where it cannot be scored. */
function scored(live: WeekLive, held: Held, fixtures: FixturesPayload): MemberLiveScore | null {
  try {
    const result = memberLiveScore({ live, ...held, fixtures });
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
  const [state, setState] = useState<{ shown: MemberLiveScore | null; refreshing: boolean }>({
    shown: null,
    refreshing: false,
  });
  const held = useRef<Held | null>(null);
  // The read in flight, the page's first or a refresh, ended when the page leaves.
  const reading = useRef<AbortController | null>(null);

  const entryId = squad.entry.entry_id;
  const gameweek = squad.gameweek;
  useEffect(() => {
    const read = new AbortController();
    reading.current = read;
    const { forwarder, loadTable } = sources.current;
    const first = async () => {
      const bundle = await forwarder.entryBundle(entryId, gameweek, { signal: read.signal });
      if (!bundle.ok || bundle.document.current_week === null) return;
      const member = bundle.document.current_week;
      const [live, table] = await Promise.all([
        forwarder.liveWeek(member.gameweek, { signal: read.signal }),
        loadTable(read.signal).then(
          (envelope) => envelope.payload,
          () => null,
        ),
      ]);
      if (read.signal.aborted || !live.ok || table === null) return;
      held.current = { member, table };
      const shown = scored(live.document, held.current, sources.current.fixtures);
      if (shown !== null) setState({ shown, refreshing: false });
    };
    // The client answers every failure as a refusal; anything else also shows nothing.
    first().catch(() => undefined);
    return () => read.abort();
  }, [entryId, gameweek, capture]);

  const refresh = useCallback(() => {
    const inputs = held.current;
    if (inputs === null) return;
    reading.current?.abort();
    const read = new AbortController();
    reading.current = read;
    setState((current) => ({ ...current, refreshing: true }));
    void sources.current.forwarder
      .liveWeek(inputs.member.gameweek, { signal: read.signal })
      .catch(() => null)
      .then((live) => {
        if (read.signal.aborted) return;
        // A refresh the source does not answer leaves no card, as the first read does.
        setState({
          shown: live?.ok ? scored(live.document, inputs, sources.current.fixtures) : null,
          refreshing: false,
        });
      });
  }, []);

  useEffect(() => () => reading.current?.abort(), []);

  return { shown: state.shown, refreshing: state.refreshing, refresh };
}
