import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { useLeagueIdentity } from "../identity/useLeagueIdentity";
import type { SuggestionHistory } from "./historyData";
import styles from "./PersonalSeasonReport.module.css";

const COPY = {
  tr: {
    title: "Sezon raporum",
    week: "Hafta",
    actual: "Kadro puanım",
    advice: "Önerilen kadro",
    hits: "Transfer kesintisi",
    captain: "Kaptan",
    transfers: "Transferlerim",
    none: "Transfer yok",
  },
  en: {
    title: "My season report",
    week: "Gameweek",
    actual: "My squad points",
    advice: "Suggested squad",
    hits: "Transfer hit",
    captain: "Captain",
    transfers: "My transfers",
    none: "No transfers",
  },
};

/** The visitor's report only. The identity is the site's existing member selection. */
export function PersonalSeasonReport({ history }: { history: SuggestionHistory }) {
  const { language, locale } = useLanguage();
  const { member } = useLeagueIdentity(history.payload.league_id);
  if (member?.entryId !== history.payload.entry_id) return null;
  const weeks = history.payload.weeks
    .filter((week) => week.status === "available" && week.actual && week.suggested)
    .sort((left, right) => right.gameweek - left.gameweek);
  if (!weeks.length) return null;
  const copy = COPY[language];
  return (
    <details className={styles.report}>
      <summary>{copy.title}</summary>
      <div className={styles.weeks}>
        {weeks.map((week) => {
          const actual = week.actual!;
          const detail = actual.details;
          return (
            <section
              key={week.gameweek}
              className={styles.week}
              aria-label={`${copy.week} ${week.gameweek}`}
            >
              <h2>
                {copy.week} {week.gameweek}
              </h2>
              <dl className={styles.totals}>
                <div>
                  <dt>{copy.actual}</dt>
                  <dd>{points(actual.net_points, 1, locale)}</dd>
                </div>
                <div>
                  <dt>{copy.advice}</dt>
                  <dd>{points(week.suggested!.net_points, 1, locale)}</dd>
                </div>
                <div>
                  <dt>{copy.hits}</dt>
                  <dd>{points(actual.transfer_hit_points, 1, locale)}</dd>
                </div>
              </dl>
              {detail ? (
                <>
                  <h3>{copy.captain}</h3>
                  <p className={styles.row}>
                    <strong>{detail.captain.name}</strong>
                    <span>{points(detail.captain.counted_points, 1, locale)}</span>
                  </p>
                  <h3>{copy.transfers}</h3>
                  {detail.transfers.length ? (
                    <ul className={styles.moves}>
                      {detail.transfers.map((move, index) => (
                        <li className={styles.row} key={`${index}-${move.player_in.player_id}`}>
                          <span>
                            {move.player_out} → <strong>{move.player_in.name}</strong>
                          </span>
                          <span>{points(move.player_in.counted_points, 1, locale)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>{copy.none}</p>
                  )}
                </>
              ) : null}
            </section>
          );
        })}
      </div>
    </details>
  );
}
