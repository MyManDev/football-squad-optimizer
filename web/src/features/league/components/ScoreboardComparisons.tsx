import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import type { ScoreboardGameweek } from "../types";
import styles from "./ScoreboardCard.module.css";

export function ScoreboardComparisons({ weeks }: { weeks: ScoreboardGameweek[] }) {
  const { messages, locale } = useLanguage();
  const copy = messages.scoreboardComparisons;
  if (!weeks.some((week) => Array.isArray(week.comparisons) && week.comparisons.length))
    return null;
  const number = (value: number | null | undefined, signed = false) =>
    value == null || !Number.isFinite(value)
      ? "—"
      : signed
        ? signedPoints(value, 1, locale)
        : points(value, 1, locale);
  // One landmark for the table: the scrolling region below carries the name, so the block
  // around it is a plain group under its heading rather than a second region of that name.
  return (
    <div>
      <h3>{copy.title}</h3>
      <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.title}>
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
                          {row.scoring_basis === "source_average"
                            ? copy.game
                            : row.scoring_basis === "named_eleven_no_autosubs"
                              ? copy.legacy
                              : row.scoring_basis === "official_autosub_captain_v2"
                                ? copy.official
                                : row.scoring_basis === "net"
                                  ? copy.memberNet
                                  : copy.basisUnknown}
                        </div>
                      )}
                      <div className={styles.sub}>
                        {row.kind === "league_mean"
                          ? copy.memberPopulation(week.members_counted)
                          : row.kind === "game_mean"
                            ? copy.gamePopulation
                            : row.kind === "elite_xi" || row.kind === "ownership_template"
                              ? copy.synthetic
                              : copy.paperPopulation}
                      </div>
                    </th>
                    <td>{number(settled ? row.net : null)}</td>
                    <td>
                      {errors?.zero_minute_starters != null &&
                      Number.isInteger(errors.zero_minute_starters)
                        ? points(errors.zero_minute_starters, 0, locale)
                        : "—"}
                    </td>
                    <td>{number(errors?.minutes_shortfall, true)}</td>
                    <td>{number(errors?.captain_shortfall, true)}</td>
                    <td>{number(errors?.autosub_recovery)}</td>
                  </tr>
                );
              }),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
