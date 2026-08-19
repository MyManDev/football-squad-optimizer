import type { ReactNode } from "react";

import styles from "./Badge.module.css";

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
}) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
