import {
  entryAddress,
  memberAddress,
  memberHistoryAddress,
  type MemberTool,
} from "../../../lib/leagueAddresses";
import { useLeagueId } from "../useLeague";
import { NewInformationNotice } from "../advice/OfficialInformationCard";
import { QueryClientContext } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useSearchParams } from "react-router";

import { recordUsage } from "../../../data/usage";
import { EmptyState } from "../../../design/components/EmptyState";
import { useShellLayout } from "../../../design/shell/layout";
import { useShell } from "../../../design/shell/ShellContext";
import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures } from "../../../lib/clubs";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { ChipTimingCard } from "../advice/ChipTimingCard";
import { COMPUTE_COPY, jobStanding, type ComputeCopy } from "../advice/computeCopy";
import { gameweekDeadline } from "../advice/deadline";
import { MemberDecisionControls } from "../advice/MemberDecisionControls";
import { deviceEndedWithoutPlan } from "../device/useDevicePlan";
import { isDevicePlanEntry } from "../device/types";
import { advisedFifteen } from "../device/whatIf";
import { WhatIfPanel } from "../device/WhatIfPanel";
import { MemberLiveWeekView } from "../live/MemberLiveWeek";
import { cachedBundle } from "../live/liveSources";
import { useMemberLiveScore, type MemberLiveDependencies } from "../live/useMemberLiveScore";
import { forwarder as siteForwarder } from "../forwarder/client";
import { useLiveWindow } from "../live/useLiveWindow";
import { useGoalReplay } from "../live/useGoalReplay";
import { useBoardHold, useBoardMoments, useSettledRead } from "../live/useBoardMoments";
import {
  FOLLOW_INTERVAL_MS,
  SLOW_FOLLOW_MS,
  type LiveWindowFilter,
} from "../../liveScore/liveWindow";
import { GoalMomentLayer } from "../../liveScore/GoalMoment";
import { squadWithPlayedWeek } from "../live/memberLineup";
import { whatIfBasis } from "../device/whatIfDraft";
import { DecisionPreferencesPanel } from "../advice/DecisionPreferencesPanel";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import { coachAbsences } from "../advice/coachAbsences";
import type { AdviceJob } from "../advice/useAdviceJob";
import { TemplatePicker } from "../templates/TemplatePicker";
import { MemberResourceCards } from "../components/MemberResourceCards";
import { MemberFixtureRail, type RailPlacement } from "../components/MemberFixtureRail";
import { DisclosureIcon } from "../components/memberIcons";
import { isMemberStrategy } from "../types";
import { AdviceDecision, AdviceDetails, MissingAdviceCard, PlanLineup } from "./MemberAdviceCard";
import { ApplyOnFpl } from "./ApplyOnFpl";
import { HeldSquad, MemberSquad } from "./MemberSquad";
import { hasLineup, squadOnPitch } from "./squadOnPitch";
import { MemberTopBar } from "./MemberTopBar";
import { MemberSections } from "./MemberSections";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { useMemberAdviceView } from "./useMemberAdviceView";
import { rivalCandidates } from "../advice/adviceSelection";
import { canDuel, duelRivalId } from "./duelSides";
import { RivalDuel } from "./RivalDuel";
import { SquadCard } from "../card/SquadCard";
import { LastWeekCard } from "./LastWeekCard";
import { lastWeekResult } from "./lastWeekResult";
import { useWeekArrival } from "./weekArrival";
import styles from "./LeagueMemberPage.module.css";

export function LeagueMemberView(props: LeagueMemberViewProps) {
  const { squad } = props;
  const contextKey = [
    squad.payload.league_id,
    squad.payload.entry.entry_id,
    squad.payload.season,
    squad.payload.gameweek,
    squad.payload.source_snapshot_id,
    squad.generated_at_utc,
  ].join(":");
  // A new published squad invalidates both an old result and its in-flight request.
  return <LeagueMemberContent key={contextKey} {...props} />;
}

type MemberCopy = ReturnType<typeof useLanguage>["messages"]["leagueMembers"];

/**
 * The state of a request for this page's plan as one quiet line, for the decision heading:
 * it stays beside the result, while the settings sit further down the page. A waiting job's
 * place in line or count of stages goes with its word. Nothing while no request was made, nor
 * when the service could not be reached: the panel says that.
 */
function computeEcho(
  copy: MemberCopy,
  computeCopy: ComputeCopy,
  state: AdviceJob["state"],
): string | null {
  const states = copy.computeEchoStates;
  const word =
    state.phase === "requesting"
      ? states.requesting
      : state.phase === "waiting"
        ? state.status === null
          ? null
          : states[state.status]
        : state.phase === "done" && state.source !== "static-fallback"
          ? states.done
          : state.phase === "failed"
            ? states.failed
            : state.phase === "unavailable"
              ? states.unavailable
              : null;
  if (word === null) return null;
  const standing = state.phase === "waiting" ? jobStanding(computeCopy, state) : null;
  return copy.computeEcho(standing === null ? word : `${word}, ${standing}`);
}

/** A closed section of the page's secondary tools, read one click away. */
function Tool({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className={styles.tool}>
      <summary className={styles.toolSummary}>
        <DisclosureIcon className={styles.toolIcon} />
        <span>{title}</span>
      </summary>
      <div className={styles.toolBody}>{children}</div>
    </details>
  );
}

function LeagueMemberContent({
  squad,
  advice,
  coachNews = null,
  adviceIssue,
  adviceLoading = false,
  onRetryAdvice,
  onRetryIndex,
  members = [],
  index = null,
  client,
  capabilities = null,
  computeService = "static",
  computePending = false,
  deviceDependencies,
  whatIfDependencies,
  liveDependencies,
  deviceRivals,
  rivalSquad = null,
  duelSquad = null,
  duelIssue,
  windowControl = null,
  deadlinePassed = null,
  now,
  fixtures = null,
  fixturesPending = false,
  scoreboard = null,
  history = null,
  tool,
}: LeagueMemberViewProps) {
  useEffect(() => recordUsage({ step: "tool" }), [tool]);
  const { language, messages } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.leagueMembers;
  const layout = useShellLayout();
  const shell = useShell();
  const view = squad.payload;
  const news = useMemo(() => coachAbsences(coachNews ?? advice, squad), [coachNews, advice, squad]);
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    entryId,
    resolve,
    selection,
    indexReadable,
    selectionAvailable,
    computeAvailable,
    job,
    device,
    onDevice,
    rivalsLoading,
    request,
    shown,
    rejectedContext,
    rejectedUnreadable,
  } = useMemberAdviceView(
    {
      squad,
      advice,
      adviceIssue,
      adviceLoading,
      members,
      index,
      client,
      capabilities,
      computeService,
      deviceDependencies,
      deviceRivals,
    },
    searchParams,
  );
  // Past its deadline the week is closed: nothing is computed for it and none of its plans
  // can be applied, so the page leaves out what only changes or recomputes the plan.
  const closed = deadlinePassed !== null;
  // While one of the live week's matches is played the page follows it, whichever week it
  // shows: a goal by the member's players plays its moment on an open week's page too.
  // What the member's latest live read said (their clubs, the matches still unfinished), kept
  // while no read is made, so the window follows only their matches (the owner's decision 3).
  const [matchFilter, setMatchFilter] = useState<LiveWindowFilter>({});
  // The GOL replay opens from the address alone (`?replay=1`): it plays the member's live week's
  // goals, assists and automatic substitutions one by one, so the board can be seen when no
  // match is on.
  const replaying = searchParams.get("replay") === "1";
  // The member's bundle is read through the app's cache, under the forwarded gate's key, so
  // the phone bar's LIVE pill and LIVE itself read it no second time.
  const queryClient = useContext(QueryClientContext);
  const liveReads = useMemo<MemberLiveDependencies | undefined>(
    () =>
      liveDependencies ??
      (queryClient === undefined
        ? undefined
        : {
            forwarder: { ...siteForwarder, entryBundle: cachedBundle(siteForwarder, queryClient) },
          }),
    [liveDependencies, queryClient],
  );
  const liveMatch = useLiveWindow(fixtures, matchFilter);
  const liveWeek = useMemberLiveScore(
    view,
    fixtures,
    liveReads,
    (closed || liveMatch.open || liveMatch.slow) &&
      view.league_id === leagueId &&
      (!tool || tool === "current-squad"),
    // The replay stands in for the page's own reads: nothing follows while it plays. A match
    // that may still be played (stalled) is read now and then until its limit.
    replaying || !(liveMatch.open || liveMatch.slow) ? null : liveMatch.gameweek,
    liveMatch.open ? FOLLOW_INTERVAL_MS : SLOW_FOLLOW_MS,
  );
  if (liveWeek.matches !== null && liveWeek.matches !== matchFilter) {
    setMatchFilter(liveWeek.matches);
  }
  // One GOL layer for the page and its tools, which share this mounted page: it stays as the
  // member moves between them, so a moment already played never plays again on the way back.
  const replay = useGoalReplay(view, fixtures, liveReads, replaying && view.league_id === leagueId);
  const board = useBoardMoments(liveWeek, view.entry.entry_id);
  // The live score holds the points of the board's queued moments until each one's run lands;
  // the replay brings no real points, so it holds nothing.
  const hold = useBoardHold(replaying ? null : board);
  const goalBatch = replaying
    ? replay === null
      ? null
      : { id: `replay:${replay.id}`, items: replay.items }
    : board === null
      ? null
      : { id: `live:${board.id}`, items: board.items };
  const goalMoments = (
    <GoalMomentLayer
      batch={goalBatch}
      source={replaying ? "replay" : "live"}
      scoring={!replaying}
      onLanded={hold.landed}
    />
  );
  // While the board plays, the page draws the read from before its first moment: the card and
  // the pitch take the newest one together once its last moment has landed.
  const drawnLive = useSettledRead(liveWeek.shown, hold.waiting, String(view.entry.entry_id));
  const displayedSquad = closed ? squadWithPlayedWeek(view, drawnLive?.lineup ?? null) : view;
  // With the service answering, a selection it computes and nobody published is not a
  // dead end: the panel offers the computation and no "not listed" card stands beside it.
  // The same holds for a selection the member's device solves, until a run ends without a
  // plan: the card then says what is published again. Both hold only while the week is
  // open; a closed week has no panel, so the card says what is published.
  const computeOnly =
    selection.status === "not-listed" &&
    !closed &&
    ((computeAvailable && selection.computable !== undefined) ||
      (device.available && !deviceEndedWithoutPlan(device.state)));
  // The what-if mode starts from the plan on screen when it is a solved week without a chip.
  const advised = advisedFifteen(shown?.envelope.payload);
  // The duel (#1133): the other human members, and the one `?duel=` names among them.
  const duelCandidates = rivalCandidates(members, view.entry.entry_id);
  const duelId = duelRivalId(searchParams, members, view.entry.entry_id);
  // Looked up only for a plan with a rival: the list's system row has no entry id either, so a
  // plan with none would otherwise name that row.
  const selectedRival =
    selection.request.rivalEntryId == null
      ? undefined
      : members.find((member) => member.entry_id === selection.request.rivalEntryId);
  const rivalName = selectedRival?.team_name ?? selectedRival?.manager_name;
  const selectionSummary = [
    isMemberStrategy(selection.request.strategy)
      ? copy.strategies[selection.request.strategy].name
      : {
          garantici: messages.decision.modes.safe,
          agresif: messages.decision.modes.aggressive,
          "asiri-agresif": messages.decision.modes.extreme,
        }[selection.request.strategy],
    messages.decision.week(selection.request.window),
    selection.request.model === "football" ? copy.modelNames.football : null,
    rivalName ? `${copy.rivalLabel}: ${rivalName}` : null,
    selection.top100.weight !== 0 ? copy.top100Weight(selection.top100.weight) : null,
    selection.evidence.on ? EVIDENCE_COPY[language].legend : null,
    selection.chip.chip ? copy.chipNames[selection.chip.chip] : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const echo = computeEcho(copy, COMPUTE_COPY[language], job.state);
  const codes = useMemo(() => clubCodesFromFixtures(fixtures), [fixtures]);
  // The member's latest finished week, from the scoreboard and their history; null leaves
  // the page without the card.
  const lastWeek = lastWeekResult(view, scoreboard, history);
  const plan = !adviceLoading && shown ? shown.envelope.payload : null;
  const onPitch = squadOnPitch(closed ? null : plan, displayedSquad);
  // The week can still be changed only while the calendar states a deadline that is ahead:
  // an unknown deadline is not an open week, so nothing is offered to apply then.
  const weekOpen =
    deadlinePassed === null && gameweekDeadline(fixtures, view.season, view.gameweek) !== null;
  // The way to make the decision on the game's own page, in a new tab. It is placed in the
  // document where it is seen (the heading row, or the end of the decision on a phone), so
  // the tab order follows the screen.
  const apply = plan && weekOpen ? <ApplyOnFpl plan={plan} squad={view} /> : null;
  // The page arrives once, and its decision once it is drawn (weekArrival.ts).
  const arrival = useRef<HTMLDivElement>(null);
  useWeekArrival(arrival, !adviceLoading && !rivalsLoading && shown != null);
  // One fixture rail: its own column from 1180 px (and on a page rendered without the
  // shell), beside the squad on a tablet, and a sheet over the page on a phone.
  const railPlacement: RailPlacement = !shell
    ? "column"
    : layout === "phone"
      ? "sheet"
      : layout === "tablet"
        ? "flow"
        : "column";
  const rail = (
    <MemberFixtureRail
      placement={railPlacement}
      fixtures={fixtures}
      pending={fixturesPending}
      season={view.season}
      gameweek={view.gameweek}
      moves={closed ? [] : (plan?.moves ?? [])}
      eleven={onPitch.eleven}
      codes={codes}
    />
  );
  const squadArea = (
    <div className={styles.squadArea}>
      <div className={styles.squadGrid}>
        <MemberSquad
          pointsKind={closed ? "actual" : "expected"}
          onPitch={onPitch}
          plan={closed ? null : plan}
          codes={codes}
          news={news}
          held={displayedSquad}
          fixtures={fixtures}
          list={
            !closed && plan && hasLineup(plan) ? <PlanLineup view={plan} codes={codes} /> : null
          }
        />
        {railPlacement === "flow" ? rail : null}
      </div>
    </div>
  );

  // The plan's settings sit under the decision they change. A member opens the page to
  // read this week's move; the controls that recompute it are one link away, not in front.
  const planSettings = (
    <section
      id="plan-settings"
      aria-labelledby="plan-settings-title"
      className={styles.planSettings}
      // The decision's "change settings" link lands here; focus follows it.
      tabIndex={-1}
    >
      {/* The plan is chosen in one place: the templates head it as presets that set the same
          strategy and window as the controls under them. */}
      <MemberDecisionControls
        entryId={entryId}
        members={members}
        index={selection.status === "index-error" ? null : index}
        capabilities={capabilities}
        onDevice={onDevice}
        part="plan"
        presets={
          <TemplatePicker
            members={members}
            canApply={(params) => {
              const offered = resolve(params);
              return (
                !adviceLoading &&
                indexReadable &&
                (offered.status === "ready" || offered.computable?.selection === true)
              );
            }}
          />
        }
      />
      {/* The Top 100 influence stays in front, just after the plan: its options are useful
          enough not to fold away (#1248). */}
      <MemberDecisionControls
        entryId={entryId}
        members={members}
        index={selection.status === "index-error" ? null : index}
        capabilities={capabilities}
        onDevice={onDevice}
        part="top100"
      />
      {/* What a member changes rarely waits folded: the experimental model, beside the
          manager's word and the chips. */}
      <Tool title={copy.advancedSettings}>
        <MemberDecisionControls
          entryId={entryId}
          members={members}
          index={selection.status === "index-error" ? null : index}
          capabilities={capabilities}
          onDevice={onDevice}
          part="model"
        />
        <MemberDecisionControls
          entryId={entryId}
          members={members}
          index={selection.status === "index-error" ? null : index}
          capabilities={capabilities}
          onDevice={onDevice}
          part="advanced"
        />
        {/* Beside the chip control: the chip timing the device read with the plain plan. */}
        <ChipTimingCard
          squad={view}
          timing={device.state.phase === "done" ? device.state.chipTiming : null}
          fixtures={fixtures}
        />
        <DecisionPreferencesPanel squad={view} available={capabilities?.preferences === true} />
      </Tool>
      <AdviceRequestPanel
        dockClassName={styles.computeDock}
        request={request}
        job={job}
        device={device}
        selectionAvailable={
          selectionAvailable &&
          !selection.evidence.on &&
          selection.top100.weight === 0 &&
          selection.chip.chip === null
        }
        service={
          selection.computable ? "ready" : computeService === "ready" ? "static" : computeService
        }
        computable={computeAvailable}
        // While the rivals' documents are read, nothing is said yet about what can be
        // computed or what was published for this selection.
        pending={computePending || rivalsLoading}
        published={
          adviceLoading || rivalsLoading || !indexReadable
            ? undefined
            : selection.status === "not-listed" || selection.status === "declared-unavailable"
              ? false
              : selectionAvailable &&
                  advice &&
                  !adviceIssue &&
                  !rejectedContext &&
                  !rejectedUnreadable
                ? true
                : undefined
        }
        chipChosen={selection.chip.chip !== null}
      />
    </section>
  );

  // The member's tools, each its own page that the sidebar links (lib/leagueAddresses.ts);
  // a tool this member's week has nothing for is null and its page says so.
  const tools: Record<MemberTool, { title: string; body: ReactNode | null }> = {
    "current-squad": {
      title: copy.memberSquad,
      body:
        displayedSquad.starting_xi.length > 0 ? (
          <HeldSquad
            squad={displayedSquad}
            codes={codes}
            pointsKind={closed ? "actual" : "expected"}
          />
        ) : null,
    },
    "what-if": {
      title: copy.whatIfTitle,
      body:
        advised !== null && isDevicePlanEntry(view.device_plan) ? (
          <WhatIfPanel
            key={whatIfBasis(view, advised)}
            squad={view}
            advised={advised}
            dependencies={whatIfDependencies}
          />
        ) : null,
    },
    duel: {
      title: copy.duelTitle,
      body:
        canDuel(squad) && duelCandidates.length > 0 ? (
          <RivalDuel
            squad={squad}
            candidates={duelCandidates}
            selected={duelId}
            rival={duelSquad?.payload.entry.entry_id === duelId ? duelSquad : null}
            issue={duelIssue}
            onSelect={(rivalId) =>
              setSearchParams(
                (current) => {
                  const next = new URLSearchParams(current);
                  next.set("duel", String(rivalId));
                  return next;
                },
                { replace: true },
              )
            }
          />
        ) : null,
    },
    chips: { title: copy.chipsAndTransfers, body: <MemberResourceCards squad={view} /> },
    card: {
      title: copy.cardTitle,
      body:
        !adviceLoading && shown ? <SquadCard view={shown.envelope.payload} squad={view} /> : null,
    },
  };

  if (tool !== undefined) {
    const page = tools[tool];
    return (
      <>
        {goalMoments}
        <div className={styles.layout}>
          <div className={styles.page}>
            <MemberTopBar
              squad={squad}
              members={members}
              fixtures={fixtures}
              deadlinePassed={deadlinePassed}
              now={now}
            />
            <section aria-labelledby="member-tool-title" className={styles.toolBody}>
              <h2 className={styles.decisionTitle} id="member-tool-title">
                {page.title}
              </h2>
              {page.body ?? <EmptyState title={copy.toolEmpty} />}
            </section>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {goalMoments}
      <div ref={arrival} className={styles.layout} data-rail={railPlacement}>
        <div className={styles.page}>
          <MemberTopBar
            squad={squad}
            members={members}
            fixtures={fixtures}
            deadlinePassed={deadlinePassed}
            now={now}
          />
          {/* A phone's one column is long: the strip keeps its two parts a tap away, pinned
            under the phone bar once the decision has been read past. Wider layouts pin the
            top bar instead and show more of the page at once. */}
          {layout === "phone" ? <MemberSections closed={closed} /> : null}

          {deadlinePassed !== null ? (
            <p className={styles.deadlineNotice} role="status" data-testid="deadline-passed">
              {COMPUTE_COPY[language].deadlinePassedTitle}
            </p>
          ) : null}
          {/* The week being played (#1008), beside the notice that its deadline has passed. A
            closed week leaves the plan's settings out, so the card adds nothing to the open
            week's page. It needs the calendar for each club's id. */}
          {deadlinePassed !== null && fixtures !== null && view.league_id === leagueId ? (
            <MemberLiveWeekView
              squad={view}
              live={{ ...liveWeek, shown: drawnLive }}
              brought={drawnLive === liveWeek.shown ? 0 : hold.brought}
            />
          ) : null}

          {/* What the member's last finished week came to, before what this week decides. */}
          {lastWeek ? (
            <LastWeekCard
              result={lastWeek}
              historyHref={
                lastWeek.suggested !== null && view.league_id === leagueId && leagueId > 0
                  ? memberHistoryAddress(leagueId, entryId)
                  : null
              }
            />
          ) : null}

          <section aria-labelledby="entry-advice-title" className={styles.adviceSection}>
            <div className={styles.decision} data-mark="decision">
              <div className={styles.headingRow}>
                <div className={styles.headingText}>
                  {/* Once the deadline has passed the page is the week being played, not a
                    plan: the heading says so as a green mark with a pulsing light, and the
                    settings' summary goes with the plan. */}
                  <h2
                    className={styles.decisionTitle}
                    id="entry-advice-title"
                    data-live={closed || undefined}
                  >
                    {closed ? <span className={styles.liveLight} aria-hidden="true" /> : null}
                    {closed ? copy.liveWeek : copy.decisionTitle}
                  </h2>
                  {closed ? null : (
                    <p className={styles.selectionSummary} data-testid="member-selection-summary">
                      {selectionSummary}
                    </p>
                  )}
                  {/* The settings now sit under the decision, so the way to them is named
                    where the decision says which settings it was made under. A closed
                    week has no settings to go to. */}
                  {closed ? null : (
                    <a href="#plan-settings" className={styles.changePlan}>
                      {copy.changePlan}
                    </a>
                  )}
                  <p className={styles.echo} aria-live="polite">
                    {echo}
                  </p>
                </div>
                {layout === "phone" ? null : apply}
              </div>
              {/* Under LIVE WEEK nothing waits on the plan, which is not drawn there. */}
              {adviceLoading || rivalsLoading ? (
                closed ? null : (
                  <EmptyState title={adviceLoading ? copy.loadingAdvice : copy.loadingRivals} />
                )
              ) : shown ? (
                // Under LIVE WEEK the closed week's plan is not drawn: the week being played is.
                closed ? null : (
                  <AdviceDecision shown={shown} squad={squad} fixtures={fixtures} />
                )
              ) : computeOnly && !rejectedContext ? null : closed &&
                index?.menu === "device" ? null : ( // is to say. The card would only name a publication that never happens. // is no default plan to point at, and the squad and its score say what there // A device menu publishes no plan for any week: once the week is closed there
                <MissingAdviceCard
                  issue={
                    rejectedContext
                      ? "context-mismatch"
                      : rejectedUnreadable
                        ? "unavailable"
                        : (adviceIssue ??
                          (selection.status !== "ready" ? selection.status : "not-computed"))
                  }
                  onRetry={
                    adviceIssue === "index-error"
                      ? onRetryIndex
                      : rejectedContext ||
                          rejectedUnreadable ||
                          adviceIssue === "published-missing" ||
                          adviceIssue === "unavailable"
                        ? onRetryAdvice
                        : undefined
                  }
                  // With no service to ask, Hesapla only reads this same document again, and a
                  // press being answered is not offered again.
                  canCompute={
                    computeAvailable &&
                    !closed &&
                    computeService !== "static" &&
                    job.state.phase !== "requesting" &&
                    job.state.phase !== "waiting"
                  }
                  // The address the sidebar's own link lands on with no selection.
                  defaultPlan={
                    closed
                      ? leagueId > 0
                        ? memberAddress(leagueId, entryId)
                        : entryAddress(entryId)
                      : undefined
                  }
                />
              )}
              {layout === "phone" ? apply : null}
            </div>
            {squadArea}
            {/* One team on its own (league 0) has no league address for its history. */}
            {view.league_id === leagueId && leagueId > 0 ? (
              <p className={styles.historyLink}>
                <Link to={memberHistoryAddress(leagueId, entryId)}>
                  {messages.suggestionHistory.title}
                </Link>
              </p>
            ) : null}
            {!adviceLoading && shown && !closed ? (
              <>
                {/* It sends the member to Hesapla, which a closed week does not have. */}
                <NewInformationNotice
                  view={shown.envelope.payload}
                  latest={closed ? undefined : capabilities?.decisionInformation}
                />
                <AdviceDetails
                  shown={shown}
                  squad={squad}
                  rivalSquad={rivalSquad}
                  windowControl={windowControl}
                />
              </>
            ) : null}
          </section>

          {/* Every setting in it changes or recomputes a plan the closed week cannot apply. */}
          {closed ? null : planSettings}
        </div>
        {railPlacement === "column" ? rail : null}
        {railPlacement === "sheet" ? createPortal(rail, document.body) : null}
      </div>
    </>
  );
}
