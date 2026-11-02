/**
 * The device solve at work, in the middle of the screen: how many of the run's stages are
 * done, and a bar that follows them. The count is of those stages, never of elapsed time, so
 * it moves in steps: one solve reports nothing until it ends. It is written as a count
 * ("2/7"), never as a percentage, because member pages carry no percentages.
 *
 * It covers the whole screen with the page's background, so nothing of the page shows
 * while the run counts. It is drawn into the document's body, so a closed drawer or a
 * sticky sidebar does not hide it, and it goes as soon as nothing is counting. While it stands
 * the page behind is inert and focus is on the card; when it goes, focus returns to the
 * control the page names.
 */

import { useEffect, useRef, type RefObject } from "react";
import { createPortal } from "react-dom";

import { useLanguage } from "../../../i18n/context";
import { countingProgress, progressShare } from "./progress";
import type { DevicePlanPhase } from "./useDevicePlan";
import styles from "./DeviceProgressPanel.module.css";

export function DeviceProgressPanel({
  state,
  returnFocus,
}: {
  state: DevicePlanPhase;
  /** The control that started the run, which takes focus back when the cover goes. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const progress = countingProgress(state);
  const counting = progress !== null;
  const panel = useRef<HTMLElement>(null);

  // A cover hides the page, not its controls: everything else in the body goes inert with it.
  useEffect(() => {
    if (!counting) return;
    const control = returnFocus?.current;
    const behind = [...document.body.children].filter(
      (element) => !element.contains(panel.current) && !element.hasAttribute("inert"),
    );
    for (const element of behind) element.setAttribute("inert", "");
    panel.current?.focus();
    return () => {
      for (const element of behind) element.removeAttribute("inert");
      control?.focus();
    };
  }, [counting, returnFocus]);

  if (progress === null || typeof document === "undefined") return null;

  const share = progressShare(progress);
  // Before the inputs say how many stages there are, there is nothing to count yet.
  const count = progress.total === null ? null : `${progress.done}/${progress.total}`;

  return createPortal(
    <div className={styles.layer} data-device-progress={progress.step}>
      <section
        ref={panel}
        className={styles.panel}
        aria-labelledby="device-progress-title"
        tabIndex={-1}
      >
        <h2 id="device-progress-title" className={styles.title}>
          {copy.deviceSolving}
        </h2>
        {count === null ? null : (
          <p className={styles.share} aria-hidden="true">
            {count}
          </p>
        )}
        <div
          className={styles.track}
          role="progressbar"
          aria-labelledby="device-progress-title"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(share * 100)}
          aria-valuetext={count ?? undefined}
        >
          <span className={styles.bar} style={{ inlineSize: `${share * 100}%` }} />
        </div>
      </section>
    </div>,
    document.body,
  );
}
