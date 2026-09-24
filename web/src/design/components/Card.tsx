import type { ReactNode } from "react";

import styles from "./Card.module.css";

/**
 * One region of a page: an optional heading row and its content, separated from what
 * comes before it by a hairline and space rather than a box. `muted` reads quieter;
 * `pitch` marks a region whose content draws its own grass (the heading stays on the
 * page, never on the grass), so it looks like `surface`.
 */
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
  const className = tone === "muted" ? `${styles.card} ${styles.muted}` : styles.card;
  return (
    <section className={className}>
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
