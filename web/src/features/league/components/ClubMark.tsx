import { clubCode, clubSwatch, type ClubCodes } from "../../../lib/clubs";
import styles from "./ClubMark.module.css";

/**
 * A club as the boards, plates and fixture cells print it: a 10 px swatch with an ink
 * outline and the three-letter code in mono. The swatch is decoration (the code is always
 * beside it). A club with no known code is printed by its name, never an invented code.
 */
export function ClubMark({ team, codes }: { team: string; codes?: ClubCodes | null }) {
  const code = clubCode(team, codes);
  const swatch = clubSwatch(code);
  return (
    <span className={styles.club}>
      {swatch ? (
        <span className={styles.swatch} style={{ background: swatch }} aria-hidden="true" />
      ) : null}
      <span className={code ? styles.code : undefined}>{code ?? team}</span>
    </span>
  );
}
