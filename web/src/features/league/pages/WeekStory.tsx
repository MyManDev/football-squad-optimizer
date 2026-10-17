import { useId, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import { signedPoints } from "../../../lib/format";
import { CHIP_COPY } from "../advice/chipCopy";
import type { EntryAdvice } from "../types";
import { hasPublishedPlan, namedChip, STORY_ANCHORS } from "./storyPlan";
import styles from "./WeekStory.module.css";

/**
 * The week's decisions as short cards at the top of the member page (#1134): transfers,
 * captain and chip, each from the advice document alone. A week without a transfer or a chip
 * shows no card for it, and a week with none of the three shows nothing. The transfer and
 * captain cards are links into their detail below; the chip card opens on itself, lifting
 * slightly, with the chip and what the chip week adds against the member's own plan.
 */
export function WeekStory({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const titleId = useId();
  const [chipOpen, setChipOpen] = useState(false);
  const planned = hasPublishedPlan(view);
  const moves = planned ? view.moves : [];
  const captain = planned ? (view.captain ?? null) : null;
  const chip = namedChip(view);
  if (moves.length === 0 && !captain && !chip) return null;

  const swaps = moves
    .map((move) => {
      const out = move.player_out?.short_name || move.player_out?.name;
      const into = move.player_in?.short_name || move.player_in?.name;
      return out && into ? `${out} → ${into}` : null;
    })
    .filter((swap): swap is string => swap !== null)
    .join(", ");
  const gain = view.chip_choice?.gain_vs_no_chip;
  const chipName = chip ? (copy.chipNames[chip] ?? chip) : null;

  return (
    <nav className={styles.story} aria-labelledby={titleId}>
      <h2 className="visually-hidden" id={titleId}>
        {copy.storyTitle}
      </h2>
      <ul className={styles.cards}>
        {moves.length > 0 ? (
          <li className={styles.card} data-story="transfers">
            <a className={styles.link} href={`#${STORY_ANCHORS.transfers}`}>
              <span className={styles.label}>{copy.storyTransfers}</span>
              <span className={styles.value}>{copy.storyMoves(moves.length)}</span>
              {swaps ? <span className={styles.detail}>{swaps}</span> : null}
            </a>
          </li>
        ) : null}
        {captain ? (
          <li className={styles.card} data-story="captain">
            <a className={styles.link} href={`#${STORY_ANCHORS.captain}`}>
              <span className={styles.label}>{copy.captainLabel}</span>
              <span className={styles.value}>{captain.short_name || captain.name}</span>
            </a>
          </li>
        ) : null}
        {chip && chipName ? (
          <li className={styles.card} data-story="chip" data-open={chipOpen ? "" : undefined}>
            <button
              type="button"
              className={styles.link}
              aria-expanded={chipOpen}
              onClick={() => setChipOpen((open) => !open)}
            >
              <span className={styles.label}>{copy.chipLabel}</span>
              <span className={styles.value}>{chipName}</span>
            </button>
            {chipOpen ? (
              <div className={styles.opened}>
                <p className={styles.detail}>{copy.storyChipPlay}</p>
                {typeof gain === "number" && Number.isFinite(gain) ? (
                  <p className={`${styles.detail} num`}>
                    {CHIP_COPY[language].gain(signedPoints(gain, 1, locale))}
                  </p>
                ) : null}
                {view.chip_choice ? (
                  <a className={styles.more} href={`#${STORY_ANCHORS.chip}`}>
                    {copy.storyDetail}
                  </a>
                ) : null}
              </div>
            ) : null}
          </li>
        ) : null}
      </ul>
    </nav>
  );
}
