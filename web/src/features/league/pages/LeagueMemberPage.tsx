import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { DecisionControls } from "../../moves/components/DecisionControls";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { createAdviceClient, type AdviceClient, type AdviceSource } from "../advice/adviceClient";
import { canComputeAdvice, selectedAdviceRequest } from "../advice/adviceSelection";
import { checkedAdvice } from "../advice/adviceResponse";
import { sameAdviceRequest, useAdviceJob } from "../advice/useAdviceJob";
import { TemplatePicker } from "../templates/TemplatePicker";
import { useDecisionSelection } from "../../moves/decisionSelection";
import { Pitch } from "../../squad/components/Pitch";
import { SquadPage } from "../../squad/pages/SquadPage";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { LeagueDataMissing, loadEntryAdvice, loadEntrySquad, loadLeagueMembers } from "../data";
import type {
  AdviceMove,
  AdvicePlayer,
  EntryAdvice,
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
  const { mode, windowSize } = useDecisionSelection();
  const validEntryId = Number.isSafeInteger(entryId) && entryId > 0;
  const squad = useQuery({
    queryKey: ["provisional-entry-squad", entryId],
    queryFn: () => loadEntrySquad(entryId),
    enabled: validEntryId,
    staleTime: 60_000,
  });
  const advice = useQuery({
    queryKey: ["provisional-entry-advice", entryId, mode, windowSize],
    queryFn: () => loadEntryAdvice(entryId, mode, windowSize),
    enabled: validEntryId,
    staleTime: 60_000,
  });
  const membersQuery = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
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
      members={membersQuery.data?.payload.members ?? []}
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
  client,
}: LeagueMemberViewProps) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
  const [searchParams] = useSearchParams();
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const job = useAdviceJob(adviceClient);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  const request = selectedAdviceRequest(searchParams, leagueId, entryId, members, {
    season: view.season,
    gameweek: view.gameweek,
  });
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
        <TemplatePicker />
        <DecisionControls variant="entry" />
        <AdviceRequestPanel request={request} job={job} />
        {shown ? (
          <AdviceCard shown={shown} />
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

function MissingAdviceCard({ issue, canCompute }: { issue: AdviceIssue; canCompute: boolean }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <Card title={copy.advice}>
      <p className={styles.honesty}>
        <strong>
          {issue === "not-computed" ? copy.adviceNotComputed : copy.entryNotAvailable}
        </strong>
      </p>
      <p className={styles.muted}>
        {issue === "not-computed" ? copy.adviceNotComputedBody : copy.entryNotAvailableBody}
      </p>
      {canCompute ? <p className={styles.muted}>{copy.adviceRequestHint}</p> : null}
    </Card>
  );
}

function AdviceCard({ shown }: { shown: ShownAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { envelope, origin } = shown;
  const view = envelope.payload;
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
          {copy.unprovenPlanBody(points(view.optimality_gap ?? 0, 1, locale))}
        </p>
      ) : null}
      {view.mode !== "saf-puan" && view.expected_points_cost != null ? (
        <p className={styles.planCost}>
          <strong className="num">
            {copy.planCost(points(view.expected_points_cost, 1, locale))}
          </strong>
          {view.rival_label ? <span> · {copy.planRival(view.rival_label)}</span> : null}
        </p>
      ) : null}
      {view.moves.length === 0 ? (
        <p className={styles.muted}>
          {view.data_quality === "complete" ? copy.noMove : copy.noAdviceMissingData}
        </p>
      ) : (
        <div className={styles.moves}>
          {view.moves.map((move) => (
            <AdviceRow key={move.move_id} move={move} />
          ))}
        </div>
      )}
      <LineupSection view={view} />
      <p className={styles.diagnostic}>{copy.diagnosticOnly}</p>
    </Card>
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
        <strong>{copy.expectedPointCost(points(move.expected_points_cost, 1, locale))}</strong>
      </div>
      <p className={styles.muted}>
        {move.reason_code === "window_value" ? copy.windowValueReason : copy.modeTradeoffReason}
      </p>
    </article>
  );
}
