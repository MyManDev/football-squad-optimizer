import { useLanguage } from "../../../i18n/context";
import type { ViewerChipLines } from "../chipShape";
import styles from "./ViewerChips.module.css";

/**
 * The viewer's chips for the half of the season being played, one line a chip ('hazır',
 * 'kullanıldı · 4. hafta'), as D-Lig draws them beside the table. In the first half, a
 * quiet line says the second half's chips are not open yet when that is what the document
 * says of every one of them.
 */
export function ViewerChips({ chips }: { chips: ViewerChipLines }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const resources = messages.memberResources;
  return (
    <section className={styles.chips} aria-labelledby="viewer-chips-title">
      <div className={styles.head}>
        <h2 className={styles.title} id="viewer-chips-title">
          {resources.chipsTitle}
        </h2>
        <span className={styles.half}>{resources.halves[chips.half]}</span>
      </div>
      <ul className={styles.list}>
        {chips.lines.map(({ chip, window }) => (
          <li key={chip} className={styles.chip} data-state={window.state}>
            <span className={styles.name}>{copy.chipNames[chip]}</span>
            <span className={styles.state}>
              {window.state === "used" && window.gameweek !== null
                ? copy.chipLine.used(window.gameweek)
                : window.state === "used"
                  ? resources.states.used
                  : copy.chipLine[window.state]}
            </span>
          </li>
        ))}
      </ul>
      {chips.secondHalfClosed ? <p className={styles.note}>{copy.chipsHalfNote}</p> : null}
    </section>
  );
}
