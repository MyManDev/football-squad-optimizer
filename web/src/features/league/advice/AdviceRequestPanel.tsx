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
 * Beside it, where the publisher wrote the member's inputs, a second button asks the
 * member's own device for the plain one-week plan (`device`); its states are the same
 * kind of sentence, and the two buttons wait for each other, one answer at a time.
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
import { local } from "../../../lib/format";
import { useViewerEntry } from "../identity/useViewerEntry";
import type { AdviceRequest } from "./adviceClient";
import { canComputeAdvice } from "./adviceSelection";
import { COMPUTE_COPY, failureSentence } from "./computeCopy";
import { deviceEndedWithoutPlan, type DevicePlan } from "../device/useDevicePlan";
import type { AdviceJob, EarlierAnswer } from "./useAdviceJob";
import styles from "./AdviceRequestPanel.module.css";

/**
 * Where the page stands with the compute service: none configured (`static`, today's
 * site), answering with capabilities that fit this page (`ready`), configured but not
 * answering (`unreachable`), or answering from another data capture (`other-capture`).
 */
export type ComputeService = "static" | "ready" | "unreachable" | "other-capture";

/** What stays on the page after an attempt: the earlier answer when one is kept. */
function kept(earlier: EarlierAnswer | null | undefined): "published" | "earlier" {
  return earlier ? "earlier" : "published";
}

/** Where the device solve stands; nothing while nothing was asked of it. */
function DeviceState({ state }: { state: DevicePlan["state"] }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  if (state.phase === "idle") return null;
  const text =
    state.phase === "loading"
      ? copy.deviceLoading
      : state.phase === "solving"
        ? copy.deviceSolving
        : state.phase === "done"
          ? copy.deviceDone(
              new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(state.seconds),
            )
          : state.phase === "refused"
            ? copy.deviceRefused
            : state.phase === "other-capture"
              ? copy.deviceOtherCapture
              : state.phase === "unpublished"
                ? copy.deviceUnpublished
                : copy.deviceFailed;
  return (
    <p className={styles.state} data-device-state={state.phase}>
      {state.phase === "done" ? <Badge tone="good">{copy.computeDone}</Badge> : null}
      {state.phase === "done" ? " " : null}
      {text}
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
  deadlinePassed = false,
  dockClassName,
  device,
}: {
  request: AdviceRequest;
  job: AdviceJob;
  /** A solve on the member's own device, offered where the publisher wrote its inputs. */
  device?: DevicePlan;
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
   * A sentence about what Compute supports or what was published would be wrong a moment
   * later, so the notes wait.
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
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const computeCopy = COMPUTE_COPY[language];
  const { viewer } = useViewerEntry(request.leagueId);
  const { state, compute } = job;
  const isSelf = viewer !== null && viewer.entryId === request.entryId;
  const supported =
    !deadlinePassed &&
    (service === "ready"
      ? computable
      : service !== "other-capture" && selectionAvailable && canComputeAdvice(request));
  // The member's device solves this selection: no note calls it unsupported, and until it
  // has run the notes offer it rather than send the member to a published option. Once it
  // has answered there is nothing to add; after a run that ended without a plan the notes
  // say what they would say without it, beside the device's own sentence.
  const deviceOffered = device?.available === true && !deadlinePassed;
  const deviceAnswered = deviceOffered && device.state.phase === "done";
  const deviceStillOffered = deviceOffered && !deviceEndedWithoutPlan(device.state);
  const unreachableNote =
    published === true
      ? computeCopy.serviceUnreachablePublished
      : published === false
        ? deviceAnswered
          ? null
          : deviceStillOffered
            ? computeCopy.serviceUnreachableDevice
            : computeCopy.serviceUnreachableAbsent
        : computeCopy.serviceUnreachable;

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

        {device?.available && !deadlinePassed ? (
          <button
            type="button"
            className={styles.compute}
            data-device-compute
            disabled={
              device.state.phase === "loading" ||
              device.state.phase === "solving" ||
              state.phase === "requesting" ||
              state.phase === "waiting"
            }
            onClick={device.run}
          >
            {copy.deviceButton}
          </button>
        ) : null}
        {device?.available ? <DeviceState state={device.state} /> : null}

        {state.phase === "requesting" ? (
          <p className={styles.state}>{copy.computeRequesting}</p>
        ) : null}
        {state.phase === "waiting" ? (
          <p className={styles.state}>
            <Badge tone="accent">
              {state.status === "queued" ? copy.computeQueued : copy.computeRunning}
            </Badge>{" "}
            {state.earlier
              ? computeCopy.waitingWithEarlier
              : state.fallback !== null
                ? copy.computeWaitingWithFallback
                : copy.computeWaiting}
          </p>
        ) : null}
        {state.phase === "done" ? (
          <p className={styles.state}>
            <Badge tone={state.source === "api-cache" ? "good" : "accent"}>
              {state.source === "api-cache" ? copy.computeDone : copy.computePublished}
            </Badge>{" "}
            {copy.computeProvenance(
              String(state.envelope.payload.source_snapshot_id ?? "—"),
              local(state.envelope.generated_at_utc, locale),
            )}
            {state.source === "static-fallback" ? <> {copy.computeStaticFallback}</> : null}
          </p>
        ) : null}
        {state.phase === "unavailable" ? (
          <p className={styles.state}>
            {state.reason == null
              ? state.earlier
                ? `${copy.computeUnavailable} ${computeCopy.earlierRemains}`
                : copy.computeUnavailable
              : failureSentence(computeCopy, state.reason, null, kept(state.earlier))}
          </p>
        ) : null}
        {state.phase === "failed" ? (
          <p className={styles.state}>
            {state.reason == null && !state.earlier
              ? copy.computeFailed
              : failureSentence(
                  computeCopy,
                  state.reason,
                  state.retryAfterSeconds,
                  kept(state.earlier),
                )}
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
        {!deadlinePassed &&
        !supported &&
        !pending &&
        !deviceOffered &&
        service !== "other-capture" ? (
          <p role="note" className={styles.note}>
            {service !== "ready"
              ? copy.computeUnsupportedSelection
              : chipChosen
                ? computeCopy.chipUnavailable
                : computeCopy.notComputable}
          </p>
        ) : null}
        {!deadlinePassed && !pending && service === "unreachable" && unreachableNote !== null ? (
          <p role="note" className={styles.note}>
            {unreachableNote}
          </p>
        ) : null}
        {!deadlinePassed && service === "other-capture" ? (
          <p role="note" className={styles.note}>
            {computeCopy.otherCapture}
          </p>
        ) : null}
        {service === "ready" && supported && (published === false || !chipChosen) ? (
          <p role="note" className={styles.note}>
            {published === false ? computeCopy.notPrecomputed : null}
            {published === false && !chipChosen ? " " : null}
            {chipChosen ? null : (
              <>
                {computeCopy.duration[request.window]} {computeCopy.durationNote}
              </>
            )}
          </p>
        ) : null}
        {isSelf ? <p className={styles.note}>{copy.computeBodySelf}</p> : null}
      </div>
    </>
  );
}
