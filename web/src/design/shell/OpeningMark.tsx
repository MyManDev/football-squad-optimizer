import { useEffect, useState } from "react";
import "@fontsource/allura/latin-400.css";

import { MOTION_MS, prefersReducedMotion } from "../motion";
import styles from "./OpeningMark.module.css";

/** Set once the opening has played in this tab, so a reload or a new page does not replay it. */
export const OPENING_STORAGE_KEY = "squadopt.openingShown";

/** The opening's one clock: ten data-motion lengths, as `--opening-length` in the stylesheet. */
export const OPENING_MS = MOTION_MS.data * 10;

/**
 * When the clock takes the cover off: a beat after its animations end, so they finish rather
 * than being cancelled by the removal (a cancelled animation rejects its `finished` promise).
 */
export const OPENING_LEAVE_MS = OPENING_MS + MOTION_MS.ui;

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
 * beside SquadOpt. The maker's signature sits in the lower right as the cover fades.
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
    const timer = window.setTimeout(() => setOpen(false), OPENING_LEAVE_MS);
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
      <div className={styles.signature}>
        <span className={styles.signatureName}>MyManDev</span>
        <span className={styles.signatureLine}>Still Building</span>
      </div>
      <div className={styles.brand}>
        <svg className={styles.mark} width="40" height="50" viewBox="0 0 16 20">
          <rect x="0" y="0" width="16" height="9" rx="2" data-bar="out" />
          <rect x="0" y="11" width="16" height="9" rx="2" data-bar="in" />
        </svg>
        <span className={styles.word}>SquadOpt</span>
      </div>
    </div>
  );
}
