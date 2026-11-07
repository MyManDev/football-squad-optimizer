import { Link, useParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { memberAddress } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../dataErrors";
import type { SuggestionHistory, WeekReview } from "../history/historyData";
import { summarizeHistory } from "../history/historySummary";
import { useSuggestionHistory } from "../queries";
import { useLeague, useLeagueId } from "../useLeague";
import styles from "./LeagueMemberVsPage.module.css";

/**
 * VS SQUADOPT: the member against the system's suggestion, gameweek by gameweek. Each
 * settled week the member's history holds a suggestion and a result for is one row: the
 * captain and transfers the system suggested beside the captain and transfers the member
 * made, each side's net points, and the difference. The season's totals stand above.
 */
export function LeagueMemberVsPage() {
  const { messages } = useLanguage();
  const { league } = useLeague();
  const copy = messages.suggestionHistory;
  const parameter = useParams().entryId ?? "";
  const entryId = Number(parameter);
  const valid = /^[1-9]\d*$/.test(parameter) && Number.isSafeInteger(entryId);
  const query = useSuggestionHistory(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (query.isPending) return <EmptyState title={messages.common.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState page title={missing ? copy.empty : copy.unreadable}>
        {missing ? (
          <p>{copy.emptyBody}</p>
        ) : (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retry}
          </button>
        )}
        <p>
          <Link to={memberAddress(league.leagueId, entryId)}>{copy.back}</Link>
        </p>
      </EmptyState>
    );
  }
  return <LeagueMemberVsView key={entryId} history={query.data} />;
}

/** A week both sides scored: the only kind the comparison can draw. */
function comparable(week: WeekReview): boolean {
  return (
    week.status === "available" &&
    week.suggested !== null &&
    week.actual !== null &&
    week.net_difference !== null
  );
}

/** The captain the recorded squad names, where it names one. */
function suggestedCaptain(week: WeekReview): string | null {
  return week.players.find((player) => player.captain)?.name ?? null;
}

/** The plain one-week plan's moves, out and in, where the week recorded that plan. */
function suggestedMoves(week: WeekReview): { out: string; in: string }[] {
  const plan = week.recorded_plans?.find(
    (row) =>
      row.strategy === "saf-puan" &&
      row.rival_entry_id === null &&
      row.top100_weight === undefined &&
      row.managers_word === undefined &&
      row.chip === null,
  );
  return (plan?.moves ?? [])
    .filter((move) => move.player_out !== null && move.player_in !== null)
    .map((move) => ({ out: move.player_out!, in: move.player_in! }));
}

export function LeagueMemberVsView({ history }: { history: SuggestionHistory }) {
  const { messages, locale } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.vsSquadopt;
  const { entry_id: entryId, weeks } = history.payload;
  const compared = weeks.filter(comparable).sort((a, b) => b.gameweek - a.gameweek);
  const summary = summarizeHistory(compared);
  const net = (value: number | null) => (value === null ? "—" : points(value, 1, locale));
  const signed = (value: number | null) => (value === null ? "—" : signedPoints(value, 1, locale));
  return (
    <div className={styles.page}>
      <header>
        <Link to={memberAddress(leagueId, entryId)}>{messages.suggestionHistory.back}</Link>
        <h1>{copy.title}</h1>
      </header>
      {compared.length === 0 ? (
        <EmptyState title={messages.suggestionHistory.empty}>
          <p>{messages.suggestionHistory.emptyBody}</p>
        </EmptyState>
      ) : (
        <>
          <Card title={copy.total}>
            <dl className={styles.totals} data-testid="vs-totals">
              <div>
                <dt>{copy.squadopt}</dt>
                <dd>{net(summary.suggested)}</dd>
              </div>
              <div>
                <dt>{copy.you}</dt>
                <dd>{net(summary.actual)}</dd>
              </div>
              <div>
                <dt>{copy.difference}</dt>
                <dd>{signed(summary.difference)}</dd>
              </div>
            </dl>
          </Card>
          {compared.map((week) => {
            const actual = week.actual!;
            const detail = actual.details ?? null;
            const moves = suggestedMoves(week);
            return (
              <section
                key={week.gameweek}
                className={styles.week}
                aria-labelledby={`vs-week-${week.gameweek}`}
                data-testid="vs-week"
              >
                <h2 id={`vs-week-${week.gameweek}`}>
                  {messages.suggestionHistory.gameweek(week.gameweek)}
                </h2>
                <div className={styles.sides}>
                  <div className={styles.side}>
                    <h3>{copy.squadopt}</h3>
                    <dl>
                      <dt>{copy.captain}</dt>
                      <dd>{suggestedCaptain(week) ?? "—"}</dd>
                      <dt>{copy.transfers}</dt>
                      <dd>
                        {moves.length === 0 ? (
                          copy.none
                        ) : (
                          <ul className={styles.moves}>
                            {moves.map((move, index) => (
                              <li key={index}>
                                {move.out} → <strong>{move.in}</strong>
                              </li>
                            ))}
                          </ul>
                        )}
                      </dd>
                      <dt>{copy.net}</dt>
                      <dd className={styles.net}>{net(week.suggested!.net_points)}</dd>
                    </dl>
                  </div>
                  <div className={styles.side}>
                    <h3>{copy.you}</h3>
                    <dl>
                      <dt>{copy.captain}</dt>
                      <dd>{detail?.captain.name ?? "—"}</dd>
                      <dt>{copy.transfers}</dt>
                      <dd>
                        {detail === null || detail.transfers.length === 0 ? (
                          copy.none
                        ) : (
                          <ul className={styles.moves}>
                            {detail.transfers.map((move, index) => (
                              <li key={index}>
                                {move.player_out} → <strong>{move.player_in.name}</strong>
                              </li>
                            ))}
                          </ul>
                        )}
                      </dd>
                      <dt>{copy.net}</dt>
                      <dd className={styles.net}>{net(actual.net_points)}</dd>
                    </dl>
                  </div>
                </div>
                <p className={styles.difference}>
                  {copy.difference}: <strong>{signed(week.net_difference)}</strong>
                </p>
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
