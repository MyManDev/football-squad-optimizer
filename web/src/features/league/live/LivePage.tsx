/**
 * LIVE: the member's live week beside one rival (the synthesis of 2026-11-11, sections 3.1
 * to 3.6, and the owner's decisions of that day). Its own address under the member's, as
 * the history and VS SQUADOPT have, behind the same gates, and `/entry/<id>/live` for one
 * team on its own, which has no rival.
 *
 * The week is always the bundle's current week, the latest whose deadline has passed, never
 * the squad's own week: once the next week is published the page still shows the week being
 * played. Its reads are the member's live week's (`useMemberLiveScore`): on open, on Yenile,
 * and once a minute while one of the member's matches is played and the page is in view,
 * wired as the member page wires them, with the GOL board and `?replay=1` of its own. The
 * member and the rival are scored from the read the live week shows. The rival's bundle is read
 * when the rival is chosen, again on Yenile, and again by itself while it is refused or names
 * another week (`useReadAgain`: after 1, 2, 4 and 8 minutes, then no more until Yenile); a
 * head-to-head league's pairings are read once, and a published classic league's total gap
 * comes from the members table the page holds.
 *
 * The heading stands first in every state, so the one the shell focuses on arrival stays.
 * Canlı puan takes the GOL board's points as each moment lands, as the member page's card
 * does, and the rows and the recap take a read once its moments have landed.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useParams, useSearchParams } from "react-router";

import { recordUsage } from "../../../data/usage";
import { useShellLayout } from "../../../design/shell/layout";
import { useLanguage } from "../../../i18n/context";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { GoalMomentLayer } from "../../liveScore/GoalMoment";
import {
  FOLLOW_INTERVAL_MS,
  SLOW_FOLLOW_MS,
  type LiveWindowFilter,
} from "../../liveScore/liveWindow";
import type { DevicePlanDocument } from "../device/types";
import { useForwardedLeague } from "../forwarded/ForwardedLeagueContext";
import { defaultRivalOf } from "../forwarded/forwardedTree";
import { forwarder as siteForwarder } from "../forwarder/client";
import { useClaimedEntry } from "../identity/useLeagueIdentity";
import { LEAGUE_READ, leagueKeys, useEntrySquad } from "../queries";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { useCoverGone } from "../../liveScore/openingCover";
import {
  advanceRecap,
  liveBoard,
  lookedAt,
  recapFrom,
  recapItems,
  type LiveBoard,
  type LiveRecap,
} from "./liveBoard";
import { leagueTotalsBefore, liveDuel, type LiveDuel } from "./liveDuel";
import { createLiveLight, type LiveLight } from "./liveLight";
import { keepLook, readLook } from "./liveLooks";
import {
  lookKey,
  lookOf,
  planMotion,
  sameDuel,
  type DuelLook,
  type LiveLook,
  type MotionGate,
  type MotionPlan,
} from "./liveMotion";
import { addressedRival, chooseRival, h2hOpponent, rivalChoices } from "./liveRival";
import {
  bundleQuery,
  createLiveRecord,
  liveSources,
  newestReading,
  readingAt,
  sharedTable,
  tableQuery,
  type LiveForwarder,
} from "./liveSources";
import styles from "./LivePage.module.css";
import { LiveHeader, LiveState, LiveView, type HeldDuel, type LiveRivalView } from "./LiveView";
import { useBoardHold, useBoardMoments } from "./useBoardMoments";
import { useReadAgain } from "./useReadAgain";
import { useGoalReplay } from "./useGoalReplay";
import { useLiveWindow } from "./useLiveWindow";
import { useMemberLiveScore } from "./useMemberLiveScore";
import { useWide } from "./useWide";

/** The GOL board, drawn again only when its batch, source or wiring changes. */
const GoalLayer = memo(GoalMomentLayer);

/** The reads the page makes; the site's own unless a test injects them. */
export interface LiveDependencies {
  forwarder?: LiveForwarder;
  loadTable?: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
}

/** What the heading says of a member's week, once the page below it knows. */
interface LiveHead {
  entryId: number;
  gameweek: number | null;
}

export function LivePage({ dependencies }: { dependencies?: LiveDependencies } = {}) {
  useEffect(() => recordUsage({ step: "tool" }), []);
  const { messages } = useLanguage();
  const parameter = useParams().entryId ?? "";
  const entryId = Number(parameter);
  const valid = /^[1-9]\d*$/.test(parameter) && Number.isSafeInteger(entryId);
  const squad = useEntrySquad(entryId, valid);
  const fixtures = useFixtures();
  const wide = useWide();
  const [head, setHead] = useState<LiveHead | null>(null);
  const [light] = useState(createLiveLight);
  const known = head !== null && head.entryId === entryId ? head : null;
  const unnamed = messages.leagueMembers.unknownTeam;
  // A squad held is drawn from, though a later read of it fails.
  const entry = squad.data;
  let body: ReactNode;
  if (entry === undefined) {
    body = <LiveState kind={valid && !squad.isError ? "loading" : "empty"} />;
  } else if (fixtures.isPending) {
    body = <LiveState kind="loading" />;
  } else {
    body = (
      <LiveMember
        key={entryId}
        squad={entry}
        fixtures={fixtures.data ?? null}
        dependencies={dependencies}
        wide={wide}
        unnamed={unnamed}
        onHead={setHead}
        light={light}
      />
    );
  }
  return (
    <div className={styles.page} data-live-page data-wide={wide || undefined}>
      <LiveHeader
        team={entry === undefined ? "" : (entry.payload.entry.team_name ?? unnamed)}
        gameweek={known?.gameweek ?? null}
        entryId={entryId}
        light={light}
      />
      {body}
    </div>
  );
}

function LiveMember({
  squad,
  fixtures,
  dependencies = {},
  wide,
  unnamed,
  onHead,
  light,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  fixtures: FixturesPayload | null;
  dependencies?: LiveDependencies;
  wide: boolean;
  unnamed: string;
  onHead: (head: LiveHead) => void;
  light: LiveLight;
}) {
  const view = squad.payload;
  const entryId = view.entry.entry_id;
  const { league, tree, forwarded = false } = useLeague();
  const leagueId = league.leagueId;
  const standalone = leagueId <= 0;
  const headToHead = useForwardedLeague()?.scoring === "h2h";
  // A head-to-head league plays for match points, so only a classic table has a total gap.
  const classic = !standalone && !headToHead;
  const [searchParams, setSearchParams] = useSearchParams();
  const replaying = searchParams.get("replay") === "1";
  const client = useQueryClient();
  const forwarder = dependencies.forwarder ?? siteForwarder;
  const capture = view.source_snapshot_id ?? null;
  const injectedTable = dependencies.loadTable;
  const loadTable = useMemo(
    () =>
      injectedTable ??
      sharedTable(client, tree.league, capture, (signal) => tree.devicePlan(capture, { signal })),
    [injectedTable, client, tree, capture],
  );
  const [record] = useState(createLiveRecord);
  const sources = useMemo(
    () => liveSources({ forwarder, record, client, loadTable, leagueId, capture }),
    [forwarder, record, client, loadTable, leagueId, capture],
  );
  const ready = fixtures !== null && view.league_id === leagueId;

  // The member's live week, wired as the member page wires it: the window follows only the
  // member's matches once a read has named them, and the replay stands in for the page's
  // own reads while it plays.
  const [matchFilter, setMatchFilter] = useState<LiveWindowFilter>({});
  const liveMatch = useLiveWindow(fixtures, matchFilter);
  const live = useMemberLiveScore(
    view,
    fixtures,
    sources,
    ready,
    replaying || !(liveMatch.open || liveMatch.slow) ? null : liveMatch.gameweek,
    liveMatch.open ? FOLLOW_INTERVAL_MS : SLOW_FOLLOW_MS,
  );
  if (live.matches !== null && live.matches !== matchFilter) setMatchFilter(live.matches);
  const replay = useGoalReplay(view, fixtures, sources, replaying && ready);
  // The board's batches, numbered as the member page numbers them: the replay and the real
  // reads are two streams, so one never swallows or replays the other's moment.
  const stream = useBoardMoments(live, entryId);
  // While the board plays, LIVE stays on the read from before its first moment, the points
  // that have landed added to Canlı puan, as the member page's card does; the replay brings no
  // real points, so nothing waits for it.
  const hold = useBoardHold(replaying ? null : stream);
  // The same batch while nothing new comes, so a landing does not draw the board again.
  const goalBatch = useMemo(
    () =>
      replaying
        ? replay === null
          ? null
          : { id: `replay:${replay.id}`, items: replay.items }
        : stream === null
          ? null
          : { id: `live:${stream.id}`, items: stream.items },
    [replaying, replay, stream],
  );

  const snapshot = useSyncExternalStore(record.subscribe, record.snapshot, record.snapshot);
  const memberBundle = useQuery({
    ...bundleQuery(forwarder, entryId, view.gameweek),
    ...LEAGUE_READ,
    enabled: ready,
  });
  const memberWeek = memberBundle.data?.ok ? memberBundle.data.document.current_week : null;
  const table = useQuery({
    ...tableQuery(loadTable, leagueId, capture),
    ...LEAGUE_READ,
    enabled: ready,
  });
  const week = memberWeek?.gameweek ?? null;
  // The board is scored from the read the live week shows, so its total changes in the same
  // render as the moments that read brought and the hold on them. Until the live week shows
  // one (a first read brings no moments), the newest read is drawn.
  const shownTime = live.shown?.score.source_time ?? null;
  const [lastShown, setLastShown] = useState<string | null>(null);
  if (shownTime !== null && shownTime !== lastShown) setLastShown(shownTime);
  const time = shownTime ?? lastShown;
  const reading =
    week === null
      ? null
      : ((time === null ? null : readingAt(snapshot, week, time)) ?? newestReading(snapshot, week));
  const board = useMemo(
    () =>
      reading !== null && memberWeek !== null && table.data !== undefined && fixtures !== null
        ? liveBoard({
            live: reading.week,
            activity: reading.activity,
            member: memberWeek,
            table: table.data.payload,
            fixtures,
          })
        : null,
    [reading, memberWeek, table.data, fixtures],
  );

  // The rival: the members the page holds, the live week's opponent in a head-to-head
  // league, and a listed league's default from its index, each read only where needed.
  const members = useQuery({
    queryKey: leagueKeys.members(leagueId),
    queryFn: () => tree.members(),
    enabled: !standalone,
    ...LEAGUE_READ,
  });
  const held = useMemo(() => members.data?.payload.members ?? [], [members.data]);
  const opponent = useQuery({
    queryKey: ["fpl-h2h-opponent", leagueId, week, entryId] as const,
    queryFn: () => h2hOpponent((page) => forwarder.h2hMatches(leagueId, week!, page), entryId),
    enabled: headToHead && week !== null,
    ...LEAGUE_READ,
  });
  const choices = useMemo(
    () => rivalChoices(held, entryId, opponent.data ?? null, unnamed),
    [held, entryId, opponent.data, unnamed],
  );
  const byAddress =
    addressedRival(searchParams, "duel", choices) ?? addressedRival(searchParams, "rival", choices);
  const index = useQuery({
    queryKey: leagueKeys.adviceIndex(leagueId, entryId),
    queryFn: () => tree.entryAdviceIndex(entryId),
    enabled: !standalone && !forwarded && byAddress === null,
    ...LEAGUE_READ,
  });
  const waiting =
    members.isPending ||
    (headToHead &&
      addressedRival(searchParams, "duel", choices) === null &&
      (week === null || opponent.isPending)) ||
    (!forwarded && byAddress === null && index.isPending);
  const rivalId =
    standalone || waiting
      ? null
      : chooseRival({
          search: searchParams,
          opponent: opponent.data?.entryId ?? null,
          fallback: forwarded
            ? defaultRivalOf(held, entryId)
            : (index.data?.payload.default_rival_entry_id ?? null),
          choices,
        });
  const rivalBundle = useQuery({
    ...bundleQuery(forwarder, rivalId ?? 0, view.gameweek),
    ...LEAGUE_READ,
    enabled: ready && rivalId !== null,
  });
  const rivalWeek = rivalBundle.data?.ok ? rivalBundle.data.document.current_week : null;
  // A rival read before a deadline names the week before, and a refused read names none: it is
  // read again by itself, less and less often, and on Yenile.
  const rivalBehind =
    rivalId !== null &&
    (rivalBundle.isError || (rivalWeek !== null && week !== null && rivalWeek.gameweek !== week));
  const readRival = rivalBundle.refetch;
  const countRivalAfresh = useReadAgain(rivalBehind, readRival, rivalBundle.isFetching, rivalId);
  const memberRefresh = live.refresh;
  const refreshBoth = useCallback(() => {
    memberRefresh();
    if (rivalId === null) return;
    countRivalAfresh();
    void readRival();
  }, [memberRefresh, rivalId, countRivalAfresh, readRival]);
  const rivalBoard = useMemo(
    () =>
      reading !== null &&
      rivalWeek !== null &&
      rivalWeek.gameweek === reading.week.gameweek &&
      table.data !== undefined &&
      fixtures !== null
        ? liveBoard({
            live: reading.week,
            activity: reading.activity,
            member: rivalWeek,
            table: table.data.payload,
            fixtures,
          })
        : null,
    [reading, rivalWeek, table.data, fixtures],
  );
  // A classic league's totals before the week, from its own published table.
  const totals = useMemo(
    () =>
      classic && week !== null && rivalId !== null
        ? leagueTotalsBefore(members.data?.payload ?? null, week, entryId, rivalId)
        : null,
    [classic, week, rivalId, members.data, entryId],
  );
  const duel = useMemo(
    () =>
      board !== null && rivalBoard !== null
        ? liveDuel(board, rivalBoard, classic ? totals : null)
        : null,
    [board, rivalBoard, classic, totals],
  );
  // The last duel drawn holds its place, out of sight, while the next rival's bundle is read
  // for the first time. The first rival's, read after the member's board, holds the room of a
  // level duel, so its arrival moves nothing below it. A read made again (Yenile, a refused or
  // late rival) holds no room: an empty room would come and go with each try.
  const [kept, setKept] = useState<HeldDuel | null>(null);
  if (duel !== null && rivalBoard !== null && kept?.duel !== duel) {
    setKept({ duel, rivalNet: rivalBoard.net });
  }
  // The first read of this rival: nothing answered yet, neither a bundle nor a refusal (a read
  // made again after a refusal is pending once more, but has been answered before).
  const rivalReading =
    duel === null &&
    rivalId !== null &&
    rivalBundle.isPending &&
    rivalBundle.dataUpdatedAt === 0 &&
    rivalBundle.errorUpdateCount === 0;
  const pending = useMemo(
    () =>
      !rivalReading
        ? null
        : (kept ??
          (board === null
            ? null
            : { duel: liveDuel(board, board, classic ? totals : null), rivalNet: board.net })),
    [rivalReading, kept, board, classic, totals],
  );
  const choose = useCallback(
    (next: number) =>
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current);
          params.set("duel", String(next));
          return params;
        },
        { replace: true },
      ),
    [setSearchParams],
  );
  // Drawn once the rival is chosen, so the picker never shows an empty choice first; the same
  // object until something in it changes, so the rival's side is not drawn again for nothing.
  const showRival = !(standalone || waiting || choices.length === 0);
  const opponentId = opponent.data?.entryId ?? null;
  const rivalView = useMemo<LiveRivalView | null>(
    () =>
      showRival
        ? {
            choices,
            entryId: rivalId,
            name: choices.find((choice) => choice.entryId === rivalId)?.name ?? null,
            board: rivalBoard,
            duel,
            pending,
            opponent: rivalId !== null && rivalId === opponentId,
            onSelect: choose,
          }
        : null,
    [showRival, choices, rivalId, rivalBoard, duel, pending, opponentId, choose],
  );

  const claimed = useClaimedEntry(leagueId);
  const gameweek = board?.gameweek ?? week;
  useEffect(() => onHead({ entryId, gameweek }), [onHead, entryId, gameweek]);
  const loading =
    ready &&
    board === null &&
    (memberBundle.isPending ||
      (memberWeek !== null &&
        (table.isPending || (reading === null && !snapshot.settled.has(memberWeek.gameweek)))));
  return (
    <>
      <GoalLayer
        batch={goalBatch}
        source={replaying ? "replay" : "live"}
        scoring={!replaying}
        onLanded={hold.landed}
      />
      {board === null ? (
        <LiveState kind={loading ? "loading" : "empty"} />
      ) : (
        <LiveShown
          board={board}
          brought={hold.brought}
          waiting={hold.waiting}
          team={view.entry.team_name ?? unnamed}
          own={!standalone && claimed === entryId}
          rival={rivalView}
          entryId={entryId}
          refreshing={live.refreshing}
          reading={live.reading}
          refresh={refreshBoth}
          wide={wide}
          windowOpen={liveMatch.open}
          light={light}
        />
      )}
    </>
  );
}

/**
 * The rival's side while the board holds the read before: the duel that read drew, or, for a
 * rival whose duel it did not draw (picked, or first read, while the board plays), its room out
 * of sight until the board has played out, so the duel never mixes two reads.
 */
function heldRival(
  rival: LiveRivalView,
  settled: { rivalId: number | null; rivalBoard: LiveBoard | null; rivalDuel: LiveDuel | null },
): LiveRivalView {
  if (settled.rivalId === rival.entryId && settled.rivalDuel !== null) {
    return { ...rival, board: settled.rivalBoard, duel: settled.rivalDuel, pending: null };
  }
  const room =
    rival.duel !== null && rival.board !== null
      ? { duel: rival.duel, rivalNet: rival.board.net }
      : rival.pending;
  return { ...rival, board: null, duel: null, pending: room };
}

/** What LIVE has told of a member's week: the board drawn, the recap, the look and its motion. */
interface Told {
  board: LiveBoard | null;
  recap: LiveRecap | null;
  look: LiveLook | null;
  plan: MotionPlan | null;
}

/**
 * Where LIVE starts for the board it opens on: from what the visitor last saw of the week, kept
 * in this browser, so a newer board moves what changed since and the recap tells it; from
 * nothing, where nothing was seen.
 */
function toldAtOpen(board: LiveBoard): Told {
  const kept = readLook(lookKey(board));
  return kept === null
    ? { board: null, recap: null, look: null, plan: null }
    : { board: null, recap: recapFrom(kept.marks), look: kept.look, plan: null };
}

/**
 * `drawn` taken in: the recap advanced (cleared first when the visitor looked since), the look,
 * and the read's motion against the look before. A copy of the same read keeps the motion it
 * has; another week has none.
 */
function tell(told: Told, drawn: LiveBoard, duel: DuelLook | null, clear: boolean): Told {
  const recap = advanceRecap(clear ? lookedAt(told.recap) : told.recap, drawn);
  const look = lookOf(drawn, duel);
  const before = told.look;
  const same = before !== null && before.key === look.key;
  const plan =
    same && look.time > before.time
      ? planMotion(before, look, recap.fresh, told.board === null)
      : same && look.time === before.time
        ? told.plan
        : null;
  return { board: drawn, recap, look, plan };
}

/** The duel as drawn beside `board`, or null while none is: no rival, or one still read. */
function duelLook(board: LiveBoard, rival: LiveRivalView | null): DuelLook | null {
  if (rival === null || rival.entryId === null || rival.duel === null || rival.board === null) {
    return null;
  }
  return {
    rivalId: rival.entryId,
    rivalNet: rival.board.net,
    memberNet: board.net,
    margin: rival.duel.margin,
  };
}

/**
 * The board as it is shown. Its own part, so it takes the page's board, the hold and the
 * moments' wait once all three have settled for a read: while the GOL board brings a read's
 * moments, everything (the rows, the counts, the recap, the rival's side and the duel) stays as
 * the read before left it, so nothing moves or jumps under the board, and Canlı puan stands at
 * that read's total plus what the moments that have landed brought. The duel is drawn from that
 * one read whole (its Fark, its ends, Toplam fark and Farklar), so nothing in it disagrees.
 *
 * Each newer board drawn is told against the one before (`tell`): what it adds to the recap,
 * and how it moves (`liveMotion.ts`), which waits for the opening cover to go. What was drawn is
 * kept as the visitor's last look of the week (`liveLooks.ts`).
 */
function LiveShown({
  entryId,
  board,
  brought,
  waiting,
  team,
  own,
  rival,
  refreshing,
  reading,
  refresh,
  wide,
  windowOpen,
  light,
}: {
  /** The member the page is for. */
  entryId: number;
  board: LiveBoard;
  brought: number;
  waiting: boolean;
  team: string;
  own: boolean;
  rival: LiveRivalView | null;
  refreshing: boolean;
  /** A read is on its way: a refresh, or a followed one. */
  reading: boolean;
  refresh: () => void;
  wide: boolean;
  /** The follow window of the member's matches is open. */
  windowOpen: boolean;
  light: LiveLight;
}) {
  const rivalBoard = rival?.board ?? null;
  const rivalDuel = rival?.duel ?? null;
  const rivalId = rival?.entryId ?? null;
  const [settled, setSettled] = useState({ board, rivalBoard, rivalDuel, rivalId });
  if (
    !waiting &&
    (board !== settled.board ||
      rivalBoard !== settled.rivalBoard ||
      rivalDuel !== settled.rivalDuel ||
      rivalId !== settled.rivalId)
  ) {
    setSettled({ board, rivalBoard, rivalDuel, rivalId });
  }
  const holding = waiting && settled.board.gameweek === board.gameweek;
  const drawn = holding ? settled.board : board;
  const drawnRival = useMemo(
    () => (rival === null || !holding ? rival : heldRival(rival, settled)),
    [rival, holding, settled],
  );
  const gained = holding ? brought : 0;
  const drawnDuel = duelLook(drawn, drawnRival);
  const gate: MotionGate = useCoverGone() ? "open" : "wait";

  // What the reads since the visitor last looked brought the member: each newer board adds
  // to it, and Yenile or a return to the page (the visitor looking again) clears it. A look
  // clears it with the first newer board drawn after it, or, where no read is on its way, at
  // once: the recap changes once for a look, never under the board.
  const [told, setTold] = useState<Told>(() => toldAtOpen(drawn));
  const [lookLater, setLookLater] = useState(false);
  if (drawn !== told.board) {
    const newer =
      told.board === null ||
      lookKey(drawn) !== lookKey(told.board) ||
      Date.parse(drawn.sourceTime) > Date.parse(told.board.sourceTime);
    const clear = lookLater && !holding && (newer || !reading);
    if (clear) setLookLater(false);
    setTold((current) => tell(current, drawn, drawnDuel, clear));
  } else if (lookLater && !holding && !reading) {
    setLookLater(false);
    setTold((current) => ({ ...current, recap: lookedAt(current.recap) }));
  } else if (!holding && told.look !== null && !sameDuel(told.look.rival, drawnDuel)) {
    // The duel drawn changed without a read (the rival's first read, another rival): the next
    // read moves the duel from where it now stands.
    setTold((current) =>
      current.look === null ? current : { ...current, look: { ...current.look, rival: drawnDuel } },
    );
  }
  const look = useCallback(() => setLookLater(true), [setLookLater]);
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") look();
    };
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) look();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onShow);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", onShow);
    };
  }, [look]);
  const onRefresh = useCallback(() => {
    look();
    refresh();
  }, [look, refresh]);

  // What was drawn is what the visitor last saw of the week.
  useEffect(() => {
    if (told.look !== null && told.recap !== null) keepLook(told.look, told.recap);
  }, [told.look, told.recap]);

  // The heading's light: one of the member's own rows is being played in the board drawn. The
  // follow window stays open longer, up to three hours from a kickoff FPL has not finished,
  // only to time the reads; the board ends a match at its bound, as its groups and Maçlar do.
  // It breathes for a newer read drawn, once the opening cover has gone.
  const plan = told.plan;
  const playing = windowOpen && drawn.rows.some((row) => row.phase === "playing");
  const breath = plan !== null && plan.playing && gate === "open" ? plan.token : null;
  useEffect(() => light.set({ entryId, playing, breath }), [light, entryId, playing, breath]);
  useEffect(() => () => light.set(null), [light]);

  // Farklar: closed on a phone, open on a tablet and beside the page, until the member opens
  // or closes it; that choice then stands, through a change of rival too.
  const layout = useShellLayout();
  const [open, setOpen] = useState<boolean | null>(null);
  const recap = useMemo(() => recapItems(told.recap), [told.recap]);
  return (
    <LiveView
      team={team}
      board={drawn}
      net={drawn.net + gained}
      recap={recap}
      own={own}
      rival={drawnRival}
      refreshing={refreshing}
      onRefresh={onRefresh}
      wide={wide}
      differentialsOpen={open ?? (wide || layout !== "phone")}
      onDifferentialsToggle={setOpen}
      plan={plan}
      gate={gate}
    />
  );
}
