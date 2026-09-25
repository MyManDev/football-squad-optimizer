import type { CSSProperties } from "react";

import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { karneWeeks, type KarneWeek, type ScoreboardState } from "./karne";
import { DisclosureIcon } from "./memberIcons";
import { ScoreboardCard } from "./ScoreboardCard";
import styles from "./SystemKarne.module.css";

type Series = "ours" | "league" | "game";

/**
 * "Sistemin karnesi": SquadOpt's own paper squad week by week beside the league mean and
 * the FPL average, as horizontal bars on one scale for the whole chart (3 px a point where
 * the column allows), so a longer bar is always more points. Its good weeks and bad weeks are both
 * shown. A replay week is marked and the basis of the system's net is stated under the
 * chart; everything else the scoreboard says (provisional weeks, Top 100, the error
 * breakdown) is one click away in the closed full scoreboard
 * (SystemScoreboardDetails), which the page lays out at full width.
 */
export function SystemKarne({ state, leagueId }: { state: ScoreboardState; leagueId: number }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const board = messages.leagueScoreboard;
  // Another league's scoreboard is not this table's record.
  if (state.status === "ready" && state.envelope.payload.league_id !== leagueId) return null;
  const weeks = state.status === "ready" ? karneWeeks(state.envelope.payload) : [];
  // One scale for the whole chart: the longest bar is the largest figure in it.
  const max = Math.max(
    1,
    ...weeks
      .flatMap((week) => [week.ours, week.league, week.game])
      .filter((value): value is number => value !== null),
  );
  const format = (series: Series, value: number) =>
    points(value, series === "league" || !Number.isInteger(value) ? 1 : 0, locale);
  const names: Record<Series, string> = {
    ours: copy.karneOurs,
    league: copy.karneLeague,
    game: copy.karneGame,
  };
  const describe = (week: KarneWeek) =>
    `${copy.weekLabel(week.gameweek)}${week.replay ? ` (${copy.karneReplay})` : ""}: ${(
      ["ours", "league", "game"] as const
    )
      .map((series) => {
        const value = week[series];
        return `${names[series]} ${value === null ? copy.karneNone : format(series, value)}`;
      })
      .join(", ")}`;
  return (
    <section className={styles.karne} aria-labelledby="karne-title" data-mark="karne">
      <h2 className={styles.title} id="karne-title">
        {copy.karneTitle}
      </h2>
      <p className={styles.lede}>{copy.karneLede}</p>
      {state.status === "pending" ? (
        <p className={styles.state}>{board.loading}</p>
      ) : state.status === "missing" ? (
        <p className={styles.state}>{board.notPublished}</p>
      ) : state.status === "error" ? (
        <p className={styles.state}>{board.notAvailable}</p>
      ) : weeks.length === 0 ? (
        <p className={styles.state}>{board.noGameweek}</p>
      ) : (
        <>
          <ul className={styles.legend} aria-hidden="true">
            {(["ours", "league", "game"] as const).map((series) => (
              <li key={series}>
                <span className={`${styles.swatch} ${styles[series]}`} />
                {names[series]}
              </li>
            ))}
          </ul>
          <ol className={styles.weeks} style={{ "--max": max } as CSSProperties}>
            {weeks.map((week) => (
              <li key={week.gameweek} className={styles.week}>
                <span className={styles.weekName}>
                  {copy.karneWeek(week.gameweek)}
                  {week.provisional ? (
                    <span className={styles.provisional}>{board.provisional}</span>
                  ) : null}
                  {week.replay && week.ours !== null ? (
                    <span className={styles.provisional}>{copy.karneReplay}</span>
                  ) : null}
                </span>
                <div className={styles.bars} role="img" aria-label={describe(week)}>
                  {(["ours", "league", "game"] as const).map((series) => {
                    const value = week[series];
                    return (
                      <span key={series} className={styles.bar} data-series={series}>
                        {value === null ? (
                          <span className={styles.none}>{copy.karneNone}</span>
                        ) : (
                          <>
                            <span
                              className={`${styles.fill} ${styles[series]}`}
                              style={{ "--points": Math.max(0, value) } as CSSProperties}
                            />
                            <span className={styles.value}>{format(series, value)}</span>
                          </>
                        )}
                      </span>
                    );
                  })}
                </div>
              </li>
            ))}
          </ol>
          <p className={styles.caption}>{copy.karneCaption}</p>
          {weeks.some((week) => week.ours !== null && week.namedEleven) ? (
            <p className={styles.caption}>{copy.karneNamedEleven}</p>
          ) : null}
          {weeks.some((week) => week.ours !== null && week.replay) ? (
            <p className={styles.caption}>{copy.karneReplayNote}</p>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * The whole scoreboard behind the record, closed until asked for: the scoring basis, live
 * or replay, provisional weeks and the error breakdown. It is a wide table, so the page
 * gives it the full width under the table and the record rather than the record's narrow
 * column; it exists only where the record has weeks to show.
 */
export function SystemScoreboardDetails({
  state,
  leagueId,
  className,
}: {
  state: ScoreboardState;
  leagueId: number;
  className?: string;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  if (state.status !== "ready" || state.envelope.payload.league_id !== leagueId) return null;
  if (karneWeeks(state.envelope.payload).length === 0) return null;
  return (
    <details className={className ? `${styles.full} ${className}` : styles.full}>
      <summary className={styles.fullSummary}>
        <DisclosureIcon className={styles.fullIcon} />
        <span>{copy.karneFull}</span>
      </summary>
      <div className={styles.fullBody}>
        <ScoreboardCard envelope={state.envelope} />
      </div>
    </details>
  );
}
