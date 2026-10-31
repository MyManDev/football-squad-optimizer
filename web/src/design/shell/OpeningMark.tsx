import { useEffect, useState } from "react";

import { MOTION_MS, prefersReducedMotion } from "../motion";
import styles from "./OpeningMark.module.css";

/** Set once the opening has played in this tab, so a reload or a new page does not replay it. */
export const OPENING_STORAGE_KEY = "squadopt.openingShown";

/** The opening's one clock: five data-motion lengths, as `--opening-length` in the stylesheet. */
export const OPENING_MS = MOTION_MS.data * 5;

function shouldOpen(): boolean {
  if (prefersReducedMotion()) return false;
  try {
    return window.sessionStorage.getItem(OPENING_STORAGE_KEY) === null;
  } catch {
    /* Storage may be unavailable; the opening then plays on each load of the site. */
    return true;
  }
}

/**
 * The brand's opening, once per tab: the two bars stand side by side, red on the left and
 * green on the right, then turn a quarter clockwise into the SquadOpt mark (red over green)
 * under the word SquadOpt, and the cover fades off the page.
 *
 * It is decoration only: hidden from assistive technology, inert, and transparent to the
 * pointer, so the page under it can be used from the first frame. Under the reduced-motion
 * preference it never shows.
 */
export function OpeningMark() {
  const [open, setOpen] = useState(shouldOpen);
  useEffect(() => {
    try {
      window.sessionStorage.setItem(OPENING_STORAGE_KEY, "1");
    } catch {
      /* Nothing to remember it in; see shouldOpen. */
    }
    // The cover leaves when its fade ends; a page that draws no frames (a hidden tab) sends
    // no animationend, so the clock takes it off as well.
    const timer = window.setTimeout(() => setOpen(false), OPENING_MS);
    return () => window.clearTimeout(timer);
  }, []);
  if (!open) return null;
  return (
    <div
      className={styles.cover}
      aria-hidden="true"
      inert
      data-opening-mark=""
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}
    >
      <span className={styles.word}>SquadOpt</span>
      <svg className={styles.mark} width="64" height="80" viewBox="0 0 16 20">
        <rect x="0" y="0" width="16" height="9" rx="2" data-bar="out" />
        <rect x="0" y="11" width="16" height="9" rx="2" data-bar="in" />
      </svg>
    </div>
  );
}
