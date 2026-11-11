/**
 * The member's live week (#1008): read when the page opens, again when the member presses
 * refresh, and, while one of the live week's matches is being played and the page is in view,
 * once every `FOLLOW_INTERVAL_MS` (the owner's decision of 2026-11-11, so a goal shows by
 * itself). The first read asks the forwarder for the member's bundle (its current week), then
 * for that week's live points and the capture's table together; every later read asks for the
 * live points alone. A first read that gives no document, or a week that cannot be scored,
 * shows nothing: no card, and no sentence in its place. A followed read that is not answered
 * keeps what is shown.
 *
 * Each read after the first is compared with the reads before it (`advanceLiveMarks`): the
 * goals, assists and cards it adds become the read's GOL moments. A followed page whose first
 * read has not been answered, or whose member's week is not the one being played, makes the
 * first read again at the next tick instead.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import { advanceLiveMarks, type LiveMarks } from "../../liveScore/liveEvents";
import { liveMoments, type LiveMoment } from "../../liveScore/liveMoments";
import { FOLLOW_INTERVAL_MS } from "../../liveScore/liveWindow";
import type { LiveActivity } from "../../liveScore/weekActivity";
import type { MemberWeek, Position, WeekLive } from "../../liveScore/weekLive";
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

/** The moments one read brought, numbered so a new read is a new batch. */
export interface LiveMomentBatch {
  id: number;
  items: LiveMoment[];
}

export interface MemberLive {
  /** The week to show, or null while it is read and whenever there is none. */
  shown: MemberLiveScore | null;
  /** Whether a refresh is being read; the shown week stays until it answers. */
  refreshing: boolean;
  refresh: () => void;
  /** The newest read's goals, assists and cards, or null when no read has brought any. */
  moments: LiveMomentBatch | null;
}

/** What a later read reads the live points against: the member's week and the table. */
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
  fixtures: FixturesPayload | null,
): MemberLiveScore | null {
  if (fixtures === null) return null;
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

/** Each pick's name, club and position as the scored week holds them, by element id. */
function picksOf(shown: MemberLiveScore, member: MemberWeek) {
  const fifteen = [...shown.lineup.starting_xi, ...shown.lineup.bench];
  const players = new Map<number, { name: string; team: string; position: Position }>();
  member.pick_order.forEach((elementId, index) => {
    const player = fifteen[index];
    if (player === undefined || player.position === "UNK") return;
    players.set(elementId, {
      name: shown.names.get(elementId) ?? player.short_name,
      team: player.team,
      position: player.position,
    });
  });
  return players;
}

interface State {
  identity: string;
  shown: MemberLiveScore | null;
  refreshing: boolean;
  moments: LiveMomentBatch | null;
}

/**
 * `squad` is the member's published entry document: its entry, its gameweek (the table
 * gameweek the bundle is asked for) and its capture (whose table names the element ids).
 * `fixtures` is the site's calendar, for each club's id. `follow` is the gameweek whose match
 * is being played (`liveWindow`), or null: only while it is set do reads repeat on their own.
 */
export function useMemberLiveScore(
  squad: EntrySquad,
  fixtures: FixturesPayload | null,
  dependencies: MemberLiveDependencies = {},
  enabled = true,
  follow: number | null = null,
): MemberLive {
  const { tree } = useLeague();
  const ready = enabled && fixtures !== null;
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
  const [state, setState] = useState<State>({
    identity,
    shown: null,
    refreshing: false,
    moments: null,
  });
  if (state.identity !== identity) {
    setState({ identity, shown: null, refreshing: false, moments: null });
  }
  const held = useRef<Held | null>(null);
  // The read in flight, the page's first or a refresh, ended when the page leaves.
  const reading = useRef<AbortController | null>(null);
  // A followed read in flight; it never ends a read the member asked for.
  const following = useRef<AbortController | null>(null);
  // The goals, assists and cards counted so far, and the reads numbered for their moments.
  const marks = useRef<LiveMarks | null>(null);
  const reads = useRef(0);
  const lastRead = useRef(0);
  // The first read, to make again; and whether one is on its way.
  const firstRead = useRef<(() => void) | null>(null);
  const firstInFlight = useRef(false);

  /** The read's moments against the marks so far; the first read only sets the marks. */
  const momentsOf = useCallback(
    (shown: MemberLiveScore, live: LiveReading, inputs: Held): LiveMomentBatch | null => {
      const member = inputs.member;
      const { marks: next, events } = advanceLiveMarks(
        marks.current,
        {
          identity: `${inputs.identity}:${member.gameweek}`,
          sourceTime: shown.score.source_time,
          elements: live.week.elements,
          activity: live.activity,
        },
        member.pick_order,
      );
      marks.current = next;
      if (events.length === 0) return null;
      reads.current += 1;
      const items = liveMoments(events, {
        read: reads.current,
        season: live.week.season,
        counted: shown.score.counted,
        captain: shown.score.captain,
        tripleCaptain: member.active_chip === "3xc",
        players: picksOf(shown, member),
      });
      return items.length === 0 ? null : { id: reads.current, items };
    },
    [],
  );

  const entryId = squad.entry.entry_id;
  const gameweek = squad.gameweek;
  useEffect(() => {
    reading.current?.abort();
    following.current?.abort();
    following.current = null;
    held.current = null;
    // Every first read is a starting point: nothing before it plays.
    marks.current = null;
    firstInFlight.current = false;
    if (!ready) return;
    const first = async (read: AbortController) => {
      const { forwarder, loadTable } = sources.current;
      lastRead.current = Date.now();
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
      if (shown === null) return;
      momentsOf(shown, live, held.current);
      setState({ identity, shown, refreshing: false, moments: null });
    };
    const start = () => {
      if (firstInFlight.current) return;
      reading.current?.abort();
      const read = new AbortController();
      reading.current = read;
      firstInFlight.current = true;
      // The client answers every failure as a refusal; anything else also shows nothing.
      first(read)
        .catch(() => undefined)
        .finally(() => {
          if (reading.current === read) firstInFlight.current = false;
        });
    };
    firstRead.current = start;
    start();
    return () => {
      reading.current?.abort();
      firstRead.current = null;
      firstInFlight.current = false;
    };
  }, [entryId, gameweek, capture, identity, ready, momentsOf]);

  /**
   * A newer week replaces the shown one with the moments it brings; an older one is kept. Only
   * the member's own refresh ends the refreshing state: a followed read leaves it as it is.
   */
  const accept = useCallback(
    (shown: MemberLiveScore, live: LiveReading, inputs: Held, refreshed: boolean) => {
      const moments = momentsOf(shown, live, inputs);
      setState((current) => {
        const refreshing = !refreshed && current.identity === identity && current.refreshing;
        const older =
          current.identity === identity &&
          current.shown !== null &&
          Date.parse(shown.score.source_time) < Date.parse(current.shown.score.source_time);
        if (older) return { ...current, refreshing };
        return {
          identity,
          shown,
          refreshing,
          moments: moments ?? (current.identity === identity ? current.moments : null),
        };
      });
    },
    [identity, momentsOf],
  );

  const refresh = useCallback(() => {
    const inputs = held.current;
    if (inputs === null || inputs.identity !== identity) return;
    reading.current?.abort();
    const read = new AbortController();
    reading.current = read;
    lastRead.current = Date.now();
    setState((current) => ({ ...current, refreshing: true }));
    void readLive(sources.current.forwarder, inputs.member.gameweek, read.signal)
      .catch(() => null)
      .then((live) => {
        if (read.signal.aborted) return;
        const shown = live === null ? null : scored(live, inputs, sources.current.fixtures);
        // A refresh the source does not answer leaves no card, as the first read does.
        if (live === null || shown === null) {
          setState((current) => ({ ...current, identity, shown: null, refreshing: false }));
          return;
        }
        accept(shown, live, inputs, true);
      });
  }, [identity, accept]);

  /**
   * A followed read: the live points alone, quietly; no answer keeps what is shown. With no
   * first read answered yet, or the member's week not the one being played, the first read
   * is made again instead.
   */
  const followRead = useCallback(() => {
    const inputs = held.current;
    if (
      inputs === null ||
      inputs.identity !== identity ||
      (follow !== null && inputs.member.gameweek !== follow)
    ) {
      firstRead.current?.();
      return;
    }
    if (following.current !== null) return;
    const read = new AbortController();
    following.current = read;
    lastRead.current = Date.now();
    void readLive(sources.current.forwarder, inputs.member.gameweek, read.signal)
      .catch(() => null)
      .then((live) => {
        if (following.current === read) following.current = null;
        if (read.signal.aborted || live === null) return;
        const shown = scored(live, inputs, sources.current.fixtures);
        if (shown !== null) accept(shown, live, inputs, false);
      });
  }, [identity, accept, follow]);

  useEffect(() => {
    if (!ready || follow === null) return undefined;
    const visible = () => document.visibilityState === "visible";
    const stale = () => Date.now() - lastRead.current >= FOLLOW_INTERVAL_MS;
    const timer = setInterval(() => {
      if (visible()) followRead();
    }, FOLLOW_INTERVAL_MS);
    // Back in view after a minute or more: one read at once, not at the next tick.
    const onVisibility = () => {
      if (visible() && stale()) followRead();
    };
    document.addEventListener("visibilitychange", onVisibility);
    // A match that starts, or a page that comes back, with a read a minute old reads at once.
    if (visible() && stale() && held.current !== null) followRead();
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      following.current?.abort();
      following.current = null;
    };
  }, [ready, follow, followRead]);

  useEffect(
    () => () => {
      reading.current?.abort();
      following.current?.abort();
    },
    [],
  );

  const current = ready && state.identity === identity;
  return {
    shown: current ? state.shown : null,
    refreshing: state.identity === identity && state.refreshing,
    refresh,
    moments: current ? state.moments : null,
  };
}
