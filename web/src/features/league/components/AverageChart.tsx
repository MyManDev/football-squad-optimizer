import type { LeagueWeekView } from "../../../data/schema";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import styles from "./AverageChart.module.css";

const W = 640;
const H = 200;
const PAD = { top: 12, right: 16, bottom: 26, left: 40 };

/**
 * Our net score against the game's own average, gameweek by gameweek. Only weeks the
 * game has scored are drawn; an unscored week is a gap, not a zero.
 */
export function AverageChart({ weeks }: { weeks: LeagueWeekView[] }) {
  const { locale, messages } = useLanguage();
  const scored = weeks.filter(
    (w) => w.average_entry_score !== null && w.our_realized_net_score !== null,
  );
  if (scored.length === 0) return null;
  const values = scored.flatMap((w) => [
    w.average_entry_score as number,
    w.our_realized_net_score as number,
  ]);
  const minY = Math.min(0, ...values);
  const maxY = Math.max(minY === 0 ? 1 : 0, ...values);
  const first = scored[0].gameweek;
  const last = Math.max(first + 1, scored[scored.length - 1].gameweek);
  const x = (gw: number) => PAD.left + ((gw - first) / (last - first)) * (W - PAD.left - PAD.right);
  const y = (v: number) =>
    H - PAD.bottom - ((v - minY) / (maxY - minY)) * (H - PAD.top - PAD.bottom);
  const zero = y(0);
  const ticks = [...new Set([minY, minY < 0 ? 0 : Math.floor(maxY / 2), maxY])];
  const barWidth = Math.max(6, Math.min(28, (W - PAD.left - PAD.right) / (scored.length * 2.2)));
  const line = scored
    .map((w) => `${x(w.gameweek)},${y(w.average_entry_score as number)}`)
    .join(" ");
  return (
    <figure className={styles.figure}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-label={messages.league.averageLabel(scored.length)}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              className={tick === 0 ? styles.zero : styles.grid}
            />
            <text x={PAD.left - 20} y={y(tick) + 4} className={styles.tick} textAnchor="end">
              {Math.round(tick)}
            </text>
          </g>
        ))}
        {scored.map((w) => {
          const ours = w.our_realized_net_score as number;
          const ahead = ours >= (w.average_entry_score as number);
          return (
            <g key={w.gameweek}>
              <rect
                x={x(w.gameweek) - barWidth / 2}
                y={Math.min(y(ours), zero)}
                width={barWidth}
                height={Math.abs(y(ours) - zero)}
                className={ahead ? styles.barAhead : styles.barBehind}
              />
              <text
                x={x(w.gameweek)}
                y={H - PAD.bottom + 15}
                className={styles.tick}
                textAnchor="middle"
              >
                {w.gameweek}
              </text>
            </g>
          );
        })}
        <polyline points={line} className={styles.average} />
        {scored.map((w) => (
          <circle
            key={`avg-${w.gameweek}`}
            cx={x(w.gameweek)}
            cy={y(w.average_entry_score as number)}
            r={3}
            className={styles.averageDot}
          />
        ))}
      </svg>
      <figcaption className={styles.legend}>
        <span>
          <i className={styles.swatchOurs} /> {messages.league.ourNet}
        </span>
        <span>
          <i className={styles.swatchAverage} /> {messages.league.gameAverage}
        </span>
        <span className={styles.muted}>
          {messages.league.lastWeek(
            points(scored[scored.length - 1].difference_to_average as number, 0, locale),
          )}
        </span>
      </figcaption>
    </figure>
  );
}
