import { Link, useNavigate, useSearchParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { MemberDecisionControls } from "../advice/MemberDecisionControls";
import { useViewerEntry } from "../identity/useViewerEntry";
import { TemplatePicker } from "../templates/TemplatePicker";
import { Pitch } from "../../squad/components/Pitch";
import { MemberResourceCards } from "../components/MemberResourceCards";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { AdviceCard, MissingAdviceCard } from "./MemberAdviceCard";
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
  rivalSquad = null,
}: LeagueMemberViewProps) {
  const { locale, messages } = useLanguage();
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

      <MemberResourceCards squad={view} />

      {view.starting_xi.length > 0 ? (
        <>
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
        </>
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
        {viewer !== null && viewer.entryId !== entryId ? (
          <Card tone="muted" title={copy.notYourPageTitle}>
            <p className={styles.notice}>
              {copy.notYourPageBody}{" "}
              <Link to={`/league/members/${viewer.entryId}`}>{copy.notYourPageLink}</Link>
            </p>
          </Card>
        ) : null}
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
            selection.computable ? "ready" : computeService === "ready" ? "static" : computeService
          }
          computable={computeAvailable}
          published={selection.status === "ready"}
          chipChosen={selection.chip.chip !== null}
        />
        {adviceLoading ? (
          <EmptyState title={copy.loadingAdvice} />
        ) : shown ? (
          <AdviceCard shown={shown} members={members} squad={squad} rivalSquad={rivalSquad} />
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
