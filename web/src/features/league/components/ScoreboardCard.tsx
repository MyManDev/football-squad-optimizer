import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { LeagueDataMissing, loadScoreboard } from "../data";
import type { LeagueViewEnvelope, Scoreboard, ScoreboardGameweek } from "../types";
import styles from "./ScoreboardCard.module.css";
import { ScoreboardComparisons } from "./ScoreboardComparisons";
import { LiveSeriesSection } from "./LiveSeriesCard";

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
  return (
    <>
      <ScoreboardCard envelope={query.data} />
      <LiveSeriesSection view={query.data.payload} />
    </>
  );
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
  // A null total has two different causes and they must not read alike. No week has
  // settled at all, or weeks have settled but were scored under another rule and are not
  // summed with this one. Saying "no settled week" in the second case would contradict the
  // settled row sitting in the table above it.
  const oursExcluded = total.ours_excluded_gameweeks ?? [];
  const oursCovers =
    total.ours_net === null
      ? oursExcluded.length > 0
        ? copy.oursOtherBasis(oursExcluded.map((week) => `${week.gameweek}`).join(", "))
        : copy.oursNone
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
        <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.caption}>
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
                {[
                  messages.scoreboardComparisons.zero,
                  messages.scoreboardComparisons.minutes,
                  messages.scoreboardComparisons.captain,
                  messages.scoreboardComparisons.autosub,
                ].map((label) => (
                  <th key={label} scope="col">
                    {label}
                  </th>
                ))}
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
                  <td>—</td>
                  <td>—</td>
                  <td>—</td>
                  <td>—</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
      <p className={styles.notice}>{messages.scoreboardComparisons.missing}</p>
      {anyGross && <p className={styles.notice}>{copy.grossNote}</p>}
      <ScoreboardComparisons weeks={view.gameweeks} />
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
  const errors =
    week.finished && week.data_checked && ours?.net != null ? ours.diagnostics : undefined;
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
            <div className={styles.sub}>
              {ours.scoring_basis === "named_eleven_no_autosubs"
                ? messages.scoreboardComparisons.legacy
                : ours.scoring_basis === "official_autosub_captain_v2"
                  ? messages.scoreboardComparisons.official
                  : messages.scoreboardComparisons.basisUnknown}
            </div>
            <div className={styles.sub}>{messages.scoreboardComparisons.paperPopulation}</div>
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
      {[
        errors?.zero_minute_starters,
        errors?.minutes_shortfall,
        errors?.captain_shortfall,
        errors?.autosub_recovery,
      ].map((value, index) => (
        <td key={index} className={`${styles.right} num`}>
          {value != null && Number.isFinite(value)
            ? index === 1 || index === 2
              ? signedPoints(value, 1, locale)
              : points(value, index === 0 ? 0 : 1, locale)
            : "—"}
        </td>
      ))}
    </tr>
  );
}
