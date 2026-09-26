import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { loadLiveSeries, type LiveSeries } from "../history/liveSeries";
import { LEAGUE_READ } from "../queries";
import type { Scoreboard } from "../types";
import styles from "./ScoreboardCard.module.css";

export function LiveSeriesSection({ view }: { view: Scoreboard }) {
  const { messages } = useLanguage();
  const query = useQuery({
    queryKey: ["live-member-series", view.season, view.source_snapshot_id],
    queryFn: ({ signal }) => loadLiveSeries(view, signal),
    ...LEAGUE_READ,
  });
  if (!query.data)
    return (
      <Card title={messages.liveSeries.title}>
        <p>{query.isPending ? messages.liveSeries.loading : messages.liveSeries.unavailable}</p>
      </Card>
    );
  return <LiveSeriesCard {...query.data} />;
}

export function LiveSeriesCard({
  series,
  remaining,
  unavailableMembers,
}: {
  series: LiveSeries;
  remaining: number | null;
  unavailableMembers: number;
}) {
  const { messages, locale } = useLanguage();
  const copy = messages.liveSeries;
  return (
    <Card title={copy.title}>
      <p>{copy.accumulated(series.memberWeeks, series.weekClusters)}</p>
      <p>
        {remaining === null
          ? copy.unknown
          : remaining > 0
            ? copy.remaining(remaining)
            : copy.reached}
      </p>
      <p className={styles.notice}>{copy.limits}</p>
      {unavailableMembers > 0 && <p>{copy.missing(unavailableMembers)}</p>}
      {series.meanDifference !== null && (
        <p>{copy.mean(signedPoints(series.meanDifference, 1, locale))}</p>
      )}
      {series.rows.length > 0 && (
        <>
          <div
            className={styles.tableWrap}
            tabIndex={0}
            role="region"
            aria-label={copy.weekSummary}
          >
            <table className={`${styles.table} ${styles.summaryTable}`}>
              <caption>{copy.weekSummary}</caption>
              <thead>
                <tr>
                  <th scope="col">{copy.week}</th>
                  <th scope="col">{copy.members}</th>
                  <th scope="col">{copy.difference}</th>
                </tr>
              </thead>
              <tbody>
                {series.weeks.map((week) => (
                  <tr key={week.gameweek}>
                    <th scope="row">{week.gameweek}</th>
                    <td>{week.members}</td>
                    <td>{signedPoints(week.meanDifference, 1, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.population}>
            <table className={styles.table}>
              <caption>
                {copy.population} · {messages.scoreboardComparisons.official} · {copy.net}
              </caption>
              <thead>
                <tr>
                  {[
                    copy.week,
                    copy.member,
                    copy.basis,
                    copy.suggested,
                    copy.actual,
                    copy.difference,
                  ].map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {series.rows.map((row) => (
                  <tr key={row.recordKey}>
                    <td>{row.gameweek}</td>
                    <th scope="row">
                      <Link to={`/league/members/${row.entryId}/history`}>{row.entryId}</Link>
                    </th>
                    <td>
                      {messages.scoreboardComparisons.official}
                      <div className={styles.sub}>
                        {copy.population} · {copy.net}
                      </div>
                    </td>
                    <td>{points(row.suggested, 1, locale)}</td>
                    <td>{points(row.actual, 1, locale)}</td>
                    <td>{signedPoints(row.difference, 1, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
