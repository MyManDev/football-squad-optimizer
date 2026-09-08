import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { LeagueDataMissing, loadScoreboard } from "../data";
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
  const query = useQuery({
    queryKey: ["provisional-league-scoreboard"],
    queryFn: loadScoreboard,
    staleTime: 60_000,
    retry: false,
  });
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
  // A gross Top-100 mean sits in a net table; the card says so rather than letting the
  // column read as one more net figure.
  const anyGross = finished.some((week) => week.top100?.basis === "gross");
  const anyProvisional = finished.some((week) => !week.data_checked);
  const oursCovers =
    total.ours_net === null
      ? copy.oursNone
      : total.ours_gameweeks.length === total.gameweeks.length
        ? null
        : copy.oursCovers(total.ours_gameweeks.join(", "));
  // The members' figure is a running total, so it spans every week played up to the last
  // finished one. That is the same set as the rest of the row until the finished weeks
  // run with a gap; when it is not, the cell says which weeks it covers rather than
  // sitting beside two narrower figures unmarked.
  const membersGameweeks = total.members_gameweeks ?? [];
  const membersCovers =
    total.members_mean_total_points === null ||
    membersGameweeks.join(",") === total.gameweeks.join(",")
      ? null
      : copy.membersCovers(membersGameweeks.join(", "));
  return (
    <Card title={copy.title} aside={copy.aside(view.source_snapshot_id)}>
      <p className={styles.notice}>{copy.paperLedger}</p>
      {finished.length === 0 ? (
        <p className={styles.notice}>{copy.noGameweek}</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className="visually-hidden">{copy.caption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.gameweek}</th>
                <th scope="col" className={styles.right}>
                  {copy.ours}
                </th>
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
                    {total.ours_net === null ? "—" : points(total.ours_net, 0, locale)}
                    {oursCovers && <div className={styles.sub}>{oursCovers}</div>}
                  </td>
                  <td className={`${styles.right} num`}>
                    {total.members_mean_total_points === null
                      ? "—"
                      : points(total.members_mean_total_points, 1, locale)}
                    <div className={styles.sub}>
                      {copy.membersTotal(total.members_counted)}
                      {membersCovers && ` · ${membersCovers}`}
                    </div>
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
      {anyGross && <p className={styles.notice}>{copy.grossNote}</p>}
      {anyProvisional && <p className={styles.notice}>{copy.provisionalNote}</p>}
      <p className={styles.notice}>{copy.modeNote}</p>
    </Card>
  );
}

function WeekRow({ week, locale }: { week: ScoreboardGameweek; locale: string }) {
  const { messages } = useLanguage();
  const copy = messages.leagueScoreboard;
  const ours = week.ours;
  const top100 = week.top100;
  return (
    <tr>
      <th scope="row" className="num">
        {week.gameweek}
        {/* Finished is not checked: bonus lands fixture by fixture, so the row can move. */}
        {!week.data_checked && <div className={styles.sub}>{copy.provisional}</div>}
      </th>
      <td className={`${styles.right} num`}>
        {ours === null ? (
          "—"
        ) : (
          <>
            {ours.net === null ? "—" : points(ours.net, 0, locale)}
            {ours.mode !== null && (
              <>
                {" "}
                <Badge tone={ours.mode === "live" ? "good" : "warn"}>{ours.mode}</Badge>
              </>
            )}
            {ours.net === null && <div className={styles.sub}>{copy.notSettled}</div>}
          </>
        )}
      </td>
      <td className={`${styles.right} num`}>
        {week.members_mean_net === null ? "—" : points(week.members_mean_net, 1, locale)}
        <div className={styles.sub}>{copy.membersCounted(week.members_counted)}</div>
      </td>
      <td className={`${styles.right} num ${top100?.basis === "gross" ? styles.gross : ""}`.trim()}>
        {top100 === null ? (
          "—"
        ) : (
          <>
            {points(top100.mean_score, 1, locale)}
            <div className={styles.sub}>
              {top100.basis === "net" ? copy.top100Net : copy.top100Gross}
              {!top100.final && ` · ${copy.top100NotFinal}`}
            </div>
          </>
        )}
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
