import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

export function EmptyState({
  title,
  page = false,
  children,
}: {
  title: string;
  /** The state is all the page holds, so its title is the page's heading. */
  page?: boolean;
  children?: ReactNode;
}) {
  const Title = page ? "h1" : "div";
  return (
    <div className={styles.empty} role="status">
      <Title className={styles.title}>{title}</Title>
      {children && <div className={styles.body}>{children}</div>}
    </div>
  );
}
