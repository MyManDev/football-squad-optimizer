import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { ScoreboardGameweek } from "../types";
import styles from "./ScoreboardCard.module.css";

export function ScoreboardComparisons({ weeks }: { weeks: ScoreboardGameweek[] }) {
  const { messages, locale } = useLanguage();
  const copy = messages.scoreboardComparisons;
  if (!weeks.some((week) => Array.isArray(week.comparisons) && week.comparisons.length))
    return null;
  const number = (value: number | null | undefined) =>
    value == null || !Number.isFinite(value) ? "-" : points(value, 1, locale);
  return (
    <section aria-label={copy.title}>
      <h3>{copy.title}</h3>
      <p className={styles.notice}>{copy.missing}</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className="visually-hidden">{copy.title}</caption>
          <thead>
            <tr>
              {[
                copy.week,
                copy.name,
                copy.net,
                copy.zero,
                copy.minutes,
                copy.captain,
                copy.autosub,
              ].map((label) => (
                <th key={label} scope="col">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.flatMap((week) =>
              (Array.isArray(week.comparisons) ? week.comparisons : []).map((row) => {
                const settled = week.finished === true && week.data_checked === true;
                const errors = settled ? row.diagnostics : undefined;
                return (
                  <tr key={`${week.gameweek}-${row.kind}`}>
                    <td>{week.gameweek}</td>
                    <th scope="row">
                      {copy.names[row.kind]}
                      {!settled && <div className={styles.sub}>{copy.pending}</div>}
                      {settled && row.net == null && week.ours == null && row.kind === "system" && (
                        <div className={styles.sub}>{copy.absent}</div>
                      )}
                      {settled && row.net !== null && (
                        <div className={styles.sub}>
                          {row.kind === "game_mean"
                            ? copy.game
                            : row.kind === "elite_xi" || row.kind === "ownership_template"
                              ? copy.synthetic
                              : row.scoring_basis === "named_eleven_no_autosubs"
                                ? copy.legacy
                                : row.scoring_basis === "official_autosub_captain_v2"
                                  ? copy.official
                                  : null}
                        </div>
                      )}
                    </th>
                    <td>{number(settled ? row.net : null)}</td>
                    <td>
                      {errors?.zero_minute_starters != null &&
                      Number.isInteger(errors.zero_minute_starters)
                        ? points(errors.zero_minute_starters, 0, locale)
                        : "-"}
                    </td>
                    <td>{number(errors?.minutes_shortfall)}</td>
                    <td>{number(errors?.captain_shortfall)}</td>
                    <td>{number(errors?.autosub_recovery)}</td>
                  </tr>
                );
              }),
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
