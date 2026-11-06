import { useLanguage } from "../../../i18n/context";
import page from "./LeagueMemberPage.module.css";
import styles from "./MemberPageSkeleton.module.css";

/** The score bug's cells in most weeks: rank, season total, last week, bank and transfers. */
const CELLS = 5;

/**
 * The member page while its squad is read: the page's own top bar with its row of figures,
 * then the decision and the pitch as quiet blocks where the page will draw them, so the
 * page arrives where the visitor is already looking instead of after one line of text.
 *
 * It is a status, busy until the page replaces it, and says what it waits for in words a
 * screen reader reads; the blocks are hidden from it. Nothing in it moves: a shimmer would
 * never let the page come to rest (e2e/atRest.ts), and the motion rules (#1136) want an
 * event behind every movement.
 */
export function MemberPageSkeleton() {
  const { messages } = useLanguage();
  return (
    <div className={page.page} role="status" aria-busy="true">
      <span className="visually-hidden">{messages.leagueMembers.loadingEntry}</span>
      <div className={`${page.topBar} ${styles.bar}`} aria-hidden="true">
        <span className={`${styles.bone} ${styles.team}`} />
        <span className={`${styles.bone} ${styles.week}`} />
        <span className={page.scoreBug}>
          {Array.from({ length: CELLS }, (_, cell) => (
            <span key={cell} className={page.scoreCell}>
              <span className={`${styles.bone} ${styles.label}`} />
              <span className={`${styles.bone} ${styles.figure}`} />
            </span>
          ))}
        </span>
      </div>
      <div className={styles.decision} aria-hidden="true">
        <span className={`${styles.bone} ${styles.heading}`} />
        <span className={`${styles.bone} ${styles.line}`} />
        <span className={`${styles.bone} ${styles.board}`} />
      </div>
      <div className={styles.pitchArea} aria-hidden="true">
        <span className={styles.pitch} />
      </div>
    </div>
  );
}
