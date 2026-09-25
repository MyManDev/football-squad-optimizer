import { useMemo, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useShellLayout } from "../../../design/shell/layout";
import { useShell } from "../../../design/shell/ShellContext";
import { ShellPortal } from "../../../design/shell/ShellPortal";
import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures } from "../../../lib/clubs";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { MemberDecisionControls } from "../advice/MemberDecisionControls";
import { DecisionPreferencesPanel } from "../advice/DecisionPreferencesPanel";
import { ModelComparison } from "../advice/ModelComparison";
import { DecisionWorkbench } from "../advice/DecisionWorkbench";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import type { AdviceJob } from "../advice/useAdviceJob";
import { useViewerEntry } from "../identity/useViewerEntry";
import { TemplatePicker } from "../templates/TemplatePicker";
import { MemberResourceCards } from "../components/MemberResourceCards";
import { ChipForecastCard } from "../components/ChipForecastCard";
import { MemberFixtureRail, type RailPlacement } from "../components/MemberFixtureRail";
import { DisclosureIcon, InfoIcon } from "../components/memberIcons";
import { isMemberStrategy } from "../types";
import {
  AdviceDecision,
  AdviceDetails,
  AdviceMethodNotes,
  AdviceStamp,
  MissingAdviceCard,
  PlanLineup,
} from "./MemberAdviceCard";
import { HeldSquad, MemberSquad } from "./MemberSquad";
import { hasLineup, squadOnPitch } from "./squadOnPitch";
import { MemberTopBar, MemberWho } from "./MemberTopBar";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { useMemberAdviceView } from "./useMemberAdviceView";
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
 * on a phone the plan and Hesapla live in the drawer, and this is what is left in view once
 * the drawer closes. Nothing while no request was made.
 */
function computeEcho(copy: MemberCopy, state: AdviceJob["state"]): string | null {
  const states = copy.computeEchoStates;
  const word =
    state.phase === "requesting"
      ? states.requesting
      : state.phase === "waiting"
        ? state.status === "queued"
          ? states.queued
          : states.running
        : state.phase === "done"
          ? state.source === "api-cache"
            ? states.done
            : states.published
          : state.phase === "failed"
            ? states.failed
            : state.phase === "unavailable"
              ? states.unavailable
              : null;
  return word === null ? null : copy.computeEcho(word);
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
  adviceIssue,
  adviceLoading = false,
  membersIssue,
  onRetryAdvice,
  onRetryIndex,
  members = [],
  outcomeFreshness,
  index = null,
  client,
  capabilities = null,
  computeService = "static",
  computePending = false,
  rivalSquad = null,
  windowControl = null,
  deadlinePassed = null,
  fixtures = null,
  leagueName,
}: LeagueMemberViewProps) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const layout = useShellLayout();
  const shell = useShell();
  const view = squad.payload;
  const [searchParams] = useSearchParams();
  const { viewer, clear } = useViewerEntry();
  const navigate = useNavigate();
  const {
    entryId,
    resolve,
    selection,
    indexReadable,
    selectionAvailable,
    computeAvailable,
    job,
    request,
    shown,
    computedForecast,
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
    },
    searchParams,
  );
  // With the service answering, a selection it computes and nobody published is not a
  // dead end: the panel offers the computation and no "not listed" card stands beside it.
  const computeOnly =
    computeAvailable && selection.computable !== undefined && selection.status === "not-listed";
  const selectedRival = members.find(
    (member) => member.entry_id === selection.request.rivalEntryId,
  );
  const modelShown =
    capabilities?.models?.includes("football") === true || selection.request.model === "football";
  const selectionSummary = [
    isMemberStrategy(selection.request.strategy)
      ? copy.strategies[selection.request.strategy].name
      : {
          garantici: messages.decision.modes.safe,
          agresif: messages.decision.modes.aggressive,
          "asiri-agresif": messages.decision.modes.extreme,
        }[selection.request.strategy],
    messages.decision.week(selection.request.window),
    modelShown
      ? copy.modelNames[selection.request.model === "football" ? "football" : "current"]
      : null,
    selection.request.rivalEntryId !== null
      ? `${copy.rivalLabel}: ${selectedRival?.team_name ?? selectedRival?.manager_name ?? `#${selection.request.rivalEntryId}`}`
      : null,
    selection.top100.weight !== 0 ? copy.top100Weight(selection.top100.weight) : null,
    selection.evidence.on ? EVIDENCE_COPY[language].legend : null,
    selection.chip.chip ? copy.chipNames[selection.chip.chip] : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const echo = computeEcho(copy, job.state);
  const dateTime = (iso: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
      new Date(iso),
    );
  const played =
    outcomeFreshness?.scoredGameweek != null && outcomeFreshness.scoredGameweek >= view.gameweek;
  const codes = useMemo(() => clubCodesFromFixtures(fixtures), [fixtures]);
  const plan = !adviceLoading && shown ? shown.envelope.payload : null;
  const onPitch = squadOnPitch(plan, view);
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
      season={view.season}
      gameweek={view.gameweek}
      moves={plan?.moves ?? []}
      eleven={onPitch.eleven}
      codes={codes}
    />
  );

  return (
    <div className={styles.layout} data-rail={railPlacement}>
      <div className={styles.page}>
        <MemberTopBar
          squad={squad}
          members={members}
          fixtures={fixtures}
          deadlinePassed={deadlinePassed}
        />
        <ShellPortal slot="who">
          <MemberWho squad={squad} leagueName={leagueName} />
        </ShellPortal>

        {deadlinePassed !== null ? (
          <section className={styles.notice} aria-labelledby="deadline-passed-title">
            <h2 className={styles.noticeTitle} id="deadline-passed-title">
              {COMPUTE_COPY[language].deadlinePassedTitle}
            </h2>
            <p data-testid="deadline-passed">
              {COMPUTE_COPY[language].deadlinePassedBody(view.gameweek, dateTime(deadlinePassed))}
            </p>
          </section>
        ) : null}
        {played ? (
          <p className={styles.notice} role="status">
            {copy.freshnessPlayed}
          </p>
        ) : null}
        {membersIssue ? (
          <p className={styles.notice}>
            <strong>
              {membersIssue === "missing" ? copy.notAvailable : copy.membersUnreadable}
            </strong>{" "}
            {copy.membersAuxiliaryUnavailable}
          </p>
        ) : null}

        <ShellPortal slot="plan">
          <MemberDecisionControls
            entryId={entryId}
            members={members}
            index={selection.status === "index-error" ? null : index}
            capabilities={capabilities}
            part="plan"
          />
          <AdviceRequestPanel
            dockClassName={styles.computeDock}
            request={request}
            job={job}
            selectionAvailable={
              selectionAvailable &&
              !selection.evidence.on &&
              selection.top100.weight === 0 &&
              selection.chip.chip === null
            }
            service={
              selection.computable
                ? "ready"
                : computeService === "ready"
                  ? "static"
                  : computeService
            }
            computable={computeAvailable}
            pending={computePending}
            published={
              adviceLoading || !indexReadable
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
            deadlinePassed={deadlinePassed !== null}
          />
          <MemberDecisionControls
            entryId={entryId}
            members={members}
            index={selection.status === "index-error" ? null : index}
            capabilities={capabilities}
            part="notes"
          />
        </ShellPortal>

        <section aria-labelledby="entry-advice-title" className={styles.adviceSection}>
          <div className={styles.decision} data-mark="decision">
            <div className={styles.headingRow}>
              <div className={styles.headingText}>
                <h2 className={styles.decisionTitle} id="entry-advice-title">
                  {copy.decisionTitle}
                </h2>
                <p className={styles.selectionSummary} data-testid="member-selection-summary">
                  {selectionSummary}
                </p>
                <p className={styles.echo} aria-live="polite">
                  {echo}
                </p>
              </div>
              {!adviceLoading && shown ? <AdviceStamp shown={shown} /> : null}
            </div>
            {adviceLoading ? (
              <EmptyState title={copy.loadingAdvice} />
            ) : shown ? (
              <AdviceDecision shown={shown} members={members} squad={squad} fixtures={fixtures} />
            ) : computeOnly && !rejectedContext ? null : (
              <MissingAdviceCard
                issue={
                  rejectedContext
                    ? "context-mismatch"
                    : rejectedUnreadable
                      ? "unavailable"
                      : (adviceIssue ??
                        (selection.status !== "ready" ? selection.status : "not-computed"))
                }
                reason={selection.reason}
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
                canCompute={computeAvailable}
              />
            )}
          </div>
          <div className={styles.squadArea}>
            <div className={styles.squadGrid}>
              <MemberSquad
                onPitch={onPitch}
                plan={plan}
                codes={codes}
                list={plan && hasLineup(plan) ? <PlanLineup view={plan} codes={codes} /> : null}
              />
              {railPlacement === "flow" ? rail : null}
            </div>
          </div>
          <div className={styles.honestyBlock} data-mark="honesty">
            <div className={styles.honestyLines}>
              <p>{copy.honestyModel}</p>
              <p>{copy.honestyDecision}</p>
            </div>
            <details className={styles.how}>
              <summary className={styles.howSummary}>
                <InfoIcon />
                <span>{copy.howComputed}</span>
              </summary>
              <div className={styles.howBody}>
                <p>{copy.honestyRule}</p>
                <p>{copy.independentAdviceRule}</p>
                {!adviceLoading && shown ? (
                  <AdviceMethodNotes view={shown.envelope.payload} />
                ) : null}
                <p>{copy.diagnosticOnly}</p>
                <h3 className={styles.howTitle}>{copy.freshnessTitle}</h3>
                <p>{copy.freshnessDecision(view.gameweek, dateTime(squad.generated_at_utc))}</p>
                {outcomeFreshness ? (
                  <p>
                    {copy.freshnessScored(
                      outcomeFreshness.scoredGameweek == null
                        ? copy.freshnessNoScored
                        : messages.common.gameweekShort(outcomeFreshness.scoredGameweek),
                      dateTime(outcomeFreshness.publishedAt),
                    )}
                  </p>
                ) : null}
                <p>{copy.freshnessNote}</p>
              </div>
            </details>
            {view.league_id === 352490 ? (
              <p className={styles.historyLink}>
                <Link to={`/league/members/${entryId}/history`}>
                  {messages.suggestionHistory.title}
                </Link>
              </p>
            ) : null}
          </div>
          {!adviceLoading && shown ? (
            <AdviceDetails
              shown={shown}
              squad={squad}
              rivalSquad={rivalSquad}
              windowControl={windowControl}
            />
          ) : null}
        </section>

        {viewer ? (
          <Card tone="muted" title={copy.viewerTitle}>
            <p className={styles.notice}>{copy.viewerBody}</p>
            <p className={styles.notice}>
              <strong>
                {copy.viewerSelected(
                  viewer.entryId === entryId
                    ? (view.entry.manager_name ?? `#${viewer.entryId}`)
                    : `#${viewer.entryId}`,
                )}
              </strong>{" "}
              <Link className={styles.viewerAction} to="/league/members">
                {copy.viewerChange}
              </Link>{" "}
              <button
                type="button"
                className={styles.viewerClear}
                onClick={() => {
                  clear();
                  navigate("/league/members", { replace: true });
                }}
              >
                {copy.viewerClear}
              </button>
            </p>
            {viewer.entryId !== entryId ? (
              <p className={styles.notice}>
                <strong>{copy.notYourPageTitle}</strong> {copy.notYourPageBody}{" "}
                <Link to={`/league/members/${viewer.entryId}`}>{copy.notYourPageLink}</Link>
              </p>
            ) : null}
          </Card>
        ) : null}

        <div className={styles.tools}>
          {onPitch.source === "plan" && view.starting_xi.length > 0 ? (
            <Tool title={copy.memberSquad}>
              <HeldSquad squad={view} codes={codes} />
            </Tool>
          ) : null}
          <Tool title={copy.advancedSettings}>
            <MemberDecisionControls
              entryId={entryId}
              members={members}
              index={selection.status === "index-error" ? null : index}
              capabilities={capabilities}
              part="advanced"
            />
            <TemplatePicker
              canApply={(params) => {
                const offered = resolve(params);
                return (
                  !adviceLoading &&
                  indexReadable &&
                  (offered.status === "ready" || offered.computable?.selection === true)
                );
              }}
            />
          </Tool>
          <Tool title={copy.decisionTools}>
            <DecisionPreferencesPanel squad={view} available={capabilities?.preferences === true} />
            <DecisionWorkbench
              request={{
                ...request,
                top100Weight: selection.top100.weight,
                managersWord: selection.evidence.on,
                chip: selection.chip.chip,
              }}
              selected={shown?.envelope ?? null}
              squad={squad}
              loading={adviceLoading}
            />
            {capabilities?.models?.includes("football") && computeAvailable ? (
              <ModelComparison
                request={request}
                selected={shown?.envelope ?? null}
                snapshot={view.source_snapshot_id}
                client={client}
                deadlinePassed={deadlinePassed !== null}
                busy={job.state.phase === "waiting" || job.state.phase === "requesting"}
              />
            ) : null}
          </Tool>
          <Tool title={copy.chipsAndTransfers}>
            <MemberResourceCards squad={view} />
            <ChipForecastCard
              published={indexReadable ? index?.chip_forecast : undefined}
              computed={computedForecast}
              squad={view}
            />
          </Tool>
        </div>
      </div>
      {railPlacement === "column" ? rail : null}
      {railPlacement === "sheet" ? createPortal(rail, document.body) : null}
    </div>
  );
}
