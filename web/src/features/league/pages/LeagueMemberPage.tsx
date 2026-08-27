import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { DecisionControls } from "../../moves/components/DecisionControls";
import { AdviceRequestPanel } from "../advice/AdviceRequestPanel";
import { TemplatePicker } from "../templates/TemplatePicker";
import { useDecisionSelection } from "../../moves/decisionSelection";
import { Pitch } from "../../squad/components/Pitch";
import { SquadPage } from "../../squad/pages/SquadPage";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { LeagueDataMissing, loadEntryAdvice, loadEntrySquad, loadLeagueMembers } from "../data";
import type { AdviceMove, EntryAdvice, EntrySquad, EntryView, LeagueViewEnvelope } from "../types";
import styles from "./LeagueMemberPage.module.css";

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
  if (advice.isError) {
    // Only this pair is solved per member; asking for another is a normal outcome, and
    // saying "not available" for it would read as a fault the reader should report.
    const uncomputed = advice.error instanceof LeagueDataMissing;
    return (
      <EmptyState title={uncomputed ? copy.adviceNotComputed : copy.entryNotAvailable}>
        {uncomputed ? copy.adviceNotComputedBody : copy.entryNotAvailableBody}
      </EmptyState>
    );
  }
  return (
    <LeagueMemberView
      squad={squad.data}
      advice={advice.data}
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

export function LeagueMemberView({
  squad,
  advice,
  members = [],
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  advice: LeagueViewEnvelope<EntryAdvice>;
  members?: EntryView[];
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
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
        <AdviceRequestPanel
          leagueId={advice.payload.league_id}
          entryId={view.entry.entry_id ?? 0}
          members={members}
        />
        <AdviceCard envelope={advice} />
      </section>
    </div>
  );
}

function AdviceCard({ envelope }: { envelope: LeagueViewEnvelope<EntryAdvice> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = envelope.payload;
  return (
    <Card title={copy.advice} aside={<ExampleDataBadge sourceKind={envelope.source_kind} />}>
      <p className={styles.honesty}>{copy.honestyRule}</p>
      <p className={styles.honesty}>{copy.independentAdviceRule}</p>
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
      <p className={styles.diagnostic}>{copy.diagnosticOnly}</p>
    </Card>
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
