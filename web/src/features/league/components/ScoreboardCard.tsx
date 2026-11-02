import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { LeagueDataMissing } from "../data";
import { useLeagueScoreboard } from "../queries";
import type { LeagueViewEnvelope, Scoreboard, ScoreboardGameweek } from "../types";
import styles from "./ScoreboardCard.module.css";

/**
 * The scoreboard as the `/league` page shows it: read, or say why not. A missing file is
 * the normal state before the first weekly run that writes it, so it reads as "not
 * published yet" rather than as an error; anything else is an error.
 */
export function ScoreboardSection() {
  const { messages } = useLanguage();
  const copy = messages.leagueScoreboard;
  const query = useLeagueScoreboard();
  if (query.isPending) {
    return (
      <Card tone="muted" title={copy.title}>
        <p className={styles.notice}>{copy.loading}</p>
      </Card>
    );
  }
  if (query.isError) {
    return (
      <Card tone="muted" title={copy.title}>
        <p className={styles.notice}>
          {query.error instanceof LeagueDataMissing ? copy.notPublished : copy.notAvailable}
        </p>
      </Card>
    );
  }
  return <ScoreboardCard envelope={query.data} />;
}

export function ScoreboardCard({ envelope }: { envelope: LeagueViewEnvelope<Scoreboard> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueScoreboard;
  const view = envelope.payload;
  const finished = view.gameweeks.filter((week) => week.finished);
  const total = view.cumulative;
  return (
    <Card title={copy.title}>
      {finished.length === 0 ? (
        <p className={styles.notice}>{copy.noGameweek}</p>
      ) : (
        <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.caption}>
          <table className={styles.table}>
            <caption className="visually-hidden">{copy.caption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.gameweek}</th>
                <th scope="col" className={styles.right}>
                  {copy.members}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.top100}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.average}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.highest}
                </th>
              </tr>
            </thead>
            <tbody>
              {finished.map((week) => (
                <WeekRow key={week.gameweek} week={week} locale={locale} />
              ))}
            </tbody>
            {total.through_gameweek !== null && (
              <tfoot>
                <tr className={styles.total}>
                  <th scope="row">{copy.cumulative(total.through_gameweek)}</th>
                  <td className={`${styles.right} num`}>
                    {total.members_mean_total_points === null
                      ? "—"
                      : points(total.members_mean_total_points, 1, locale)}
                  </td>
                  <td className={`${styles.right} num`}>—</td>
                  <td className={`${styles.right} num`}>
                    {total.average_entry_score === null
                      ? "—"
                      : points(total.average_entry_score, 0, locale)}
                  </td>
                  <td className={`${styles.right} num`}>—</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </Card>
  );
}

function WeekRow({ week, locale }: { week: ScoreboardGameweek; locale: string }) {
  return (
    <tr>
      <th scope="row" className="num">
        {week.gameweek}
      </th>
      <td className={`${styles.right} num`}>
        {week.members_mean_net === null ? "—" : points(week.members_mean_net, 1, locale)}
      </td>
      <td className={`${styles.right} num`}>
        {week.top100 === null ? "—" : points(week.top100.mean_score, 1, locale)}
      </td>
      <td className={`${styles.right} num`}>
        {week.average_entry_score === null ? "—" : points(week.average_entry_score, 0, locale)}
      </td>
      <td className={`${styles.right} num`}>
        {week.highest_score === null ? "—" : points(week.highest_score, 0, locale)}
      </td>
    </tr>
  );
}
