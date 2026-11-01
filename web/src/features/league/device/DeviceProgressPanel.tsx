/**
 * The device solve at work, in the middle of the screen: how many of the run's stages are done
 * and the stages themselves, each ticked as the run passes it (the inputs read, the solver
 * loaded, the plan solved, then each held chip tried). The count is of those stages, never of
 * elapsed time, so it moves in steps: one solve reports nothing until it ends. It is written
 * as a count ("2/7"), never as a percentage, because member pages carry no percentages.
 *
 * It covers the whole screen with the page's background, so nothing of the page shows
 * while the run counts. It is drawn into the document's body, so a closed drawer or a
 * sticky sidebar does not hide it, and it goes as soon as nothing is counting.
 */

import { createPortal } from "react-dom";

import { useLanguage } from "../../../i18n/context";
import { countingProgress, progressShare } from "./progress";
import type { DevicePlanPhase } from "./useDevicePlan";
import styles from "./DeviceProgressPanel.module.css";

type Stage = "inputs" | "solver" | "plan" | "chips";
const ORDER: readonly Stage[] = ["inputs", "solver", "plan", "chips"];

export function DeviceProgressPanel({ state }: { state: DevicePlanPhase }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const progress = countingProgress(state);
  if (progress === null || typeof document === "undefined") return null;

  const share = progressShare(progress);
  // Before the inputs say how many stages there are, there is nothing to count yet.
  const count = progress.total === null ? null : `${progress.done}/${progress.total}`;
  const chipTotal = progress.chips?.total ?? null;
  // The chips are a stage only where the run tries some; before the inputs say, they wait.
  const stages = ORDER.filter((stage) => stage !== "chips" || (chipTotal ?? 0) > 0);
  const current = ORDER.indexOf(progress.step);
  const label = (stage: Stage) =>
    stage === "chips"
      ? copy.deviceSteps.chips(progress.chips?.done ?? 0, chipTotal ?? 0)
      : copy.deviceSteps[stage];

  return createPortal(
    <div className={styles.layer} data-device-progress={progress.step}>
      <section className={styles.panel} aria-labelledby="device-progress-title">
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
          aria-valuetext={
            count === null ? label(progress.step) : `${count}, ${label(progress.step)}`
          }
        >
          <span className={styles.bar} style={{ inlineSize: `${share * 100}%` }} />
        </div>
        <ol className={styles.stages}>
          {stages.map((stage) => {
            const index = ORDER.indexOf(stage);
            const mark = index < current ? "done" : index === current ? "current" : "waiting";
            return (
              <li key={stage} className={styles.stage} data-stage={mark}>
                <span className={styles.tick} aria-hidden="true" />
                <span aria-current={mark === "current" ? "step" : undefined}>{label(stage)}</span>
              </li>
            );
          })}
        </ol>
      </section>
    </div>,
    document.body,
  );
}
