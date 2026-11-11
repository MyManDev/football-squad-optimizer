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
 * member and the rival are scored from the read the live week shows; the rival's bundle and
 * a head-to-head league's pairings are read once, and a published classic league's total gap
 * comes from the members table the page holds.
 *
 * The heading stands first in every state, so the one the shell focuses on arrival stays.
 * Canlı puan takes the GOL board's points as each moment lands, as the member page's card
 * does, and the rows and the recap take a read once its moments have landed.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
  useRef,
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
import {
  advanceRecap,
  liveBoard,
  lookedAt,
  recapItems,
  type LiveBoard,
  type LiveRecap,
} from "./liveBoard";
import { leagueTotalsBefore, liveDuel, type LiveDuel } from "./liveDuel";
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
import { useGoalReplay } from "./useGoalReplay";
import { useLiveWindow } from "./useLiveWindow";
import { useMemberLiveScore } from "./useMemberLiveScore";
import { useWide } from "./useWide";

/** The reads the page makes; the site's own unless a test injects them. */
export interface LiveDependencies {
  forwarder?: LiveForwarder;
  loadTable?: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
}

/** What the heading says of a member's week, once the page below it knows. */
interface LiveHead {
  entryId: number;
  gameweek: number | null;
  playing: boolean;
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
      />
    );
  }
  return (
    <div className={styles.page} data-live-page data-wide={wide || undefined}>
      <LiveHeader
        team={entry === undefined ? "" : (entry.payload.entry.team_name ?? unnamed)}
        gameweek={known?.gameweek ?? null}
        playing={known?.playing ?? false}
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
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  fixtures: FixturesPayload | null;
  dependencies?: LiveDependencies;
  wide: boolean;
  unnamed: string;
  onHead: (head: LiveHead) => void;
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
  const goalBatch = replaying
    ? replay === null
      ? null
      : { id: `replay:${replay.id}`, items: replay.items }
    : stream === null
      ? null
      : { id: `live:${stream.id}`, items: stream.items };

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
  // The last duel drawn holds its place, out of sight, while the next rival's bundle is read.
  // The first rival's, read after the member's board, holds the room of a level duel, so its
  // arrival moves nothing below it.
  const [kept, setKept] = useState<HeldDuel | null>(null);
  if (duel !== null && rivalBoard !== null && kept?.duel !== duel) {
    setKept({ duel, rivalNet: rivalBoard.net });
  }
  const rivalReading = duel === null && rivalId !== null && rivalBundle.isFetching;
  const pending = !rivalReading
    ? null
    : (kept ??
      (board === null
        ? null
        : { duel: liveDuel(board, board, classic ? totals : null), rivalNet: board.net }));

  const claimed = useClaimedEntry(leagueId);
  const gameweek = board?.gameweek ?? week;
  // The heading's light: one of the member's own rows is being played. The follow window
  // stays open longer, up to three hours from a kickoff FPL has not finished, only to time
  // the reads; the board ends a match at its bound, as its groups and Maçlar do.
  const playing =
    liveMatch.open && board !== null && board.rows.some((row) => row.phase === "playing");
  useEffect(() => onHead({ entryId, gameweek, playing }), [onHead, entryId, gameweek, playing]);
  const loading =
    ready &&
    board === null &&
    (memberBundle.isPending ||
      (memberWeek !== null &&
        (table.isPending || (reading === null && !snapshot.settled.has(memberWeek.gameweek)))));
  return (
    <>
      <GoalMomentLayer
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
          rival={
            // Drawn once the rival is chosen, so the picker never shows an empty choice first.
            standalone || waiting || choices.length === 0
              ? null
              : {
                  choices,
                  entryId: rivalId,
                  name: choices.find((choice) => choice.entryId === rivalId)?.name ?? null,
                  board: rivalBoard,
                  duel,
                  pending,
                  opponent: rivalId !== null && rivalId === opponent.data?.entryId,
                  onSelect: (next) =>
                    setSearchParams(
                      (current) => {
                        const params = new URLSearchParams(current);
                        params.set("duel", String(next));
                        return params;
                      },
                      { replace: true },
                    ),
                }
          }
          refreshing={live.refreshing}
          refresh={live.refresh}
          wide={wide}
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

/**
 * The board as it is shown. Its own part, so it takes the page's board, the hold and the
 * moments' wait once all three have settled for a read: while the GOL board brings a read's
 * moments, everything (the rows, the counts, the recap, the rival's side and the duel) stays as
 * the read before left it, so nothing moves or jumps under the board, and Canlı puan stands at
 * that read's total plus what the moments that have landed brought. The duel is drawn from that
 * one read whole (its Fark, its ends, Toplam fark and Farklar), so nothing in it disagrees.
 */
function LiveShown({
  board,
  brought,
  waiting,
  team,
  own,
  rival,
  refreshing,
  refresh,
  wide,
}: {
  board: LiveBoard;
  brought: number;
  waiting: boolean;
  team: string;
  own: boolean;
  rival: LiveRivalView | null;
  refreshing: boolean;
  refresh: () => void;
  wide: boolean;
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
  const drawnRival = rival === null || !holding ? rival : heldRival(rival, settled);
  const gained = holding ? brought : 0;

  // What the reads since the visitor last looked brought the member: each newer board adds
  // to it, and Yenile or a return to the page (the visitor looking again) clears it.
  const [told, setTold] = useState<{ board: LiveBoard | null; recap: LiveRecap | null }>({
    board: null,
    recap: null,
  });
  // A look while the board plays (Yenile, a return to the page) clears the recap once the board
  // has played out, before the read it brought is told, so nothing moves under the board.
  const holdingNow = useRef(holding);
  useEffect(() => {
    holdingNow.current = holding;
  });
  const [lookLater, setLookLater] = useState(false);
  if (!holding && lookLater) {
    setLookLater(false);
    setTold((current) => ({ ...current, recap: lookedAt(current.recap) }));
  }
  if (drawn !== told.board) {
    setTold((current) => ({ board: drawn, recap: advanceRecap(current.recap, drawn) }));
  }
  const look = useCallback(() => {
    if (holdingNow.current) setLookLater(true);
    else setTold((current) => ({ ...current, recap: lookedAt(current.recap) }));
  }, []);
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

  // Farklar: closed on a phone, open on a tablet and beside the page, until the member opens
  // or closes it; that choice then stands, through a change of rival too.
  const layout = useShellLayout();
  const [open, setOpen] = useState<boolean | null>(null);
  return (
    <LiveView
      team={team}
      board={drawn}
      net={drawn.net + gained}
      recap={recapItems(told.recap)}
      own={own}
      rival={drawnRival}
      refreshing={refreshing}
      onRefresh={onRefresh}
      wide={wide}
      differentialsOpen={open ?? (wide || layout !== "phone")}
      onDifferentialsToggle={setOpen}
    />
  );
}
