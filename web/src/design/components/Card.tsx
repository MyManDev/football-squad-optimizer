import type { ReactNode } from "react";

import styles from "./Card.module.css";

export function Card({
  title,
  aside,
  children,
  tone = "surface",
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  tone?: "surface" | "muted" | "pitch";
}) {
  return (
    <section className={`${styles.card} ${styles[tone]}`}>
      {(title || aside) && (
        <header className={styles.header}>
          {title && <h2 className={styles.title}>{title}</h2>}
          {aside && <div className={styles.aside}>{aside}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
