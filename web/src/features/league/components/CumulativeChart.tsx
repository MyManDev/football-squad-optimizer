import type { LedgerRowView } from "../../../data/schema";
import { points } from "../../../lib/format";
import styles from "./CumulativeChart.module.css";

const W = 640;
const H = 220;
const PAD = { top: 12, right: 16, bottom: 28, left: 44 };

/**
 * Cumulative projected vs realized points by gameweek. Every value plotted is a field
 * of the ledger view (`cumulative_projected_score`, `cumulative_realized_score`); the
 * component scales and draws, it does not sum.
 */
export function CumulativeChart({ rows }: { rows: LedgerRowView[] }) {
  if (rows.length === 0) return null;
  const projected = rows.map((r) => r.cumulative_projected_score);
  const realized = rows
    .filter((r) => r.cumulative_realized_score !== null)
    .map((r) => ({ gw: r.gameweek, value: r.cumulative_realized_score as number }));
  const maxY = Math.max(1, ...projected, ...realized.map((r) => r.value));
  const gws = rows.map((r) => r.gameweek);
  const minX = Math.min(...gws);
  const maxX = Math.max(minX + 1, ...gws);
  const x = (gw: number) => PAD.left + ((gw - minX) / (maxX - minX)) * (W - PAD.left - PAD.right);
  const y = (v: number) => H - PAD.bottom - (v / maxY) * (H - PAD.top - PAD.bottom);
  const line = (pts: Array<[number, number]>) => pts.map(([px, py]) => `${px},${py}`).join(" ");
  const ticks = [0, 0.5, 1].map((f) => Math.round(maxY * f));
  const projectedPts: Array<[number, number]> = rows.map((r) => [
    x(r.gameweek),
    y(r.cumulative_projected_score),
  ]);
  const realizedPts: Array<[number, number]> = realized.map((r) => [x(r.gw), y(r.value)]);
  const last = rows[rows.length - 1];
  return (
    <figure className={styles.figure}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-label={`Cumulative projected (${points(last.cumulative_projected_score, 0)}) versus realized points by gameweek`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={styles.grid} />
            <text x={PAD.left - 6} y={y(t) + 4} className={styles.tick} textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {gws.map((gw) => (
          <text
            key={gw}
            x={x(gw)}
            y={H - PAD.bottom + 16}
            className={styles.tick}
            textAnchor="middle"
          >
            {gw}
          </text>
        ))}
        <polyline points={line(projectedPts)} className={styles.projected} />
        {realizedPts.length > 0 && (
          <polyline points={line(realizedPts)} className={styles.realized} />
        )}
        {realizedPts.length > 0 && (
          <circle
            cx={realizedPts[realizedPts.length - 1][0]}
            cy={realizedPts[realizedPts.length - 1][1]}
            r={4}
            className={styles.dot}
          />
        )}
        {projectedPts.length === 1 && (
          <circle
            cx={projectedPts[0][0]}
            cy={projectedPts[0][1]}
            r={4}
            className={styles.dotMuted}
          />
        )}
      </svg>
      <figcaption className={styles.legend}>
        <span>
          <i className={styles.swatchProjected} /> projected, cumulative
        </span>
        <span>
          <i className={styles.swatchRealized} /> realized, cumulative
          {realizedPts.length === 0 ? " (after the first settle)" : ""}
        </span>
      </figcaption>
    </figure>
  );
}
