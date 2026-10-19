import { ClubSwatch } from "../../../design/components/ClubSwatch";
import { clubCode, type ClubCodes } from "../../../lib/clubs";
import styles from "./ClubMark.module.css";

/**
 * A club as the boards, plates and squad lists print it: a 10 px swatch of its primary
 * colour with an ink outline and the three-letter code in mono. The swatch is decoration
 * (the code is always beside it). A club with no known code is printed by its name, never
 * an invented code.
 */
export function ClubMark({ team, codes }: { team: string; codes?: ClubCodes | null }) {
  const code = clubCode(team, codes);
  return (
    <span className={styles.club}>
      <ClubSwatch code={code} />
      <span className={code ? styles.code : undefined}>{code ?? team}</span>
    </span>
  );
}
