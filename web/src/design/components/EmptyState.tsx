import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles.empty} role="status">
      <div className={styles.title}>{title}</div>
      {children && <div className={styles.body}>{children}</div>}
    </div>
  );
}
