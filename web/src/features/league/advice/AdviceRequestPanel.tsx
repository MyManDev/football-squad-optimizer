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
 */

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
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
  published = true,
  chipChosen = false,
}: {
  request: AdviceRequest;
  job: AdviceJob;
  selectionAvailable?: boolean;
  service?: ComputeService;
  /** With a ready service: whether it can answer this exact selection now. */
  computable?: boolean;
  /** With a ready service: whether the published tree already answers this selection. */
  published?: boolean;
  /** A chosen chip is shown from the published tree only; the service computes none yet. */
  chipChosen?: boolean;
}) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const computeCopy = COMPUTE_COPY[language];
  const { viewer } = useViewerEntry();
  const { state, compute } = job;
  const isSelf = viewer !== null && viewer.entryId === request.entryId;
  const supported =
    service === "ready"
      ? computable
      : service !== "other-capture" && selectionAvailable && canComputeAdvice(request);

  return (
    <Card tone="muted" title={copy.computeTitle}>
      <p className={styles.hint}>{isSelf ? copy.computeBodySelf : copy.computeBodyOther}</p>
      {!supported && service !== "other-capture" ? (
        <p role="note">
          {service !== "ready"
            ? copy.computeUnsupportedSelection
            : chipChosen
              ? computeCopy.chipNotComputed
              : computeCopy.notComputable}
        </p>
      ) : null}
      {service === "unreachable" ? <p role="note">{computeCopy.serviceUnreachable}</p> : null}
      {service === "other-capture" ? <p role="note">{computeCopy.otherCapture}</p> : null}
      {service === "ready" && supported ? (
        <p role="note">
          {published ? null : <>{computeCopy.notPrecomputed} </>}
          {computeCopy.duration[request.window]} {computeCopy.durationNote}
        </p>
      ) : null}
      <div className={styles.controls}>
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
      </div>

      {state.phase === "requesting" ? (
        <p className={styles.state}>{copy.computeRequesting}</p>
      ) : null}
      {state.phase === "waiting" ? (
        <div className={styles.state}>
          <Badge tone="accent">
            {state.status === "queued" ? copy.computeQueued : copy.computeRunning}
          </Badge>{" "}
          {state.fallback !== null ? copy.computeWaitingWithFallback : copy.computeWaiting}
          <p className={styles.hint}>{computeCopy.leaveOpen}</p>
        </div>
      ) : null}
      {state.phase === "done" ? (
        <div className={styles.state}>
          <Badge tone={state.source === "api-cache" ? "good" : "accent"}>
            {state.source === "api-cache" ? copy.computeDone : copy.computePublished}
          </Badge>{" "}
          {copy.computeProvenance(
            String(state.envelope.payload.source_snapshot_id ?? "—"),
            state.envelope.generated_at_utc,
          )}
          {state.source === "static-fallback" ? <> {copy.computeStaticFallback}</> : null}
        </div>
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
    </Card>
  );
}
