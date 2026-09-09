import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { createAdviceClient, type AdviceClient, type AdviceSource } from "../advice/adviceClient";
import {
  canComputeAdvice,
  resolvePublishedAdvice,
  type PublishedAdviceStatus,
} from "../advice/adviceSelection";
import { comparedRivalPlayers } from "../advice/rivalPlayers";
import { AdviceContextError, checkedAdvice } from "../advice/adviceResponse";
import { MemberDecisionControls } from "../advice/MemberDecisionControls";
import { sameAdviceRequest, useAdviceJob } from "../advice/useAdviceJob";
import { useViewerEntry } from "../identity/useViewerEntry";
import { TemplatePicker } from "../templates/TemplatePicker";
import { Pitch } from "../../squad/components/Pitch";
import { SquadPage } from "../../squad/pages/SquadPage";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import {
  LeagueDataMissing,
  loadEntryAdvice,
  loadEntryAdviceIndex,
  loadEntrySquad,
  loadLeagueMembers,
} from "../data";
import type {
  AdviceMove,
  AdvicePlayer,
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  EntryView,
  LeagueViewEnvelope,
} from "../types";
import styles from "./LeagueMemberPage.module.css";

/** Why no published advice is on hand for the selection: never published, or not loadable. */
export type AdviceIssue =
  | "not-computed"
  | "unavailable"
  | "published-missing"
  | "context-mismatch"
  | Exclude<PublishedAdviceStatus, "ready">;

export function LeagueMemberPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const entryParam = useParams().entryId;
  const entryId = Number(entryParam);
  const [searchParams] = useSearchParams();
  const validEntryId = Number.isSafeInteger(entryId) && entryId > 0;
  const squad = useQuery({
    queryKey: ["provisional-entry-squad", entryId],
    queryFn: () => loadEntrySquad(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
  });
  const membersQuery = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
    staleTime: 60_000,
  });
  // The index says which (strategy, rival) files the producer wrote for this member; a
  // missing or unreadable index cannot authorize a guessed baseline read.
  const indexQuery = useQuery({
    queryKey: ["provisional-entry-advice-index", entryId],
    queryFn: () => loadEntryAdviceIndex(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
    retry: false,
  });
  const members = membersQuery.data?.payload.members ?? [];
  const index = indexQuery.isError ? null : (indexQuery.data?.payload ?? null);
  const selection = resolvePublishedAdvice(
    searchParams,
    squad.data?.payload.league_id ?? 0,
    entryId,
    members,
    index,
    squad.data
      ? {
          season: squad.data.payload.season,
          gameweek: squad.data.payload.gameweek,
        }
      : undefined,
  );
  const { request } = selection;
  const adviceEnabled = validEntryId && !!squad.data && selection.status === "ready";

  const advice = useQuery({
    queryKey: [
      "provisional-entry-advice",
      entryId,
      request.strategy,
      request.window,
      request.rivalEntryId,
      selection.path,
      request.season,
      request.gameweek,
      squad.data?.payload.source_snapshot_id,
    ],
    queryFn: ({ signal }) =>
      loadEntryAdvice(entryId, request.strategy, request.window, request.rivalEntryId ?? null, {
        signal,
      }),
    enabled: adviceEnabled,
    staleTime: 60_000,
  });

  const rival = useQuery({
    queryKey: ["provisional-entry-squad", request.rivalEntryId],
    queryFn: () => loadEntrySquad(request.rivalEntryId!),
    enabled: adviceEnabled && request.rivalEntryId != null,
    staleTime: 60_000,
    retry: false,
  });

  if (entryParam === "squadopt") return <SystemLeagueMemberPage />;
  if (!validEntryId) return <EmptyState title={copy.invalidEntry} />;
  if (squad.isPending) return <EmptyState title={copy.loadingEntry} />;
  if (squad.isError) {
    const missing = squad.error instanceof LeagueDataMissing;
    return (
      <EmptyState title={missing ? copy.entryNotAvailable : copy.entryUnreadable}>
        <p>{missing ? copy.entryNotAvailableBody : copy.entryUnreadableBody}</p>
        <Link to="/league/members">{copy.backToMembers}</Link>{" "}
        {!missing ? (
          <button type="button" onClick={() => void squad.refetch()}>
            {copy.retryPublishedRead}
          </button>
        ) : null}
      </EmptyState>
    );
  }
  // Published advice that is missing or unloadable does not close the page: the member
  // context is valid, so the squad and the compute control stay, and the advice card says
  // what is missing. Only this pair is solved per member, so an unpublished combination
  // is a normal outcome rather than a fault the reader should report.
  const adviceIssue: AdviceIssue | undefined = indexQuery.isError
    ? indexQuery.error instanceof LeagueDataMissing
      ? "index-missing"
      : "index-error"
    : selection.status !== "ready"
      ? selection.status
      : advice.isError
        ? advice.error instanceof LeagueDataMissing
          ? "published-missing"
          : "unavailable"
        : undefined;
  return (
    <LeagueMemberView
      squad={squad.data}
      advice={adviceEnabled && !advice.isError ? (advice.data ?? null) : null}
      rivalSquad={rival.data ?? null}
      adviceIssue={adviceIssue}
      adviceLoading={indexQuery.isPending || (adviceEnabled && advice.isPending)}
      membersIssue={
        membersQuery.isError
          ? membersQuery.error instanceof LeagueDataMissing
            ? "missing"
            : "unavailable"
          : undefined
      }
      onRetryAdvice={() => void advice.refetch()}
      onRetryIndex={() => void indexQuery.refetch()}
      members={members}
      index={index}
    />
  );
}

function SystemLeagueMemberPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <div className={styles.systemPage}>
      <Link className={styles.back} to="/league/members">
        {copy.backToMembers}
      </Link>
      <Card
        title={copy.systemTeamTitle}
        aside={
          <Badge tone="accent">
            <span aria-hidden="true">◈</span> {copy.systemTeamBadge}
          </Badge>
        }
      >
        <p className={styles.honesty}>{copy.independentAdviceRule}</p>
      </Card>
      <SquadPage />
    </div>
  );
}

/** What the advice card shows and where it came from. */
interface ShownAdvice {
  envelope: LeagueViewEnvelope<EntryAdvice>;
  origin: "computed" | "published" | "published-while-computing" | "baseline-while-computing";
  source?: AdviceSource;
}

interface LeagueMemberViewProps {
  squad: LeagueViewEnvelope<EntrySquad>;
  advice: LeagueViewEnvelope<EntryAdvice> | null;
  adviceIssue?: AdviceIssue;
  adviceLoading?: boolean;
  membersIssue?: "missing" | "unavailable";
  onRetryAdvice?: () => void;
  onRetryIndex?: () => void;
  members?: EntryView[];
  index?: EntryAdviceIndex | null;
  client?: AdviceClient;
  rivalSquad?: LeagueViewEnvelope<EntrySquad> | null;
}

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
  rivalSquad = null,
}: LeagueMemberViewProps) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
  const [searchParams] = useSearchParams();
  const { viewer, clear } = useViewerEntry();
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(params, leagueId, entryId, members, index, {
      season: view.season,
      gameweek: view.gameweek,
    });
  const selection = resolve(searchParams);
  const { request } = selection;
  const indexReadable = adviceIssue !== "index-missing" && adviceIssue !== "index-error";
  const selectionAvailable = !adviceLoading && indexReadable && selection.status === "ready";
  const baselineAvailable =
    resolve(new URLSearchParams("mode=saf-puan&window=1")).status === "ready";
  const job = useAdviceJob(adviceClient, baselineAvailable);
  const requestKey = [
    request.leagueId,
    request.entryId,
    request.strategy,
    request.window,
    request.rivalEntryId ?? "",
    selection.status,
    selection.path,
  ].join(":");

  // A new selection starts clean: an earlier request's answer, wait or failure must not
  // read as this member's, strategy's, window's or rival's.
  const { reset } = job;
  useEffect(() => {
    reset();
  }, [requestKey, reset]);

  const current =
    selectionAvailable &&
    job.state.phase !== "idle" &&
    sameAdviceRequest(job.state.request, request)
      ? job.state
      : null;
  const computed = current?.phase === "done" ? current : null;
  const waiting = current?.phase === "waiting" ? current : null;
  let published: LeagueViewEnvelope<EntryAdvice> | null = null;
  let rejectedContext = false;
  let rejectedUnreadable = false;
  if (advice && selectionAvailable) {
    try {
      const checked = checkedAdvice(advice, request);
      const snapshot = checked.payload.source_snapshot_id;
      rejectedContext =
        snapshot != null && view.source_snapshot_id != null && snapshot !== view.source_snapshot_id;
      published = rejectedContext ? null : checked;
    } catch (error) {
      rejectedContext = error instanceof AdviceContextError;
      rejectedUnreadable = !rejectedContext;
    }
  }
  let shown: ShownAdvice | null = null;
  if (computed) {
    shown = {
      envelope: computed.envelope,
      origin: computed.source === "api-cache" ? "computed" : "published",
      source: computed.source,
    };
  } else if (published) {
    shown = { envelope: published, origin: waiting ? "published-while-computing" : "published" };
  } else if (waiting?.fallback) {
    shown = { envelope: waiting.fallback, origin: "baseline-while-computing" };
  }

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
        </div>
        <ExampleDataBadge sourceKind={squad.source_kind} />
      </header>

      <Card tone="muted" title={copy.publicDataTitle}>
        <p className={styles.notice}>{copy.publicDataBody}</p>
      </Card>

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
            <button type="button" className={styles.viewerClear} onClick={clear}>
              {copy.viewerClear}
            </button>
          </p>
        </Card>
      ) : null}

      {view.data_quality !== "complete" ? (
        <Card tone="muted" title={copy.incompleteTitle}>
          <p className={styles.notice}>
            {copy.incompleteBody(
              view.missing_fields
                .map((field) =>
                  Object.hasOwn(copy.missingFieldLabels, field)
                    ? copy.missingFieldLabels[field]
                    : copy.missingFieldUnknown,
                )
                .join(", ") || copy.unknown,
            )}
          </p>
        </Card>
      ) : null}

      {!view.free_transfers_known || !view.purchase_prices_known ? (
        <Card tone="muted" title={copy.entryAssumptionsTitle}>
          <ul className={styles.assumptionList}>
            {!view.free_transfers_known ? (
              <li>{copy.freeTransfersAssumed(view.free_transfers)}</li>
            ) : null}
            {!view.purchase_prices_known ? <li>{copy.currentPriceFallback}</li> : null}
          </ul>
        </Card>
      ) : null}

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
          canApply={(params) =>
            !adviceLoading && indexReadable && resolve(params).status === "ready"
          }
        />
        <MemberDecisionControls
          entryId={entryId}
          members={members}
          index={selection.status === "index-error" ? null : index}
        />
        <AdviceRequestPanel request={request} job={job} selectionAvailable={selectionAvailable} />
        {adviceLoading ? (
          <EmptyState title={copy.loadingAdvice} />
        ) : shown ? (
          <AdviceCard shown={shown} members={members} squad={squad} rivalSquad={rivalSquad} />
        ) : (
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
            canCompute={selectionAvailable && canComputeAdvice(request)}
          />
        )}
      </section>
    </div>
  );
}

/**
 * Why no advice is shown, in the two states the page can tell apart. A combination the
 * producer never solved is a normal outcome; a document that failed to load is a fault,
 * and saying "not published yet" for it would tell the reader to wait for a publish that
 * already happened — on a page whose squad, read from the same build, is above it.
 */
function MissingAdviceCard({
  issue,
  canCompute,
  reason,
  onRetry,
}: {
  issue: AdviceIssue;
  canCompute: boolean;
  reason?: string | null;
  onRetry?: () => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const issueCopy =
    issue === "not-computed"
      ? [copy.adviceNotComputed, copy.adviceNotComputedBody]
      : issue === "unavailable"
        ? [copy.adviceUnreadable, copy.adviceUnreadableBody]
        : [copy.publicationStates[issue].title, copy.publicationStates[issue].body];
  return (
    <Card title={copy.advice}>
      <p className={styles.honesty}>
        <strong>{issueCopy[0]}</strong>
      </p>
      <p className={styles.muted}>{issueCopy[1]}</p>
      {reason ? (
        <p className={styles.muted}>
          {Object.hasOwn(copy.publicationReasons, reason)
            ? copy.publicationReasons[reason]
            : copy.publicationReasonUnknown}
        </p>
      ) : null}
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          {copy.retryPublishedRead}
        </button>
      ) : null}
      {canCompute ? <p className={styles.muted}>{copy.adviceRequestHint}</p> : null}
    </Card>
  );
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function hasPublishedPlan(view: EntryAdvice): boolean {
  return (
    (view.solver_status === "OPTIMAL" || view.solver_status === "FEASIBLE") &&
    view.starting_xi?.length === 11 &&
    view.bench?.length === 4 &&
    view.captain != null &&
    view.vice_captain != null
  );
}

function AdviceCard({
  shown,
  members = [],
  squad,
  rivalSquad,
}: {
  shown: ShownAdvice;
  members?: EntryView[];
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { envelope, origin } = shown;
  const view = envelope.payload;
  const rival =
    view.rival_entry_id === undefined
      ? null
      : (members.find(
          (member) => member.member_kind === "human" && member.entry_id === view.rival_entry_id,
        ) ?? null);
  const rivalName = rival ? (rival.team_name ?? rival.manager_name ?? null) : null;
  // A price tag is a difference between two solved plans. It is the cost itself only
  // where both proofs finished; where one did not, the producer publishes the bound it
  // measured as `expected_points_cost_ceiling` and this page states that — the most the
  // strategy can cost — instead of a figure it cannot stand behind. A document that is
  // unproven and carries no ceiling has no honest figure to print, so it prints none;
  // and a price below zero is a giveaway no constrained plan can hand out, so no
  // producer's number is rendered as one.
  const unproven = view.solver_status === "FEASIBLE" || view.control_solver_status === "FEASIBLE";
  const priceCeiling = view.expected_points_cost_ceiling;
  const price = unproven ? priceCeiling : (priceCeiling ?? view.expected_points_cost);
  const showsPrice = view.mode !== "saf-puan" && finiteNumber(price) && price >= 0;
  const alternative = view.alternative_plan;
  const alternativePrice = unproven
    ? alternative?.expected_points_cost_ceiling
    : (alternative?.expected_points_cost_ceiling ?? alternative?.expected_points_cost);
  return (
    <Card
      title={copy.advice}
      aside={
        <>
          {origin === "computed" ? <Badge tone="good">{copy.adviceComputedBadge}</Badge> : null}{" "}
          <ExampleDataBadge sourceKind={envelope.source_kind} />
        </>
      }
    >
      {origin === "published-while-computing" ? (
        <p className={styles.honesty}>{copy.advicePublishedWhileComputing}</p>
      ) : null}
      {origin === "baseline-while-computing" ? (
        <p className={styles.honesty}>{copy.adviceBaselineWhileComputing}</p>
      ) : null}
      <p className={styles.honesty}>{copy.honestyRule}</p>
      <p className={styles.honesty}>{copy.independentAdviceRule}</p>
      {view.solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {finiteNumber(view.optimality_gap)
            ? copy.unprovenPlanBody(points(view.optimality_gap, 1, locale))
            : copy.unprovenPlanGapUnknown}
        </p>
      ) : null}
      {showsPrice && price != null ? (
        <p className={styles.planCost}>
          <strong className="num">
            {unproven
              ? copy.planCostAtMost(points(price, 1, locale))
              : copy.planCost(points(price, 1, locale))}
          </strong>
          {(rivalName ?? view.rival_label) ? (
            <span> · {copy.planRival(rivalName ?? String(view.rival_label))}</span>
          ) : null}
        </p>
      ) : null}
      {view.control_solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {finiteNumber(view.control_optimality_gap)
            ? copy.controlUnprovenBody(points(view.control_optimality_gap, 1, locale))
            : copy.controlGapUnknown}
        </p>
      ) : null}
      {finiteNumber(view.overlap_count) && finiteNumber(view.expected_gap_vs_rival) ? (
        <p className={styles.muted}>
          {copy.overlapLine(view.overlap_count)} ·{" "}
          {copy.gapLine(signedPoints(view.expected_gap_vs_rival, 1, locale))}
          {view.captain_agreement ? ` · ${copy.captainShared}` : ""}
        </p>
      ) : null}
      {view.plan_kind && finiteNumber(view.transfer_cap) && finiteNumber(view.overlap_target) ? (
        <p className={styles.muted}>
          {view.plan_kind === "within_free_transfers"
            ? finiteNumber(view.overlap_applied)
              ? copy.planWithinFree(view.transfer_cap, view.overlap_target, view.overlap_applied)
              : copy.planWithinFreeUnknown(view.transfer_cap, view.overlap_target)
            : copy.planWithHits(view.transfer_cap, view.overlap_target)}
          {alternative &&
          finiteNumber(alternative.overlap_applied) &&
          finiteNumber(alternativePrice) &&
          alternativePrice >= 0
            ? ` ${
                alternative.kind === "with_hits"
                  ? (unproven ? copy.alternativeWithHitsAtMost : copy.alternativeWithHits)(
                      alternative.overlap_applied,
                      finiteNumber(alternative.transfer_hit_points)
                        ? points(alternative.transfer_hit_points, 0, locale)
                        : copy.hitPointsNotPublished,
                      points(alternativePrice, 1, locale),
                    )
                  : (unproven ? copy.alternativeWithinFreeAtMost : copy.alternativeWithinFree)(
                      alternative.overlap_applied,
                      points(alternativePrice, 1, locale),
                    )
              }`
            : ""}
        </p>
      ) : null}
      {view.moves.length === 0 ? (
        <p className={styles.muted}>{hasPublishedPlan(view) ? copy.noMove : copy.noPlanInRecord}</p>
      ) : (
        <>
          <div className={styles.moves}>
            {view.moves.map((move) => (
              <AdviceRow key={move.move_id} move={move} />
            ))}
          </div>
          {/* The week's hit charge, once, because the game charges the week and not any
              one move. Absent on documents published before the producer stated it. */}
          {view.transfer_hit_points != null ? (
            <p className={styles.muted}>
              {copy.weekTransferCost(points(view.transfer_hit_points, 1, locale))}
            </p>
          ) : null}
        </>
      )}
      <RivalPlayers advice={envelope} squad={squad} rivalSquad={rivalSquad} />
      <LineupSection view={view} />
      <WindowSection view={view} />
      <p className={styles.diagnostic}>{copy.diagnosticOnly}</p>
    </Card>
  );
}

function RivalPlayers({
  advice,
  squad,
  rivalSquad,
}: {
  advice: LeagueViewEnvelope<EntryAdvice>;
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
}) {
  const copy = useLanguage().messages.leagueMembers;
  if (advice.payload.rival_entry_id == null) return null;
  const comparison = comparedRivalPlayers(advice, squad, rivalSquad);
  return (
    <section className={styles.lineup} aria-label={copy.rivalPlayersTitle}>
      <h3 className={styles.lineupTitle}>{copy.rivalPlayersTitle}</h3>
      <p className={styles.honesty}>{copy.rivalPlayersBasis}</p>
      {comparison ? (
        <dl>
          {(["shared", "recommendedOnly", "rivalOnly"] as const).map((kind) => (
            <div key={kind}>
              <dt>{copy.rivalPlayerGroups[kind]}</dt>
              <dd>
                {comparison[kind].map((player) => player.name).join(", ") || copy.rivalPlayersNone}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className={styles.muted}>{copy.rivalPlayersUnavailable}</p>
      )}
    </section>
  );
}

/**
 * A three- or five-week window: what it assumes, in the producer's own sentences, and
 * one row per gameweek — transfers, hit points, chip, expected points. The moves and
 * the lineup above are the first week's; the rest of the window lives here. Rendered
 * only when the producer published it, so a one-week document shows nothing extra.
 */
function WindowSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const weeks = view.plan_weeks;
  if (!weeks || weeks.length === 0) return null;
  const limits = view.stated_limits ?? [];
  const names = (players: AdvicePlayer[]) =>
    players.length === 0 ? "—" : players.map((player) => player.name).join(", ");
  const title = copy.windowTitle(weeks.length);
  return (
    <section className={styles.window} aria-label={title}>
      <h3 className={styles.lineupTitle}>{title}</h3>
      <p className={styles.honesty}>{copy.windowRule}</p>
      {limits.length > 0 ? (
        <>
          <h4 className={styles.lineupSub}>{copy.windowLimitsLabel}</h4>
          <ul className={styles.limits}>
            {limits.map((sentence) => (
              <li key={sentence}>
                {Object.hasOwn(copy.statedLimits, sentence)
                  ? copy.statedLimits[sentence]
                  : copy.statedLimitUnknown}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <div className={styles.windowScroll}>
        <table className={styles.windowTable}>
          <thead>
            <tr>
              <th scope="col">{copy.windowWeek}</th>
              <th scope="col">{copy.in}</th>
              <th scope="col">{copy.out}</th>
              <th scope="col" className={styles.right}>
                {copy.windowHits}
              </th>
              <th scope="col">{copy.chipLabel}</th>
              <th scope="col" className={styles.right}>
                {copy.windowPoints}
              </th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week.gameweek}>
                <th scope="row" className="num">
                  {copy.windowWeekOf(week.gameweek)}
                </th>
                <td>{names(week.transfers_in)}</td>
                <td>{names(week.transfers_out)}</td>
                <td className={`${styles.right} num`}>
                  {points(week.transfer_hit_points, 0, locale)}
                </td>
                <td>{week.chip ? (copy.chipNames[week.chip] ?? week.chip) : "—"}</td>
                <td className={`${styles.right} num`}>{points(week.expected_points, 1, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * The rest of the decision: armband, chip, the eleven and the bench order. Rendered only
 * when the producer published them — a document from before the producer carried the
 * plan week, or a decision handed over without it, shows the moves alone.
 */
function LineupSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { captain, vice_captain: vice, starting_xi: eleven, bench } = view;
  if (!captain || !vice || !eleven || !bench) return null;
  const chipName = view.chip ? (copy.chipNames[view.chip] ?? view.chip) : null;
  const mark = (player: AdvicePlayer) =>
    player.player_id === captain.player_id ? "C" : player.player_id === vice.player_id ? "V" : null;
  return (
    <section className={styles.lineup} aria-label={copy.lineupTitle}>
      <h3 className={styles.lineupTitle}>{copy.lineupTitle}</h3>
      <p className={styles.honesty}>{copy.lineupRule}</p>
      {finiteNumber(view.expected_own_points) ? (
        <p className={styles.planCost}>
          <strong className="num">
            {copy.expectedOwnPoints(points(view.expected_own_points, 1, locale))}
          </strong>
        </p>
      ) : null}
      <dl className={styles.armband}>
        <div>
          <dt>{copy.captainLabel}</dt>
          <dd>
            <strong>{captain.name}</strong>{" "}
            <span className={styles.muted}>
              {captain.team} · {captain.position}
            </span>
          </dd>
        </div>
        <div>
          <dt>{copy.viceCaptainLabel}</dt>
          <dd>
            <strong>{vice.name}</strong>{" "}
            <span className={styles.muted}>
              {vice.team} · {vice.position}
            </span>
          </dd>
        </div>
        <div>
          <dt>{copy.chipLabel}</dt>
          <dd>{chipName ? <Badge tone="good">{chipName}</Badge> : copy.chipNone}</dd>
        </div>
      </dl>
      <h4 className={styles.lineupSub}>{copy.startingXiLabel}</h4>
      <div className={styles.bench}>
        {eleven.map((player, index) => (
          <LineupRow key={player.player_id} player={player} order={index + 1} mark={mark(player)} />
        ))}
      </div>
      <h4 className={styles.lineupSub}>{copy.benchOrderLabel}</h4>
      <div className={styles.bench}>
        {bench.map((player, index) => (
          <LineupRow key={player.player_id} player={player} order={index + 1} mark={null} />
        ))}
      </div>
    </section>
  );
}

function LineupRow({
  player,
  order,
  mark,
}: {
  player: AdvicePlayer;
  order: number;
  mark: "C" | "V" | null;
}) {
  const { locale } = useLanguage();
  return (
    <div className={styles.benchRow}>
      <span className="num">{order}</span>
      <strong>
        {player.name}
        {mark ? (
          <>
            {" "}
            <Badge tone={mark === "C" ? "good" : "neutral"}>{mark}</Badge>
          </>
        ) : null}
      </strong>
      <span className={styles.muted}>
        {player.team} · {player.position}
      </span>
      <span className={`${styles.benchPoints} num`}>
        {player.expected_points != null ? `${points(player.expected_points, 1, locale)} xP` : ""}
      </span>
    </div>
  );
}

type MemberCopy = ReturnType<typeof useLanguage>["messages"]["leagueMembers"];

/** The caption under a move, keyed on the reason the producer stated for it. */
function reasonFor(copy: MemberCopy, code: AdviceMove["reason_code"]): string {
  if (code === "window_value") return copy.windowValueReason;
  if (code === "points_gain") return copy.pointsGainReason;
  return copy.modeTradeoffReason;
}

function AdviceRow({ move }: { move: AdviceMove }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <article className={styles.move}>
      <div className={styles.movePlayers}>
        <span>
          {copy.out}: <strong>{move.player_out?.name ?? "—"}</strong>
        </span>
        <span>
          {copy.in}: <strong>{move.player_in?.name ?? "—"}</strong>
        </span>
      </div>
      <div className={styles.moveNumbers}>
        <span>{copy.projectedGain(points(move.expected_points_delta, 1, locale))}</span>
      </div>
      <p className={styles.muted}>{reasonFor(copy, move.reason_code)}</p>
    </article>
  );
}
