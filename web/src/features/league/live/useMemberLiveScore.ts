/**
 * The member's live week (#1008): read when the page opens, again when the member presses
 * refresh, and, while one of the member's matches is being played and the page is in view,
 * once every `FOLLOW_INTERVAL_MS` (the owner's decision of 2026-11-11, so a goal shows by
 * itself; `matches` gives the caller what `liveWindow` needs to tell). The first read asks the
 * forwarder for the member's bundle (its current week), then for that week's live points and
 * the capture's table together; every later read asks for the live points alone. A first read
 * that gives no document, or a week that cannot be scored, shows nothing: no card, and no
 * sentence in its place. A followed read that is not answered keeps what is shown.
 *
 * Each read after the first is compared with the reads before it (`advanceLiveMarks`): the
 * goals, assists and cards it adds become the read's GOL moments. A followed page whose first
 * read has not been answered, or whose member's week is not the one being played, makes the
 * first read again instead, at the next tick after one failure and then after 2, 4 and at most
 * 8 minutes. A first read made again never ends the member's refresh, nor a refresh it; no tick
 * reads within half an interval of the last read.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import { advanceLiveMarks, type LiveMarks } from "../../liveScore/liveEvents";
import { liveMoments, type LiveMoment } from "../../liveScore/liveMoments";
import { FOLLOW_INTERVAL_MS, type LiveWindowFilter } from "../../liveScore/liveWindow";
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
  /** The member's clubs and the unfinished fixtures as the shown read names them, for `liveWindow`. */
  matches: LiveWindowFilter | null;
  /**
   * How many first reads have shown a week: a new number is a new starting point, for the
   * goals and cards a read adds (the marks) and for whatever a page counts from reads (its
   * substitutions).
   */
  start: number;
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

/** A match whose players' minutes went up this recently is still being played. */
const IN_PLAY_GRACE_MS = 5 * 60_000;

/** Each match's minutes as last seen going up, and when, by fixture id. */
type PlayedMinutes = Map<number, { minutes: number; at: number }>;

/**
 * The week's matches still being played, and those that may be. FPL calls a match finished only
 * once its bonus is confirmed, about an hour after the final whistle, so a match counts as played
 * only while its players' minutes go up (within `IN_PLAY_GRACE_MS`); one FPL has not finished
 * whose minutes stand still (a whistle, a long stoppage, a stalled feed) is `stalled`, to be read
 * now and then until its window's limit. Without the activity view the read cannot tell, and
 * every match not finished counts as played. `seen` is updated with this read's minutes.
 */
function matchesPlayed(
  live: LiveReading,
  seen: PlayedMinutes,
  now: number,
): { played: Set<number>; stalled: Set<number> } {
  const open = live.week.fixtures.filter((row) => !row.finished).map((row) => row.id);
  if (live.activity === null) return { played: new Set(open), stalled: new Set() };
  const minutes = new Map<number, number>();
  for (const row of live.activity.appearances) {
    minutes.set(row.fixture_id, (minutes.get(row.fixture_id) ?? 0) + row.minutes);
  }
  const played = new Set<number>();
  const stalled = new Set<number>();
  for (const id of open) {
    const total = minutes.get(id) ?? 0;
    const before = seen.get(id);
    if (before === undefined || total > before.minutes) seen.set(id, { minutes: total, at: now });
    if (total === 0) continue;
    if (now - seen.get(id)!.at < IN_PLAY_GRACE_MS) played.add(id);
    else stalled.add(id);
  }
  return { played, stalled };
}

/**
 * The clubs (the calendar's team ids) of the member's fifteen and the week's matches still
 * being played or stalled (`matchesPlayed`). The clubs come from the scored week's lineup, which names each
 * pick's club as the capture's table does: the forwarder's live elements carry no club. A club
 * the calendar does not name leaves the clubs open (null), so no match is missed.
 */
function matchesOf(
  live: LiveReading,
  shown: MemberLiveScore,
  fixtures: FixturesPayload | null,
  seen: PlayedMinutes,
  now: number,
): LiveWindowFilter {
  const ids = new Map<string, number>();
  for (const week of fixtures?.gameweeks ?? []) {
    for (const fixture of week.fixtures) {
      ids.set(fixture.home.name, fixture.home.team_id);
      ids.set(fixture.away.name, fixture.away.team_id);
    }
  }
  const picked = [...shown.lineup.starting_xi, ...shown.lineup.bench].map((player) =>
    ids.get(player.team),
  );
  const { played, stalled } = matchesPlayed(live, seen, now);
  return {
    clubs:
      picked.length > 0 && picked.every((club) => club !== undefined)
        ? new Set(picked as number[])
        : null,
    unfinished: played,
    stalled,
  };
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
  matches: LiveWindowFilter | null;
  start: number;
}

/** A tick reads only when the last read is at least this old. */
const TICK_GAP_MS = FOLLOW_INTERVAL_MS / 2;

/** A first read made again after `failures` failures waits this long after the last read. */
const retryWait = (failures: number) =>
  FOLLOW_INTERVAL_MS * 2 ** Math.min(Math.max(failures - 1, 0), 3);

/**
 * `squad` is the member's published entry document: its entry, its gameweek (the table
 * gameweek the bundle is asked for) and its capture (whose table names the element ids).
 * `fixtures` is the site's calendar, for each club's id. `follow` is the gameweek whose match
 * is being played (`liveWindow`), or null: only while it is set do reads repeat on their own,
 * `pace` apart (once a minute while a match is played, less often while one may be).
 */
export function useMemberLiveScore(
  squad: EntrySquad,
  fixtures: FixturesPayload | null,
  dependencies: MemberLiveDependencies = {},
  enabled = true,
  follow: number | null = null,
  pace: number = FOLLOW_INTERVAL_MS,
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
    matches: null,
    start: 0,
  });
  if (state.identity !== identity) {
    setState({
      identity,
      shown: null,
      refreshing: false,
      moments: null,
      matches: null,
      start: state.start,
    });
  }
  // Whether the next week shown is a first read's after the marks were set afresh.
  const fresh = useRef(true);
  const held = useRef<Held | null>(null);
  // The member's refresh in flight, ended when the page leaves.
  const reading = useRef<AbortController | null>(null);
  // The first read in flight, the page's own or one made again; it never ends a refresh.
  const firstReading = useRef<AbortController | null>(null);
  // First reads that ended without a week to show, since the last one that showed it.
  const firstFailures = useRef(0);
  // A followed read in flight; it never ends a read the member asked for.
  const following = useRef<AbortController | null>(null);
  // The goals, assists and cards counted so far, and the reads numbered for their moments.
  const marks = useRef<LiveMarks | null>(null);
  // Each match's minutes as last seen going up, for the matches still being played.
  const played = useRef<PlayedMinutes>(new Map());
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
    firstReading.current?.abort();
    firstReading.current = null;
    following.current?.abort();
    following.current = null;
    held.current = null;
    // Every first read is a starting point: nothing before it plays.
    marks.current = null;
    fresh.current = true;
    played.current = new Map();
    firstInFlight.current = false;
    firstFailures.current = 0;
    if (!ready) return;
    /** Whether the read showed a week. */
    const first = async (read: AbortController): Promise<boolean> => {
      const { forwarder, loadTable } = sources.current;
      lastRead.current = Date.now();
      const bundle = await forwarder.entryBundle(entryId, gameweek, { signal: read.signal });
      if (read.signal.aborted || !bundle.ok || bundle.document.current_week === null) return false;
      const member = bundle.document.current_week;
      const [live, table] = await Promise.all([
        readLive(forwarder, member.gameweek, read.signal),
        loadTable(read.signal).then(
          (envelope) => envelope.payload,
          () => null,
        ),
      ]);
      if (read.signal.aborted || live === null || table === null) return false;
      const inputs = { identity, member, table };
      const shown = scored(live, inputs, sources.current.fixtures);
      // A week the scorer refuses is a failed first read: it is made again later (retryWait),
      // and no followed read stands on it.
      if (shown === null) return false;
      held.current = inputs;
      // A first read made again may bring a goal against the marks so far: it plays too.
      const moments = momentsOf(shown, live, held.current);
      const matches = matchesOf(live, shown, sources.current.fixtures, played.current, Date.now());
      const begins = fresh.current;
      fresh.current = false;
      setState((current) => {
        const kept = current.identity === identity;
        return {
          identity,
          shown,
          refreshing: kept && current.refreshing,
          moments: moments ?? (kept ? current.moments : null),
          matches,
          start: current.start + (begins ? 1 : 0),
        };
      });
      return true;
    };
    const start = () => {
      if (firstInFlight.current) return;
      firstReading.current?.abort();
      const read = new AbortController();
      firstReading.current = read;
      firstInFlight.current = true;
      // The client answers every failure as a refusal; anything else also shows nothing.
      first(read)
        .catch(() => false)
        .then((shown) => {
          if (!read.signal.aborted) firstFailures.current = shown ? 0 : firstFailures.current + 1;
        })
        .finally(() => {
          if (firstReading.current === read) {
            firstReading.current = null;
            firstInFlight.current = false;
          }
        });
    };
    firstRead.current = start;
    start();
    return () => {
      reading.current?.abort();
      firstReading.current?.abort();
      firstReading.current = null;
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
      const matches = matchesOf(live, shown, sources.current.fixtures, played.current, Date.now());
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
          matches,
          start: current.start,
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
   * is made again instead, later after each failure (`retryWait`).
   */
  const followRead = useCallback(() => {
    const inputs = held.current;
    if (
      inputs === null ||
      inputs.identity !== identity ||
      (follow !== null && inputs.member.gameweek !== follow)
    ) {
      const waited = Date.now() - lastRead.current;
      if (waited >= retryWait(firstFailures.current) - TICK_GAP_MS) firstRead.current?.();
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
    const stale = () => Date.now() - lastRead.current >= pace;
    // A read in the last half interval (a refresh, a return to view) stands in for the tick's.
    const due = () => Date.now() - lastRead.current >= pace / 2;
    const timer = setInterval(() => {
      if (visible() && due()) followRead();
    }, pace);
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
  }, [ready, follow, followRead, pace]);

  useEffect(
    () => () => {
      reading.current?.abort();
      firstReading.current?.abort();
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
    matches: current ? state.matches : null,
    start: state.start,
  };
}
