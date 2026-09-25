import { useLanguage } from "../../../i18n/context";
import { CHIP_NAMES, currentChipHalf, isEntryChips } from "../chipShape";
import type { EntrySquad } from "../types";
import styles from "./ViewerChips.module.css";

/**
 * The viewer's chips for the half of the season being played, one line a chip ('hazır',
 * 'kullanıldı · 4. hafta'), as D-Lig draws them beside the table. In the first half, a
 * quiet line says the second half's chips are not open yet when that is what the document
 * says of every one of them. Chips the document does not know read as unknown.
 */
export function ViewerChips({ squad }: { squad: EntrySquad }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const resources = messages.memberResources;
  const chips = isEntryChips(squad.chips, squad.gameweek) ? squad.chips : undefined;
  const half = chips?.known ? currentChipHalf(chips) : null;
  const secondHalfClosed =
    chips?.known === true &&
    half === "first_half" &&
    CHIP_NAMES.every((chip) => chips.states[chip]?.second_half?.state === "not_yet");
  return (
    <section className={styles.chips} aria-labelledby="viewer-chips-title">
      <div className={styles.head}>
        <h2 className={styles.title} id="viewer-chips-title">
          {resources.chipsTitle}
        </h2>
        {half ? <span className={styles.half}>{resources.halves[half]}</span> : null}
      </div>
      {!chips?.known || half === null ? (
        <p className={styles.note}>{resources.chipsMissing}</p>
      ) : (
        <>
          <ul className={styles.list}>
            {CHIP_NAMES.map((chip) => {
              const window = chips.states[chip]?.[half] ?? null;
              return (
                <li key={chip} className={styles.chip} data-state={window?.state ?? "none"}>
                  <span className={styles.name}>{copy.chipNames[chip]}</span>
                  <span className={styles.state}>
                    {window === null
                      ? resources.noWindow
                      : window.state === "used" && window.gameweek !== null
                        ? copy.chipLine.used(window.gameweek)
                        : window.state === "used"
                          ? resources.states.used
                          : copy.chipLine[window.state]}
                  </span>
                </li>
              );
            })}
          </ul>
          {secondHalfClosed ? <p className={styles.note}>{copy.chipsHalfNote}</p> : null}
        </>
      )}
    </section>
  );
}
