import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { DisclosureIcon } from "./memberIcons";
import styles from "./PitchLookControl.module.css";
import { GRASS_LOOKS, usePitchLook } from "./pitchLook";

/**
 * The pitch's look under the bench (#1136): the grass's pattern and the plates' club
 * colours, each as a row of real buttons drawn as one segmented control, reachable with a
 * thumb and saying everything without a hover. Both rows wait in one closed "Saha
 * görünümü" menu, so five buttons a member seldom needs do not stand between the bench and
 * the rest of the page. A choice changes the drawing at once and is kept in this browser;
 * it changes no name, figure or plan. The menu opens closed on every visit: the look is
 * kept, not the menu.
 */
export function PitchLookControl() {
  const copy = useLanguage().messages.leagueMembers;
  const [look, change] = usePitchLook();
  const grassId = useId();
  const clubId = useId();
  const grassName = {
    stripes: copy.pitchLookStripes,
    plain: copy.pitchLookPlain,
    checks: copy.pitchLookChecks,
  } as const;
  return (
    <details className={styles.looks} data-mark="pitch-look">
      <summary className={styles.summary}>
        <DisclosureIcon className={styles.icon} />
        {copy.pitchLookMenu}
      </summary>
      <div className={styles.row}>
        <span className={styles.label} id={grassId}>
          {copy.pitchLookLabel}
        </span>
        <div className={styles.toggle} role="group" aria-labelledby={grassId}>
          {GRASS_LOOKS.map((grass) => (
            <button
              key={grass}
              type="button"
              className={styles.option}
              aria-pressed={look.grass === grass}
              onClick={() => change({ grass })}
            >
              <span className={styles.face}>{grassName[grass]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className={styles.row}>
        <span className={styles.label} id={clubId}>
          {copy.clubColoursLabel}
        </span>
        <div className={styles.toggle} role="group" aria-labelledby={clubId}>
          {([false, true] as const).map((on) => (
            <button
              key={String(on)}
              type="button"
              className={styles.option}
              aria-pressed={look.clubColours === on}
              onClick={() => change({ clubColours: on })}
            >
              <span className={styles.face}>{on ? copy.clubColoursOn : copy.clubColoursOff}</span>
            </button>
          ))}
        </div>
      </div>
    </details>
  );
}
