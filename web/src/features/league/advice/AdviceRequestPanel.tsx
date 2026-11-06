/**
 * Hesapla: the member's button, and every state it can land in.
 *
 * The request comes from the page's shared selection and squad context. Every state is a
 * short sentence the member can act on, or a mark that the plan is ready: queued, running,
 * done, failed. A job at the service also says how the wait is going: its place in line, how
 * much is solved as a percentage and a bar, and the workers at work, each only where the
 * service says it.
 *
 * The job itself belongs to the page: the panel asks for a computation and reports its
 * state, and the page hands the finished answer to the advice card beside it.
 *
 * Beside it, where the publisher wrote the member's inputs, a second button asks the
 * member's own device for the plain one-week plan (`device`); its states are the same
 * kind of sentence, its run's progress stands in the middle of the screen while it counts,
 * and the two buttons wait for each other, one answer at a time.
 *
 * A build with no compute service renders exactly what it always has. With one, the page
 * passes `service`: what may be computed is then the capabilities' word (`computable`), a
 * selection nobody published offers the computation with about how long it takes, and a
 * service that is down is mentioned only where the member's device can compute instead.
 *
 * It is drawn compact: the button first, then the state of the request, then the notes
 * that say how to reach the button or how long it takes. The button and the state are one
 * block (`data-compute-dock`), the notes a second one after it.
 */

import { useId, useRef } from "react";

import { Badge } from "../../../design/components/Badge";
import { useLanguage } from "../../../i18n/context";
import type { AdviceRequest } from "./adviceClient";
import { canComputeAdvice } from "./adviceSelection";
import { COMPUTE_COPY, failureSentence, jobStanding, jobWorkersLine } from "./computeCopy";
import { DeviceProgressPanel } from "../device/DeviceProgressPanel";
import { deviceEndedWithoutPlan, type DevicePlan } from "../device/useDevicePlan";
import type { AdviceJob, WaitingPhase } from "./useAdviceJob";
import styles from "./AdviceRequestPanel.module.css";

/**
 * Where the page stands with the compute service: none configured (`static`, today's
 * site), answering with capabilities that fit this page (`ready`), configured but not
 * answering (`unreachable`), or answering from another data capture (`other-capture`).
 */
export type ComputeService = "static" | "ready" | "unreachable" | "other-capture";

/**
 * A running job's stages as one bar, filled by what is solved. A solve
 * reports nothing until it ends and nothing here follows the clock, so the only thing that
 * moves is one pulse across the stage in hand, each time the service answers that the job is
 * still going. A job of one stage, or one that has not counted yet, is that stage alone.
 */
function JobStages({
  state,
  label,
  value,
}: {
  state: WaitingPhase;
  label: string;
  /** The share solved in words; null when there is nothing to count. */
  value: string | null;
}) {
  const done = state.progress?.done ?? 0;
  const total = state.progress?.total ?? 1;
  const share = (done / total) * 100;
  const counted = value !== null;
  return (
    <div
      className={styles.stages}
      role="progressbar"
      aria-label={label}
      aria-valuemin={counted ? 0 : undefined}
      aria-valuemax={counted ? 100 : undefined}
      aria-valuenow={counted ? Math.round(share) : undefined}
      aria-valuetext={value ?? undefined}
    >
      <span className={styles.stagesDone} style={{ inlineSize: `${share}%` }} />
      {done < total ? (
        <span
          key={state.answers ?? 0}
          className={styles.stageNow}
          data-stage-now
          style={{ inlineSize: `${100 / total}%` }}
        />
      ) : null}
    </div>
  );
}

/** Where a job at the service stands: its word, then what the service says about the wait. */
function JobState({ state }: { state: WaitingPhase }) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const computeCopy = COMPUTE_COPY[language];
  // A wait picked up after a reload names no word until the service has said one.
  if (state.status === null) return null;
  const running = state.status === "running";
  const word = running ? copy.computeRunning : copy.computeQueued;
  const standing = jobStanding(computeCopy, state);
  const workers = jobWorkersLine(computeCopy, state);
  return (
    <>
      <p className={styles.state}>
        <Badge tone="accent">{word}</Badge>{" "}
        {/* While it runs the bar says the percentage to a screen reader. */}
        {standing === null ? null : <span aria-hidden={running || undefined}>{standing}</span>}
      </p>
      {running ? <JobStages state={state} label={word} value={standing} /> : null}
      {workers === null ? null : <p className={styles.note}>{workers}</p>}
    </>
  );
}

/** Where the device solve stands; nothing while nothing was asked of it. */
function DeviceState({ id, state }: { id: string; state: DevicePlan["state"] }) {
  const copy = useLanguage().messages.leagueMembers;
  if (state.phase === "idle") return null;
  return (
    <p id={id} className={styles.state} role="status" data-device-state={state.phase}>
      {state.phase === "loading" || state.phase === "solving" ? (
        copy.deviceSolving
      ) : state.phase === "done" ? (
        <Badge tone="good">{copy.computeDone}</Badge>
      ) : state.phase === "refused" ? (
        copy.deviceRefused
      ) : (
        copy.deviceFailed
      )}
    </p>
  );
}

export function AdviceRequestPanel({
  request,
  job,
  selectionAvailable = true,
  service = "static",
  computable = false,
  published,
  chipChosen = false,
  pending = false,
  dockClassName,
  device,
  compact = false,
  serverLabel,
  disabled = false,
}: {
  request: AdviceRequest;
  job: AdviceJob;
  /** A solve on the member's own device, offered where the publisher wrote its inputs. */
  device?: DevicePlan;
  compact?: boolean;
  serverLabel?: string;
  /** Keep the controls visible when the page's gameweek is closed. */
  disabled?: boolean;
  selectionAvailable?: boolean;
  service?: ComputeService;
  /** With a ready service: whether it can answer this exact selection now. */
  computable?: boolean;
  /** Whether a readable published plan answers this selection; undefined is unconfirmed. */
  published?: boolean;
  /** A chip computation has no measured duration to display. */
  chipChosen?: boolean;
  /**
   * The page has not learned yet what can be computed here: a configured service has not
   * said what it computes, or the rivals' documents the device needs are still being read.
   * A sentence about what Compute can do would be wrong a moment later, so it waits.
   */
  pending?: boolean;
  /** The page's class for the button's block. */
  dockClassName?: string;
}) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const computeCopy = COMPUTE_COPY[language];
  const { state, compute } = job;
  const deviceButton = useRef<HTMLButtonElement>(null);
  const deviceStateId = useId();
  const supported =
    service === "ready"
      ? computable
      : service !== "other-capture" && selectionAvailable && canComputeAdvice(request);
  // The member's device solves this selection: until it has run the notes offer it, and no
  // note sends the member to change the selection. Once it has answered there is nothing to
  // add, and a run that ended without a plan is no longer an offer.
  const deviceOffered = device?.available === true;
  const deviceStillOffered =
    deviceOffered && device.state.phase !== "done" && !deviceEndedWithoutPlan(device.state);
  // At most one of these holds: what a ready or a silent service leaves.
  const note =
    service === "ready"
      ? supported
        ? [
            // An invitation to press: nothing while a press is being answered or has been.
            published === false && (state.phase === "idle" || state.phase === "failed")
              ? computeCopy.notPrecomputed
              : null,
            chipChosen ? null : computeCopy.duration[request.window],
          ]
            .filter(Boolean)
            .join(" ") || null
        : !pending && !deviceOffered && !chipChosen
          ? computeCopy.notComputable
          : null
      : service === "unreachable" && !pending && published === false && deviceStillOffered
        ? computeCopy.serviceUnreachableDevice
        : null;

  return (
    <>
      <div
        className={dockClassName ? `${styles.panel} ${dockClassName}` : styles.panel}
        data-compute-dock
      >
        <button
          type="button"
          className={styles.compute}
          disabled={
            disabled ||
            !supported ||
            state.phase === "requesting" ||
            state.phase === "waiting" ||
            device?.state.phase === "loading" ||
            device?.state.phase === "solving"
          }
          onClick={() => {
            if (!disabled && supported) compute(request);
          }}
        >
          {serverLabel ?? copy.computeButton}
        </button>

        {device?.available ? (
          <button
            ref={deviceButton}
            type="button"
            className={styles.compute}
            data-device-compute
            // The page behind the run's cover is inert, so its state line changes unheard: the
            // button says how the run ended as it takes focus back.
            aria-describedby={disabled || device.state.phase === "idle" ? undefined : deviceStateId}
            disabled={
              disabled ||
              device.state.phase === "loading" ||
              device.state.phase === "solving" ||
              state.phase === "requesting" ||
              state.phase === "waiting"
            }
            onClick={() => {
              if (!disabled) device.run();
            }}
          >
            {copy.deviceButton}
          </button>
        ) : null}
        {device?.available && !disabled ? (
          <DeviceState id={deviceStateId} state={device.state} />
        ) : null}
        {device?.available && !disabled ? (
          <DeviceProgressPanel state={device.state} returnFocus={deviceButton} />
        ) : null}

        {state.phase === "requesting" ? (
          <p className={styles.state}>{copy.computeRequesting}</p>
        ) : null}
        {state.phase === "waiting" ? <JobState state={state} /> : null}
        {state.phase === "done" && state.source !== "static-fallback" ? (
          <p className={styles.state}>
            <Badge tone="good">{copy.computeDone}</Badge>
          </p>
        ) : null}
        {state.phase === "done" && state.source === "static-fallback" ? (
          <p className={styles.state}>{copy.computeStaticFallback}</p>
        ) : null}
        {state.phase === "unavailable" && state.reason != null ? (
          <p className={styles.state}>{failureSentence(computeCopy, state.reason)}</p>
        ) : null}
        {state.phase === "failed" ? (
          <p className={styles.state}>
            {state.reason == null
              ? copy.computeFailed
              : failureSentence(computeCopy, state.reason, state.retryAfterSeconds)}
          </p>
        ) : null}
      </div>

      {!disabled && !compact && (state.phase === "waiting" || note !== null) ? (
        <div className={styles.notes}>
          {state.phase === "waiting" ? (
            <p className={styles.note}>{computeCopy.leaveOpen}</p>
          ) : null}
          {note !== null ? (
            <p role="note" className={styles.note}>
              {note}
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
