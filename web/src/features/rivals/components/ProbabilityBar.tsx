import { percent } from "../../../lib/format";
import styles from "./ProbabilityBar.module.css";

/**
 * A probability with its interval, drawn rather than written twice: the bar is the estimate,
 * the lighter band behind it is the 90% interval. Nothing is computed here — both come from
 * the risk view.
 */
export function ProbabilityBar({
  probability,
  interval,
  label,
}: {
  probability: number;
  interval?: [number, number] | null;
  label: string;
}) {
  const [low, high] = interval ?? [probability, probability];
  return (
    <div
      className={styles.wrap}
      role="img"
      aria-label={`${label}: ${percent(probability)}${
        interval ? `, 90% interval ${percent(low)} to ${percent(high)}` : ""
      }`}
    >
      <div className={styles.track}>
        <div
          className={styles.interval}
          style={{ left: `${low * 100}%`, width: `${Math.max(0, high - low) * 100}%` }}
        />
        <div className={styles.estimate} style={{ left: `${probability * 100}%` }} />
        <div className={styles.midline} />
      </div>
      <div className={styles.scale}>
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

/** A plain magnitude bar for expected points, in the pool tables. */
export function PointsBar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className={styles.pointsTrack} aria-hidden="true">
      <div className={styles.pointsFill} style={{ width: `${width}%` }} />
    </div>
  );
}
