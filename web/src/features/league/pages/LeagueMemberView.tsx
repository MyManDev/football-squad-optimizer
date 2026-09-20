import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { MemberDecisionControls } from "../advice/MemberDecisionControls";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import { useViewerEntry } from "../identity/useViewerEntry";
import { TemplatePicker } from "../templates/TemplatePicker";
import { Pitch } from "../../squad/components/Pitch";
import { MemberResourceCards } from "../components/MemberResourceCards";
import { ChipForecastCard } from "../components/ChipForecastCard";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { isMemberStrategy } from "../types";
import { AdviceCard, MissingAdviceCard } from "./MemberAdviceCard";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { useMemberAdviceView } from "./useMemberAdviceView";
import styles from "./LeagueMemberPage.module.css";

export function LeagueMemberView(props: LeagueMemberViewProps) {
  useEffect(() => {
    document.documentElement.classList.add(styles.memberPage);
    return () => document.documentElement.classList.remove(styles.memberPage);
  }, []);
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

function LeagueMemberContent({
  squad,
  advice,
  adviceIssue,
  adviceLoading = false,
  membersIssue,
  onRetryAdvice,
  onRetryIndex,
  members = [],
  index = null,
  client,
  capabilities = null,
  computeService = "static",
  computePending = false,
  rivalSquad = null,
  windowControl = null,
  deadlinePassed = null,
}: LeagueMemberViewProps) {
  const { language, locale, messages } = useLanguage();
  const [contextExpanded, setContextExpanded] = useState(
    () => window.matchMedia?.("(min-width: 641px)").matches ?? true,
  );
  useEffect(() => {
    const media = window.matchMedia?.("(min-width: 641px)");
    if (!media) return;
    const update = () => setContextExpanded(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const copy = messages.leagueMembers;
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
  const selectionSummary = [
    isMemberStrategy(selection.request.strategy)
      ? copy.strategies[selection.request.strategy].name
      : {
          garantici: messages.decision.modes.safe,
          agresif: messages.decision.modes.aggressive,
          "asiri-agresif": messages.decision.modes.extreme,
        }[selection.request.strategy],
    messages.decision.week(selection.request.window),
    selection.request.rivalEntryId !== null
      ? `${copy.rivalLabel}: ${selectedRival?.team_name ?? selectedRival?.manager_name ?? `#${selection.request.rivalEntryId}`}`
      : null,
    selection.top100.weight !== 0 ? `Top 100 ${selection.top100.weight}` : null,
    selection.evidence.on ? EVIDENCE_COPY[language].legend : null,
    selection.chip.chip ? copy.chipNames[selection.chip.chip] : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <Link className={styles.back} to="/league/members">
            {copy.backToMembers}
          </Link>
          <div className={styles.kicker}>
            {view.season} · {messages.common.gameweek(view.gameweek)} · #{view.entry.entry_id}
          </div>
          <h1 className={styles.title}>{view.entry.team_name ?? copy.unknownTeam}</h1>
          <p className={styles.lede}>{view.entry.manager_name ?? copy.unknownMember}</p>
          {view.league_id === 352490 && (
            <p>
              <Link to={`/league/members/${entryId}/history`}>
                {messages.suggestionHistory.title}
              </Link>
            </p>
          )}
        </div>
        <ExampleDataBadge sourceKind={squad.source_kind} />
      </header>

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
            <Link to="/league/members">{copy.viewerChange}</Link>{" "}
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
        </Card>
      ) : null}

      <MemberResourceCards squad={view} expanded={contextExpanded} />

      {view.starting_xi.length > 0 ? (
        <details className={styles.contextDetails} open={contextExpanded}>
          <summary>{contextExpanded ? copy.memberSquad : <h2>{copy.memberSquad}</h2>}</summary>
          <div className={styles.squadContext}>
            <Card
              tone="pitch"
              title={copy.memberSquad}
              aside={copy.starterCount(view.starting_xi.length)}
            >
              <Pitch starters={view.starting_xi} />
              <p className={styles.notice}>{copy.heldViceCaptainUnavailable}</p>
            </Card>
            <Card title={copy.bench} aside={copy.benchCount(view.bench.length)}>
              <div className={styles.bench}>
                {[...view.bench]
                  .sort(
                    (left, right) =>
                      (left.bench_order ?? Number.MAX_SAFE_INTEGER) -
                      (right.bench_order ?? Number.MAX_SAFE_INTEGER),
                  )
                  .map((player) => (
                    <div className={styles.benchRow} key={player.player_id}>
                      <span className="num">{player.bench_order ?? "—"}</span>
                      <strong>{player.name}</strong>
                      <span className={styles.muted}>
                        {player.team} · {player.position}
                      </span>
                      <span className={`${styles.benchPoints} num`}>
                        {points(player.expected_points, 1, locale)} xP
                      </span>
                    </div>
                  ))}
              </div>
            </Card>
          </div>
        </details>
      ) : (
        <EmptyState title={copy.emptySquad}>{copy.emptySquadBody}</EmptyState>
      )}

      {membersIssue ? (
        <Card
          tone="muted"
          title={membersIssue === "missing" ? copy.notAvailable : copy.membersUnreadable}
        >
          <p className={styles.notice}>{copy.membersAuxiliaryUnavailable}</p>
        </Card>
      ) : null}

      <section aria-labelledby="entry-advice-title" className={styles.adviceSection}>
        <h2 className="visually-hidden" id="entry-advice-title">
          {copy.advice}
        </h2>
        {deadlinePassed !== null ? (
          <Card tone="muted" title={COMPUTE_COPY[language].deadlinePassedTitle}>
            <p className={styles.notice} data-testid="deadline-passed">
              {COMPUTE_COPY[language].deadlinePassedBody(
                view.gameweek,
                new Intl.DateTimeFormat(locale, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(deadlinePassed)),
              )}
            </p>
          </Card>
        ) : null}
        {viewer !== null && viewer.entryId !== entryId ? (
          <Card tone="muted" title={copy.notYourPageTitle}>
            <p className={styles.notice}>
              {copy.notYourPageBody}{" "}
              <Link to={`/league/members/${viewer.entryId}`}>{copy.notYourPageLink}</Link>
            </p>
          </Card>
        ) : null}
        <ChipForecastCard
          published={indexReadable ? index?.chip_forecast : undefined}
          computed={computedForecast}
          squad={view}
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
        <MemberDecisionControls
          entryId={entryId}
          members={members}
          index={selection.status === "index-error" ? null : index}
          capabilities={capabilities}
        />
        <div className={styles.computeDock} data-compute-dock>
          <AdviceRequestPanel
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
        </div>
        <p className={styles.selectionSummary} data-testid="member-selection-summary">
          {selectionSummary}
        </p>
        {adviceLoading ? (
          <EmptyState title={copy.loadingAdvice} />
        ) : shown ? (
          <AdviceCard
            shown={shown}
            members={members}
            squad={squad}
            rivalSquad={rivalSquad}
            windowControl={windowControl}
          />
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
      </section>
    </div>
  );
}
