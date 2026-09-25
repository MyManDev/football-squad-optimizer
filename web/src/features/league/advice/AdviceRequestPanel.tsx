/**
 * Hesapla: the member's button, and every state it can land in.
 *
 * The request comes from the page's shared selection and squad context;
 * the viewer's claim says whose squad the computation starts from. Every state is a
 * sentence the member can act on — queued, running with the published answer
 * showing, done with the capture identity beside it, honestly unavailable when only
 * the static site is there.
 *
 * The job itself belongs to the page: the panel asks for a computation and reports its
 * state, and the page hands the finished answer to the advice card beside it.
 *
 * A build with no compute service renders exactly what it always has. With one, the page
 * passes `service`: what may be computed is then the capabilities' word (`computable`),
 * a selection nobody published says so and offers the computation with about how long it
 * takes, and a service that is down leaves a short notice and the published plans.
 *
 * It is drawn compact, for the sidebar under the plan: the button first, then the state
 * of the request, then the notes that say why the button is off or how long it takes, and
 * last whose squad the computation starts from. The button and the state are one block
 * (`data-compute-dock`), the notes a second one after it, so the page can pin the first to
 * the bottom of the phone drawer while the notes stay in the drawer's flow: the pinned
 * block is the button and what happened to the request, never a paragraph of caveats.
 */

import { Badge } from "../../../design/components/Badge";
import { useLanguage } from "../../../i18n/context";
import { useViewerEntry } from "../identity/useViewerEntry";
import type { AdviceRequest } from "./adviceClient";
import { canComputeAdvice } from "./adviceSelection";
import { COMPUTE_COPY, failureSentence } from "./computeCopy";
import type { AdviceJob } from "./useAdviceJob";
import styles from "./AdviceRequestPanel.module.css";

/**
 * Where the page stands with the compute service: none configured (`static`, today's
 * site), answering with capabilities that fit this page (`ready`), configured but not
 * answering (`unreachable`), or answering from another data capture (`other-capture`).
 */
export type ComputeService = "static" | "ready" | "unreachable" | "other-capture";

export function AdviceRequestPanel({
  request,
  job,
  selectionAvailable = true,
  service = "static",
  computable = false,
  published,
  chipChosen = false,
  pending = false,
  deadlinePassed = false,
  dockClassName,
}: {
  request: AdviceRequest;
  job: AdviceJob;
  selectionAvailable?: boolean;
  service?: ComputeService;
  /** With a ready service: whether it can answer this exact selection now. */
  computable?: boolean;
  /** Whether a readable published plan answers this selection; undefined is unconfirmed. */
  published?: boolean;
  /** A chip computation has no measured duration to display. */
  chipChosen?: boolean;
  /**
   * A service is configured and has not said yet what it computes. The static build's
   * sentence about what Compute supports would be wrong a moment later, so it waits.
   */
  pending?: boolean;
  /**
   * The gameweek's deadline has passed. A plan for a closed week cannot be applied, so
   * nothing is asked of the service and the panel says why; the page explains above it.
   */
  deadlinePassed?: boolean;
  /** The page's class for the button's block, which it may pin in a drawer. */
  dockClassName?: string;
}) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const computeCopy = COMPUTE_COPY[language];
  const { viewer } = useViewerEntry();
  const { state, compute } = job;
  const isSelf = viewer !== null && viewer.entryId === request.entryId;
  const supported =
    !deadlinePassed &&
    (service === "ready"
      ? computable
      : service !== "other-capture" && selectionAvailable && canComputeAdvice(request));

  return (
    <>
      <div
        className={dockClassName ? `${styles.panel} ${dockClassName}` : styles.panel}
        data-compute-dock
      >
        <button
          type="button"
          className={styles.compute}
          disabled={!supported || state.phase === "requesting" || state.phase === "waiting"}
          onClick={() => {
            if (supported) compute(request);
          }}
        >
          {copy.computeButton}
        </button>

        {state.phase === "requesting" ? (
          <p className={styles.state}>{copy.computeRequesting}</p>
        ) : null}
        {state.phase === "waiting" ? (
          <p className={styles.state}>
            <Badge tone="accent">
              {state.status === "queued" ? copy.computeQueued : copy.computeRunning}
            </Badge>{" "}
            {state.fallback !== null ? copy.computeWaitingWithFallback : copy.computeWaiting}
          </p>
        ) : null}
        {state.phase === "done" ? (
          <p className={styles.state}>
            <Badge tone={state.source === "api-cache" ? "good" : "accent"}>
              {state.source === "api-cache" ? copy.computeDone : copy.computePublished}
            </Badge>{" "}
            {copy.computeProvenance(
              String(state.envelope.payload.source_snapshot_id ?? "—"),
              state.envelope.generated_at_utc,
            )}
            {state.source === "static-fallback" ? <> {copy.computeStaticFallback}</> : null}
          </p>
        ) : null}
        {state.phase === "unavailable" ? (
          <p className={styles.state}>
            {state.reason == null
              ? copy.computeUnavailable
              : failureSentence(computeCopy, state.reason)}
          </p>
        ) : null}
        {state.phase === "failed" ? (
          <p className={styles.state}>
            {state.reason == null
              ? copy.computeFailed
              : failureSentence(computeCopy, state.reason, state.retryAfterSeconds)}
          </p>
        ) : null}
      </div>

      <div className={styles.notes}>
        {state.phase === "waiting" ? <p className={styles.note}>{computeCopy.leaveOpen}</p> : null}
        {deadlinePassed ? (
          <p role="note" className={styles.note}>
            {computeCopy.deadlinePassedCompute}
          </p>
        ) : null}
        {!deadlinePassed && !supported && !pending && service !== "other-capture" ? (
          <p role="note" className={styles.note}>
            {service !== "ready"
              ? copy.computeUnsupportedSelection
              : chipChosen
                ? computeCopy.chipUnavailable
                : computeCopy.notComputable}
          </p>
        ) : null}
        {!deadlinePassed && service === "unreachable" ? (
          <p role="note" className={styles.note}>
            {published === true
              ? computeCopy.serviceUnreachablePublished
              : published === false
                ? computeCopy.serviceUnreachableAbsent
                : computeCopy.serviceUnreachable}
          </p>
        ) : null}
        {!deadlinePassed && service === "other-capture" ? (
          <p role="note" className={styles.note}>
            {computeCopy.otherCapture}
          </p>
        ) : null}
        {service === "ready" && supported ? (
          <p role="note" className={styles.note}>
            {published === false ? <>{computeCopy.notPrecomputed} </> : null}
            {chipChosen ? (
              computeCopy.chipDurationUnknown
            ) : (
              <>
                {computeCopy.duration[request.window]} {computeCopy.durationNote}
              </>
            )}
          </p>
        ) : null}
        <p className={styles.note}>{isSelf ? copy.computeBodySelf : copy.computeBodyOther}</p>
      </div>
    </>
  );
}
