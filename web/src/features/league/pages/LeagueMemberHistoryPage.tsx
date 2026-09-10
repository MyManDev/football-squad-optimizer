import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints, utcShort } from "../../../lib/format";
import { LeagueDataMissing } from "../dataErrors";
import {
  loadSuggestionHistory,
  type SuggestionHistory,
  type WeekReview,
} from "../history/historyData";
import styles from "./LeagueMemberHistoryPage.module.css";

export function LeagueMemberHistoryPage() {
  const { messages } = useLanguage();
  const copy = messages.suggestionHistory;
  const parameter = useParams().entryId ?? "";
  const entryId = Number(parameter);
  const valid = /^[1-9]\d*$/.test(parameter) && Number.isSafeInteger(entryId);
  const query = useQuery({
    queryKey: ["suggestion-history", entryId],
    queryFn: ({ signal }) => loadSuggestionHistory(entryId, { signal }),
    enabled: valid,
  });
  if (!valid) return <EmptyState title={messages.leagueMembers.invalidEntry} />;
  if (query.isPending) return <EmptyState title={messages.common.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState title={missing ? copy.empty : copy.unreadable}>
        {missing ? (
          <p>{copy.emptyBody}</p>
        ) : (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retry}
          </button>
        )}
        <p>
          <Link to={`/league/members/${entryId}`}>{copy.back}</Link>
        </p>
      </EmptyState>
    );
  }
  return <LeagueMemberHistoryView key={entryId} history={query.data} />;
}

export function LeagueMemberHistoryView({ history }: { history: SuggestionHistory }) {
  const { messages, locale } = useLanguage();
  const copy = messages.suggestionHistory;
  const { entry_id: entryId, weeks, season } = history.payload;
  const [selected, setSelected] = useState<number | null>(null);
  const ordered = [...weeks].sort((a, b) => b.gameweek - a.gameweek);
  const week = ordered.find((item) => item.gameweek === selected) ?? ordered[0];
  return (
    <div className={styles.page}>
      <header>
        <Link to={`/league/members/${entryId}`}>{copy.back}</Link>
        <p className={styles.muted}>
          {season} · #{entryId}
        </p>
        <h1>{copy.title}</h1>
        <p>{copy.scope}</p>
        <p className={styles.muted}>
          {copy.outcomeAsOf}: {utcShort(history.generated_at_utc, locale)}
        </p>
      </header>
      {!week ? (
        <EmptyState title={copy.empty}>
          <p>{copy.emptyBody}</p>
        </EmptyState>
      ) : (
        <>
          <label className={styles.selector}>
            {copy.week}
            <select
              value={week.gameweek}
              onChange={(event) => setSelected(Number(event.target.value))}
            >
              {ordered.map((item) => (
                <option key={item.gameweek} value={item.gameweek}>
                  {messages.common.gameweek(item.gameweek)}
                </option>
              ))}
            </select>
          </label>
          <WeekResult week={week} />
        </>
      )}
      <Card tone="muted">
        <p className={styles.muted}>{copy.method}</p>
      </Card>
    </div>
  );
}

function WeekResult({ week }: { week: WeekReview }) {
  const { messages, locale } = useLanguage();
  const copy = messages.suggestionHistory;
  const format = (value: number | null | undefined) =>
    value == null ? "—" : points(value, 1, locale);
  const { suggested, actual } = week;
  const reason =
    week.reason === "no_pre_deadline_record" || week.reason === "missing_advice"
      ? copy.noEligible
      : week.reason === "missing_outcomes"
        ? copy.missingOutcomes
        : copy.invalid;
  const chip =
    suggested?.chip === "3xc" ? copy.triple : suggested?.chip ? copy[suggested.chip] : copy.noChip;
  return (
    <>
      <Card title={messages.common.gameweek(week.gameweek)}>
        {week.status !== "available" || !suggested ? (
          <EmptyState title={week.status === "unsettled" ? copy.unsettled : copy.unavailable}>
            <p>{week.status === "unsettled" ? copy.pending : reason}</p>
          </EmptyState>
        ) : (
          <>
            <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.title}>
              <table className={styles.scores}>
                <thead>
                  <tr>
                    <th scope="col">{messages.common.gameweek(week.gameweek)}</th>
                    <th scope="col">{copy.suggested}</th>
                    <th scope="col">{copy.actual}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">{copy.gross}</th>
                    <td>{format(suggested.gross_points)}</td>
                    <td>{format(actual?.gross_points)}</td>
                  </tr>
                  <tr>
                    <th scope="row">{copy.hits}</th>
                    <td>{format(suggested.transfer_hit_points)}</td>
                    <td>{format(actual?.transfer_hit_points)}</td>
                  </tr>
                  <tr>
                    <th scope="row">{copy.net}</th>
                    <td>
                      <strong>{format(suggested.net_points)}</strong>
                    </td>
                    <td>
                      <strong>{format(actual?.net_points)}</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className={styles.difference}>
              {copy.difference}:{" "}
              <strong>
                {week.net_difference === null ? "—" : signedPoints(week.net_difference, 1, locale)}
              </strong>
            </p>
            {!actual && <p role="status">{copy.actualMissing}</p>}
            <dl className={styles.facts}>
              <div>
                <dt>{copy.expectation}</dt>
                <dd>{format(week.expected_own_points)}</dd>
              </div>
              <div>
                <dt>{copy.captainBonus}</dt>
                <dd>{format(suggested.captain_bonus_points)}</dd>
              </div>
              <div>
                <dt>{copy.autosubs}</dt>
                <dd>{format(suggested.autosub_points)}</dd>
              </div>
              <div>
                <dt>{copy.chip}</dt>
                <dd>{chip}</dd>
              </div>
            </dl>
            <p className={styles.muted}>{copy.expectationNote}</p>
          </>
        )}
      </Card>
      {week.status === "available" && (
        <Card title={copy.players}>
          <p className={styles.muted}>{copy.playerNote}</p>
          <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.players}>
            <table className={styles.players}>
              <thead>
                <tr>
                  {[
                    copy.player,
                    copy.role,
                    copy.forecast,
                    copy.realized,
                    copy.error,
                    copy.minutes,
                    copy.multiplier,
                    copy.counted,
                  ].map((label) => (
                    <th scope="col" key={label}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {week.players.map((player) => (
                  <tr key={player.player_id}>
                    <th scope="row">
                      {player.name}
                      <span className={styles.position}>{player.position}</span>
                    </th>
                    <td>
                      {player.role === "starter" ? copy.starter : copy.bench}
                      {player.captain
                        ? ` · ${copy.captain}`
                        : player.vice_captain
                          ? ` · ${copy.vice}`
                          : ""}
                    </td>
                    <td>{format(player.expected_points)}</td>
                    <td>{format(player.realized_points)}</td>
                    <td>
                      {player.forecast_error === null
                        ? "—"
                        : signedPoints(player.forecast_error, 1, locale)}
                    </td>
                    <td>{player.minutes}</td>
                    <td>×{player.multiplier}</td>
                    <td>{format(player.counted_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <details className={styles.evidence}>
        <summary>{copy.evidence}</summary>
        <dl className={styles.facts}>
          {(
            [
              [copy.published, week.advice_generated_at_utc],
              [copy.deadline, week.deadline_utc],
              [copy.captured, week.advice_captured_at_utc],
              [copy.settledAt, week.outcome_captured_at_utc],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value ? utcShort(value, locale) : "—"}</dd>
            </div>
          ))}
          {(
            [
              [copy.adviceId, week.advice_snapshot_id],
              [copy.outcomeId, week.outcome_snapshot_id],
              [copy.digest, week.advice_sha256],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                <code>{value ?? "—"}</code>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
