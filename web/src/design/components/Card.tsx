import type { ReactNode } from "react";

import styles from "./Card.module.css";

/**
 * One region of a page: an optional heading row and its content, separated from what
 * comes before it by a hairline and space rather than a box. `muted` reads quieter. A
 * region that holds a pitch is a plain region: the pitch draws its own grass, and the
 * heading stays on the page, never on the grass. `zone` names the region for the usage
 * record's clicks (ADR 0015).
 */
export function Card({
  title,
  aside,
  children,
  tone = "surface",
  zone,
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  tone?: "surface" | "muted";
  zone?: string;
}) {
  const className = tone === "muted" ? `${styles.card} ${styles.muted}` : styles.card;
  return (
    <section className={className} data-zone={zone}>
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
