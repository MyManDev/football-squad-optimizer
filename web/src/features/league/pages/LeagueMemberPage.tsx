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
  publishedSelection,
  selectedAdviceRequest,
} from "../advice/adviceSelection";
import { checkedAdvice } from "../advice/adviceResponse";
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
export type AdviceIssue = "not-computed" | "unavailable";

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
  // tree from before the menu has none, and the page then offers the baseline only.
  const indexQuery = useQuery({
    queryKey: ["provisional-entry-advice-index", entryId],
    queryFn: () => loadEntryAdviceIndex(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
    retry: false,
  });
  const members = membersQuery.data?.payload.members ?? [];
  const index = indexQuery.data?.payload ?? null;
  const request = selectedAdviceRequest(
    publishedSelection(searchParams, index),
    squad.data?.payload.league_id ?? 0,
    entryId,
    members,
    undefined,
    index?.default_rival_entry_id ?? null,
  );
  const advice = useQuery({
    queryKey: [
      "provisional-entry-advice",
      entryId,
      request.strategy,
      request.window,
      request.rivalEntryId,
    ],
    queryFn: () =>
      loadEntryAdvice(entryId, request.strategy, request.window, request.rivalEntryId ?? null),
    enabled: validEntryId && !membersQuery.isPending && !indexQuery.isPending,
    staleTime: 60_000,
  });

  if (entryParam === "squadopt") return <SystemLeagueMemberPage />;
  if (!validEntryId) return <EmptyState title={copy.invalidEntry} />;
  if (squad.isPending || advice.isPending) return <EmptyState title={copy.loadingEntry} />;
  if (squad.isError) {
    return <EmptyState title={copy.entryNotAvailable}>{copy.entryNotAvailableBody}</EmptyState>;
  }
  // Published advice that is missing or unloadable does not close the page: the member
  // context is valid, so the squad and the compute control stay, and the advice card says
  // what is missing. Only this pair is solved per member, so an unpublished combination
  // is a normal outcome rather than a fault the reader should report.
  const adviceIssue: AdviceIssue | undefined = advice.isError
    ? advice.error instanceof LeagueDataMissing
      ? "not-computed"
      : "unavailable"
    : undefined;
  return (
    <LeagueMemberView
      squad={squad.data}
      advice={advice.isError ? null : advice.data}
      adviceIssue={adviceIssue}
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
  members?: EntryView[];
  index?: EntryAdviceIndex | null;
  client?: AdviceClient;
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
  members = [],
  index = null,
  client,
}: LeagueMemberViewProps) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
  const [searchParams] = useSearchParams();
  const { viewer } = useViewerEntry();
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const job = useAdviceJob(adviceClient);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  const request = selectedAdviceRequest(
    publishedSelection(searchParams, index),
    leagueId,
    entryId,
    members,
    { season: view.season, gameweek: view.gameweek },
    index?.default_rival_entry_id ?? null,
  );
  const requestKey = [
    request.leagueId,
    request.entryId,
    request.strategy,
    request.window,
    request.rivalEntryId ?? "",
  ].join(":");

  // A new selection starts clean: an earlier request's answer, wait or failure must not
  // read as this member's, strategy's, window's or rival's.
  const { reset } = job;
  useEffect(() => {
    reset();
  }, [requestKey, reset]);

  const current =
    job.state.phase !== "idle" && sameAdviceRequest(job.state.request, request) ? job.state : null;
  const computed = current?.phase === "done" ? current : null;
  const waiting = current?.phase === "waiting" ? current : null;
  let published: LeagueViewEnvelope<EntryAdvice> | null = null;
  if (advice) {
    try {
      published = checkedAdvice(advice, request);
    } catch {
      // A published file for another selection or week is not this request's answer.
      published = null;
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

      {view.data_quality !== "complete" ? (
        <Card tone="muted" title={copy.incompleteTitle}>
          <p className={styles.notice}>
            {copy.incompleteBody(view.missing_fields.join(", ") || copy.unknown)}
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

      {view.squadopt_comparison ? (
        <Card title={copy.squadoptComparisonTitle}>
          <p className={styles.notice}>{messages.league.note}</p>
          <p className={`${styles.comparison} num`}>
            {copy.squadoptComparison(
              signedPoints(view.squadopt_comparison.difference_points, 0, locale),
            )}
          </p>
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
          </Card>
          <Card title={copy.bench} aside={copy.benchCount(view.bench.length)}>
            <div className={styles.bench}>
              {view.bench.map((player) => (
                <div className={styles.benchRow} key={player.player_id}>
                  <span className="num">{player.bench_order}</span>
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
        <TemplatePicker />
        <MemberDecisionControls entryId={entryId} members={members} index={index} />
        <AdviceRequestPanel request={request} job={job} />
        {shown ? (
          <AdviceCard shown={shown} members={members} />
        ) : (
          <MissingAdviceCard
            issue={advice && !published ? "not-computed" : (adviceIssue ?? "not-computed")}
            canCompute={canComputeAdvice(request)}
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
function MissingAdviceCard({ issue, canCompute }: { issue: AdviceIssue; canCompute: boolean }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <Card title={copy.advice}>
      <p className={styles.honesty}>
        <strong>{issue === "not-computed" ? copy.adviceNotComputed : copy.adviceUnreadable}</strong>
      </p>
      <p className={styles.muted}>
        {issue === "not-computed" ? copy.adviceNotComputedBody : copy.adviceUnreadableBody}
      </p>
      {canCompute ? <p className={styles.muted}>{copy.adviceRequestHint}</p> : null}
    </Card>
  );
}

function AdviceCard({ shown, members = [] }: { shown: ShownAdvice; members?: EntryView[] }) {
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
  const showsPrice = view.mode !== "saf-puan" && price != null && price >= 0;
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
      {/* A bound that was not recorded is not a bound of zero. The producer emits null
          for exactly that state and refuses to read it as zero on its own side
          (`advice.py`'s `bound_slack`: "the proof did not finish" and "the proof finished
          at zero" are different facts); defaulting here would perform the conflation the
          backend forbids, and "gap ≤ 0.0 pts" is the strongest proof claim there is —
          printed inside the sentence that says the proof did not finish. */}
      {view.solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {view.optimality_gap != null
            ? copy.unprovenPlanBody(points(view.optimality_gap, 1, locale))
            : copy.unprovenPlanBodyNoGap}
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
          {view.control_optimality_gap != null
            ? copy.controlUnprovenBody(points(view.control_optimality_gap, 1, locale))
            : copy.controlUnprovenBodyNoGap}
        </p>
      ) : null}
      {view.overlap_count != null && view.expected_gap_vs_rival != null ? (
        <p className={styles.muted}>
          {copy.overlapLine(view.overlap_count)} ·{" "}
          {copy.gapLine(signedPoints(view.expected_gap_vs_rival, 1, locale))}
          {view.captain_agreement ? ` · ${copy.captainShared}` : ""}
        </p>
      ) : null}
      {view.plan_kind && view.transfer_cap != null && view.overlap_target != null ? (
        <p className={styles.muted}>
          {view.plan_kind === "within_free_transfers"
            ? copy.planWithinFree(view.transfer_cap, view.overlap_target, view.overlap_applied ?? 0)
            : copy.planWithHits(view.transfer_cap, view.overlap_target)}
          {alternative && alternativePrice != null && alternativePrice >= 0
            ? ` ${
                alternative.kind === "with_hits"
                  ? (unproven ? copy.alternativeWithHitsAtMost : copy.alternativeWithHits)(
                      alternative.overlap_applied,
                      points(alternative.transfer_hit_points ?? 0, 0, locale),
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
        <p className={styles.muted}>
          {view.data_quality === "complete" ? copy.noMove : copy.noAdviceMissingData}
        </p>
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
      <LineupSection view={view} />
      <WindowSection view={view} />
      <p className={styles.diagnostic}>{copy.diagnosticOnly}</p>
    </Card>
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
              // The producer's sentence in this language where the site knows it; the
              // producer's own words otherwise, never dropped.
              <li key={sentence}>{copy.statedLimits[sentence] ?? sentence}</li>
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
      {view.expected_own_points != null ? (
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
