import styles from "./PointsBar.module.css";

/** A plain magnitude bar for expected points, in the pool tables. */
export function PointsBar({ value, max }: { value: number; max: number }) {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className={styles.pointsTrack} aria-hidden="true">
      <div className={styles.pointsFill} style={{ width: `${width}%` }} />
    </div>
  );
}
