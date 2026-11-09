import type { ReactNode } from "react";

import { DisclosureIcon } from "./memberIcons";
import styles from "./RowDetails.module.css";

/**
 * A table row's figures that have no room on a phone, folded out under it: the 44 px chevron
 * at the row's end, and the labelled figures in the row drawn under it.
 */
export function RowDetailsToggle({
  open,
  controls,
  label,
  onToggle,
}: {
  open: boolean;
  /** The id of the row drawn under this one while it is open. */
  controls: string;
  /** Names the row as well as the control: every row has one. */
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      aria-label={label}
      onClick={onToggle}
    >
      <DisclosureIcon className={styles.icon} />
    </button>
  );
}

export function RowDetailsFigures({
  figures,
}: {
  figures: ReadonlyArray<{ label: string; value: ReactNode }>;
}) {
  return (
    <dl className={styles.figures}>
      {figures.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="num">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
