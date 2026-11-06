import { useEffect, useMemo } from "react";
import { Link, useLocation, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures } from "../../../lib/clubs";
import { leagueAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { createAdviceClient, type AdviceClient, type AdviceRequest } from "../advice/adviceClient";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { useAdviceJob, sameAdviceRequest } from "../advice/useAdviceJob";
import { ChipTimingCard } from "../advice/ChipTimingCard";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { gameweekDeadline, passedDeadline, useMinuteClock } from "../advice/deadline";
import { useDevicePlan, type DevicePlanDependencies } from "../device/useDevicePlan";
import { forwarder } from "../forwarder/client";
import type { FplStandingRow } from "../forwarder/documents";
import { MemberLiveWeek } from "../live/MemberLiveWeek";
import type { MemberLiveDependencies } from "../live/useMemberLiveScore";
import { AdviceDecision, PlanLineup } from "../pages/MemberAdviceCard";
import { MemberPageSkeleton } from "../pages/MemberPageSkeleton";
import { MemberSquad } from "../pages/MemberSquad";
import type { ShownAdvice } from "../pages/memberPageTypes";
import { hasLineup, squadOnPitch } from "../pages/squadOnPitch";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { useLeague } from "../useLeague";
import { useForwardedLeague } from "./ForwardedLeagueContext";
import { ForwardedTreeProvider } from "./ForwardedTreeProvider";
import { currentMemberSquad, forwardedMemberSquad } from "./memberSquad";
import {
  newestDeviceTable,
  standingsPage,
  useCaptureTable,
  useDirectory,
  useEntryBundle,
  useForwardedStandings,
} from "./reads";
import page from "../pages/LeagueMemberPage.module.css";
import styles from "./ForwardedMemberPage.module.css";

/** The page's reads and clock; the site's own unless a test injects them. */
export interface ForwardedMemberDependencies {
  server?: AdviceClient;
  device?: DevicePlanDependencies;
  live?: MemberLiveDependencies;
  clock?: () => number;
}

/** The team's name and manager over the page, and the way back to its league's table. */
function MemberHeading({ title, manager = null }: { title: string; manager?: string | null }) {
  const { messages } = useLanguage();
  const league = useForwardedLeague();
  const location = useLocation();
  const page = standingsPage(location.state?.leaguePage);
  return (
    <header className={styles.heading}>
      <h1 className={styles.title}>{title}</h1>
      {manager ? <p className={styles.manager}>{manager}</p> : null}
      {league !== null ? (
        <p className={styles.back}>
          {league.leagueName ?? messages.forwarded.leagueTitle(league.leagueId)}
          {" · "}
          <Link to={`${leagueAddress(league.leagueId)}${page > 1 ? `?page=${page}` : ""}`}>
            {messages.forwarded.backToLeague}
          </Link>
        </p>
      ) : null}
    </header>
  );
}

/**
 * One FPL team's page read through the forwarder (#983 step 4): at `/entry/<id>` on its own,
 * or under a forwarded league as a member chosen from its table. The capture's own table is
 * the newest the directory names; the team's bundle is asked for that table's gameweek, and
 * the identity rule binds the two (`forwardedMemberSquad`). Bound, the page shows the
 * device's one-week plan, the chip timing card where its inputs hold, and once the deadline
 * has passed the current squad, locked controls and live score. Not bound, it says the plan
 * cannot be computed for this team this week, and shows nothing else.
 */
export function ForwardedMemberPage({
  dependencies = {},
}: {
  dependencies?: ForwardedMemberDependencies;
}) {
  const { messages } = useLanguage();
  const words = messages.forwarded;
  const { entryId: entryParam, tool } = useParams();
  const location = useLocation();
  const league = useForwardedLeague();
  const entryId = /^\d+$/.test(entryParam ?? "") ? Number(entryParam) : 0;
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const directory = useDirectory(valid && tool === undefined);
  const tableRef = directory.data ? newestDeviceTable(directory.data) : null;
  const table = useCaptureTable(tableRef);
  const gameweek = table.data?.payload.gameweek ?? null;
  const bundle = useEntryBundle(entryId, valid ? gameweek : null);
  const fixtures = useFixtures();
  const standings = useForwardedStandings(
    league?.leagueId ?? null,
    standingsPage(location.state?.leaguePage),
  );
  const standing: FplStandingRow | null =
    standings.data?.results.find((row) => row.entry === entryId) ?? null;
  const read = bundle.data;
  // Once the deadline has passed, the live card asks for the same bundle; the one read here
  // answers it, so the forwarder is asked once.
  const live = useMemo<MemberLiveDependencies>(
    () =>
      dependencies.live ?? {
        forwarder: {
          entryBundle: (entry, week, options) =>
            read?.ok && entry === entryId && week === gameweek
              ? Promise.resolve(read)
              : forwarder.entryBundle(entry, week, options),
          liveWeek: (week, options) => forwarder.liveWeek(week, options),
        },
      },
    [dependencies.live, read, entryId, gameweek],
  );
  const tableEnvelope = table.data ?? null;
  const calendar = fixtures.data ?? null;
  const built = useMemo(
    () =>
      read?.ok && tableEnvelope !== null
        ? forwardedMemberSquad({
            bundle: read.document,
            table: tableEnvelope,
            entryId,
            fixtures: calendar,
            leagueId: league?.leagueId ?? 0,
            standing,
          })
        : null,
    [read, tableEnvelope, entryId, calendar, league?.leagueId, standing],
  );
  const currentSquad = useMemo(
    () =>
      built?.ok && read?.ok && tableEnvelope !== null
        ? currentMemberSquad(built.squad.payload, read.document, tableEnvelope.payload)
        : null,
    [built, read, tableEnvelope],
  );

  if (tool !== undefined) return <EmptyState title={messages.shell.notFound} />;
  if (!valid) return <EmptyState title={messages.leagueMembers.invalidEntry} />;
  if (
    directory.isPending ||
    (tableRef !== null && table.isPending) ||
    (gameweek !== null && bundle.isPending) ||
    fixtures.isPending
  ) {
    return <MemberPageSkeleton />;
  }
  const fallbackTitle = standing?.entry_name || words.teamTitle(entryId);
  if (tableRef === null || tableEnvelope === null || gameweek === null) {
    return (
      <div className={styles.page}>
        <MemberHeading title={fallbackTitle} manager={standing?.player_name} />
        <p className={styles.state} role="status">
          {words.planNotComputable}
        </p>
      </div>
    );
  }
  if (read === undefined || !read.ok) {
    const missing =
      read !== undefined && (read.reason === "entry_not_found" || read.reason === "not_found");
    return (
      <div className={styles.page}>
        <MemberHeading title={fallbackTitle} manager={standing?.player_name} />
        <p className={styles.state} role="status">
          {missing ? words.teamNotFound(entryId) : words.teamUnavailable}
        </p>
        {missing ? null : (
          <button type="button" className={styles.retry} onClick={() => void bundle.refetch()}>
            {words.retry}
          </button>
        )}
      </div>
    );
  }
  if (built === null || !built.ok) {
    return (
      <div className={styles.page}>
        <MemberHeading
          title={standing?.entry_name || read.document.entry.name}
          manager={standing?.player_name}
        />
        <p className={styles.state} role="status" data-plan-not-computable>
          {words.planNotComputable}
        </p>
      </div>
    );
  }
  return (
    <ForwardedTreeProvider
      leagueId={league?.leagueId ?? 0}
      leagueName={league?.leagueName ?? ""}
      tableRef={tableRef}
      table={tableEnvelope}
    >
      <ForwardedMemberView
        squad={built.squad}
        currentSquad={currentSquad}
        fixtures={calendar}
        dependencies={{ ...dependencies, live }}
      />
    </ForwardedTreeProvider>
  );
}

/**
 * A bound team's week: before its deadline, a requested server or device plan, the squad
 * it fields and the chip timing card; once the deadline has passed, the squad remains with
 * locked controls and the live score. The plan is the plain one-week plan.
 */
export function ForwardedMemberView({
  squad,
  currentSquad = null,
  fixtures,
  dependencies = {},
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  currentSquad?: EntrySquad | null;
  fixtures: FixturesPayload | null;
  dependencies?: ForwardedMemberDependencies;
}) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
  const { tree } = useLeague();
  const client = useMemo(
    () => dependencies.server ?? createAdviceClient(tree.entryAdvice),
    [dependencies.server, tree],
  );
  const serverConfigured = Boolean(dependencies.server || import.meta.env.VITE_ADVICE_API_ORIGIN);
  const now = useMinuteClock(dependencies.clock);
  const closed =
    passedDeadline(gameweekDeadline(fixtures, view.season, view.gameweek), now) !== null;
  const request = useMemo<AdviceRequest>(
    () => ({
      publicEntry: true,
      leagueId: view.league_id,
      entryId: view.entry.entry_id,
      strategy: "saf-puan",
      window: 1,
      season: view.season,
      gameweek: view.gameweek,
    }),
    [view.league_id, view.entry.entry_id, view.season, view.gameweek],
  );
  const device = useDevicePlan(view, request, dependencies.device, []);
  const { state } = device;
  const job = useAdviceJob(client, false, view.source_snapshot_id);
  const { reset, resume } = job;
  // Only resume work this tab explicitly requested; opening a team never starts a solve.
  useEffect(() => {
    reset();
    if (!closed && serverConfigured) resume?.(request);
  }, [closed, serverConfigured, request, reset, resume]);
  const computed =
    job.state.phase === "done" && sameAdviceRequest(job.state.request, request)
      ? job.state.envelope
      : null;
  const shown: ShownAdvice | null =
    state.phase === "done"
      ? { envelope: state.envelope, origin: "computed" }
      : computed
        ? { envelope: computed, origin: "computed" }
        : null;
  const plan = closed ? null : (shown?.envelope.payload ?? null);
  const codes = useMemo(() => clubCodesFromFixtures(fixtures), [fixtures]);
  const displayedSquad = closed && currentSquad !== null ? currentSquad : view;
  const onPitch = squadOnPitch(plan, displayedSquad);
  const manager = view.entry.manager_name;
  const title = view.entry.team_name ?? messages.forwarded.teamTitle(view.entry.entry_id);

  return (
    <div className={styles.page} data-forwarded-member={view.entry.entry_id}>
      <MemberHeading title={title} manager={manager} />
      {closed ? (
        <>
          <section
            className={page.notice}
            aria-labelledby="deadline-passed-title"
            data-testid="deadline-passed"
          >
            <h2 className={page.noticeTitle} id="deadline-passed-title">
              {COMPUTE_COPY[language].deadlinePassedTitle}
            </h2>
          </section>
          {fixtures !== null ? (
            <MemberLiveWeek squad={view} fixtures={fixtures} dependencies={dependencies.live} />
          ) : null}
        </>
      ) : null}
      <section
        aria-labelledby="entry-advice-title"
        className={page.adviceSection}
        data-device-state={state.phase}
      >
        <div className={page.decision} data-mark="decision">
          <div className={page.headingRow}>
            <div className={page.headingText}>
              <h2 className={page.decisionTitle} id="entry-advice-title">
                {copy.decisionTitle}
              </h2>
            </div>
          </div>
          {!closed && shown ? (
            <AdviceDecision shown={shown} squad={squad} fixtures={fixtures} />
          ) : null}
          <AdviceRequestPanel
            disabled={closed}
            request={request}
            job={{
              ...job,
              compute: (asked) => {
                device.reset();
                job.compute(asked);
              },
            }}
            device={{
              ...device,
              run: () => {
                job.reset();
                device.run();
              },
            }}
            service="ready"
            computable={serverConfigured}
            serverLabel={COMPUTE_COPY[language].serverButton}
            compact
          />
        </div>
        <div className={page.squadArea}>
          <MemberSquad
            onPitch={onPitch}
            plan={plan}
            codes={codes}
            held={displayedSquad}
            fixtures={fixtures}
            list={plan && hasLineup(plan) ? <PlanLineup view={plan} codes={codes} /> : null}
          />
        </div>
        {!closed ? (
          <ChipTimingCard
            squad={view}
            timing={state.phase === "done" ? state.chipTiming : null}
            fixtures={fixtures}
          />
        ) : null}
      </section>
    </div>
  );
}
