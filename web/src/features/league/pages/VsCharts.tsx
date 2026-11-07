import type { Breakdown } from "./vsBreakdown";
import styles from "./VsCharts.module.css";

/**
 * The pictures of VS SQUADOPT, inline SVG in the page's own colours: the two nets as a pair of
 * bars, the week's difference split into signed bars from a zero line, and the compared weeks
 * as a strip of small bars that picks the week. SquadOpt is the green of the page's "good",
 * the member the amber of its "warn"; each bar carries its number, so colour is never alone.
 */

const BAR = 18;
const GAP = 10;

export function NetBars({
  suggested,
  actual,
  labels,
  format,
}: {
  suggested: number;
  actual: number;
  labels: { squadopt: string; you: string };
  format: (value: number) => string;
}) {
  const max = Math.max(suggested, actual, 1);
  const width = 320;
  const labelWidth = 92;
  const plot = width - labelWidth - 56;
  const rows = [
    { key: "squadopt", label: labels.squadopt, value: suggested, className: styles.squadopt },
    { key: "you", label: labels.you, value: actual, className: styles.you },
  ];
  const height = rows.length * (BAR + GAP) + GAP;
  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${labels.squadopt} ${format(suggested)}, ${labels.you} ${format(actual)}`}
      data-testid="vs-net-bars"
    >
      {rows.map((row, index) => {
        const y = GAP + index * (BAR + GAP);
        const length = Math.max(4, (row.value / max) * plot);
        return (
          <g key={row.key}>
            <text x={labelWidth - 8} y={y + BAR / 2} className={styles.rowLabel} textAnchor="end">
              {row.label}
            </text>
            <rect x={labelWidth} y={y} width={length} height={BAR} rx={4} className={row.className}>
              <title>{`${row.label}: ${format(row.value)}`}</title>
            </rect>
            <text x={labelWidth + length + 8} y={y + BAR / 2} className={styles.value}>
              {format(row.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function DifferenceBars({
  parts,
  labels,
  format,
}: {
  parts: Breakdown;
  labels: { captain: string; transfers: string; hits: string; lineup: string };
  format: (value: number) => string;
}) {
  const rows = (
    [
      ["captain", labels.captain, parts.captain],
      ["transfers", labels.transfers, parts.transfers],
      ["hits", labels.hits, parts.hits],
      ["lineup", labels.lineup, parts.lineup],
    ] as const
  ).map(([key, label, value]) => ({ key, label, value }));
  const width = 320;
  const labelWidth = 120;
  const plot = width - labelWidth - 16;
  const zero = labelWidth + plot / 2;
  const max = Math.max(1, ...rows.map((row) => Math.abs(row.value)));
  const scale = (plot / 2 - 40) / max;
  const height = rows.length * (BAR + GAP) + GAP;
  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={rows.map((row) => `${row.label} ${format(row.value)}`).join(", ")}
      data-testid="vs-difference-bars"
    >
      <line x1={zero} x2={zero} y1={2} y2={height - 2} className={styles.zero} />
      {rows.map((row, index) => {
        const y = GAP + index * (BAR + GAP);
        const length = Math.abs(row.value) * scale;
        const positive = row.value >= 0;
        const x = positive ? zero + 1 : zero - 1 - length;
        const labelX = positive ? zero + 1 + length + 6 : zero - 1 - length - 6;
        return (
          <g key={row.key}>
            <text x={labelWidth - 8} y={y + BAR / 2} className={styles.rowLabel} textAnchor="end">
              {row.label}
            </text>
            {length > 0 ? (
              <rect
                x={x}
                y={y}
                width={Math.max(2, length)}
                height={BAR}
                rx={4}
                className={positive ? styles.squadopt : styles.you}
              >
                <title>{`${row.label}: ${format(row.value)}`}</title>
              </rect>
            ) : null}
            <text
              x={labelX}
              y={y + BAR / 2}
              className={styles.value}
              textAnchor={positive ? "start" : "end"}
            >
              {format(row.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function WeekStrip({
  weeks,
  chosen,
  onSelect,
  label,
  weekName,
  format,
}: {
  weeks: { gameweek: number; difference: number }[];
  chosen: number;
  onSelect: (gameweek: number) => void;
  label: string;
  weekName: (gameweek: number) => string;
  format: (value: number) => string;
}) {
  const max = Math.max(1, ...weeks.map((week) => Math.abs(week.difference)));
  return (
    <div className={styles.strip} role="group" aria-label={label} data-testid="vs-week-strip">
      {[...weeks]
        .sort((a, b) => a.gameweek - b.gameweek)
        .map((week) => {
          const share = Math.abs(week.difference) / max;
          const positive = week.difference >= 0;
          return (
            <button
              key={week.gameweek}
              type="button"
              className={styles.stripWeek}
              aria-pressed={week.gameweek === chosen}
              aria-label={`${weekName(week.gameweek)}, ${format(week.difference)}`}
              onClick={() => onSelect(week.gameweek)}
            >
              <span className={styles.stripBars} aria-hidden="true">
                <span
                  className={`${styles.stripBar} ${positive ? styles.squadoptFill : styles.youFill} ${positive ? styles.up : styles.down}`}
                  style={{ height: `${Math.max(6, share * 40)}px` }}
                />
              </span>
              <span className={styles.stripLabel} aria-hidden="true">
                {week.gameweek}
              </span>
            </button>
          );
        })}
    </div>
  );
}
