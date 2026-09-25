import type { ReactNode } from "react";

import styles from "./Badge.module.css";

export type BadgeTone = "neutral" | "good" | "warn" | "bad" | "accent" | "lime";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
