import type { CSSProperties } from "react";

import { clubColours } from "../../lib/clubs";
import styles from "./ClubSwatch.module.css";

/**
 * A club's colours as a 10 px swatch with an ink outline: its primary colour alone, or,
 * with `split`, its two colours divided on the diagonal (the primary top left). The outline
 * keeps a white half visible on a light page. It is decoration: the club's code or name is
 * always printed beside it, so assistive technology skips it. A code with no colours draws
 * nothing.
 */
export function ClubSwatch({
  code,
  split = false,
}: {
  code: string | null | undefined;
  split?: boolean;
}) {
  const colours = clubColours(code);
  if (!colours) return null;
  if (!split)
    return (
      <span className={styles.swatch} style={{ background: colours.primary }} aria-hidden="true" />
    );
  const style = {
    "--club-primary": colours.primary,
    "--club-secondary": colours.secondary,
  } as CSSProperties;
  return <span className={`${styles.swatch} ${styles.split}`} style={style} aria-hidden="true" />;
}
