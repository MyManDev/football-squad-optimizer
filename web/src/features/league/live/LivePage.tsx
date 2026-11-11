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
 * member and the rival are scored from the same live document; the rival's bundle, the two
 * seasons (a classic league's total gap) and a head-to-head league's pairings are read once.
 */

import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useParams, useSearchParams } from "react-router";

import { recordUsage } from "../../../data/usage";
import { useLanguage } from "../../../i18n/context";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { GoalMomentLayer } from "../../liveScore/GoalMoment";
import type { LiveWindowFilter } from "../../liveScore/liveWindow";
import type { DevicePlanDocument } from "../device/types";
import { useForwardedLeague } from "../forwarded/ForwardedLeagueContext";
import { defaultRivalOf } from "../forwarded/forwardedTree";
import { forwarder as siteForwarder } from "../forwarder/client";
import { useClaimedEntry } from "../identity/useLeagueIdentity";
import { LEAGUE_READ, leagueKeys, useEntrySquad } from "../queries";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { liveBoard, liveRecap, type LiveBoard, type RecapItem } from "./liveBoard";
import { liveDuel, seasonTotalBefore } from "./liveDuel";
import { addressedRival, chooseRival, h2hOpponent, rivalChoices } from "./liveRival";
import {
  bundleQuery,
  createLiveRecord,
  liveSources,
  seasonQuery,
  tableQuery,
  type LiveForwarder,
} from "./liveSources";
import { LiveView } from "./LiveView";
import { useBoardMoments } from "./useBoardMoments";
import { useGoalReplay } from "./useGoalReplay";
import { useLiveWindow } from "./useLiveWindow";
import { useMemberLiveScore } from "./useMemberLiveScore";
import { useWide } from "./useWide";

/** The reads the page makes; the site's own unless a test injects them. */
export interface LiveDependencies {
  forwarder?: LiveForwarder;
  loadTable?: (signal: AbortSignal) => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
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
  const frame = (state: "loading" | "empty", team = "") => (
    <LiveView
      team={team}
      gameweek={null}
      playing={false}
      state={state}
      board={null}
      recap={[]}
      own={false}
      rival={null}
      refreshing={false}
      onRefresh={() => undefined}
      wide={wide}
    />
  );
  if (!valid) return frame("empty");
  if (squad.isPending || fixtures.isPending) return frame("loading");
  if (squad.isError) return frame("empty");
  return (
    <LiveMember
      key={entryId}
      squad={squad.data}
      fixtures={fixtures.data ?? null}
      dependencies={dependencies}
      wide={wide}
      unnamed={messages.leagueMembers.unknownTeam}
    />
  );
}

function LiveMember({
  squad,
  fixtures,
  dependencies = {},
  wide,
  unnamed,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  fixtures: FixturesPayload | null;
  dependencies?: LiveDependencies;
  wide: boolean;
  unnamed: string;
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
    () => injectedTable ?? ((signal: AbortSignal) => tree.devicePlan(capture, { signal })),
    [injectedTable, tree, capture],
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
    replaying || !liveMatch.open ? null : liveMatch.gameweek,
  );
  if (live.matches !== null && live.matches !== matchFilter) setMatchFilter(live.matches);
  const replay = useGoalReplay(view, fixtures, sources, replaying && ready);
  // The board's batches, numbered as the member page numbers them: the replay and the real
  // reads are two streams, so one never swallows or replays the other's moment.
  const stream = useBoardMoments(live, entryId);
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
  const reading = week === null ? null : (snapshot.readings.get(week) ?? null);
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
  const seasons = useQueries({
    queries: [entryId, rivalId ?? 0].map((id) => ({
      ...seasonQuery(forwarder, id),
      ...LEAGUE_READ,
      enabled: ready && classic && rivalId !== null,
    })),
  });
  const [ownSeason, rivalSeason] = seasons.map((season) => season.data ?? null);
  const totals =
    week !== null && ownSeason && rivalSeason
      ? { member: seasonTotalBefore(ownSeason, week), rival: seasonTotalBefore(rivalSeason, week) }
      : null;
  const duel =
    board !== null && rivalBoard !== null
      ? liveDuel(board, rivalBoard, classic ? totals : null)
      : null;

  // What the newest read changed against the board shown before it; a board scored again
  // from the same read keeps the recap it had.
  const [shown, setShown] = useState<{ board: LiveBoard | null; recap: RecapItem[] }>({
    board: null,
    recap: [],
  });
  if (board !== null && board !== shown.board) {
    const newer =
      shown.board === null || Date.parse(board.sourceTime) > Date.parse(shown.board.sourceTime);
    setShown({ board, recap: newer ? liveRecap(shown.board, board) : shown.recap });
  }

  const claimed = useClaimedEntry(leagueId);
  const team = view.entry.team_name ?? unnamed;
  const loading =
    ready &&
    board === null &&
    (memberBundle.isPending ||
      (memberWeek !== null &&
        (table.isPending || (reading === null && !snapshot.settled.has(memberWeek.gameweek)))));
  return (
    <>
      <GoalMomentLayer batch={goalBatch} />
      <LiveView
        team={team}
        gameweek={board?.gameweek ?? week}
        playing={liveMatch.open}
        state={board !== null ? "board" : loading ? "loading" : "empty"}
        board={board}
        recap={shown.recap}
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
                headToHead,
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
        onRefresh={live.refresh}
        wide={wide}
      />
    </>
  );
}
