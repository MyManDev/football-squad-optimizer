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
 */

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { useViewerEntry } from "../identity/useViewerEntry";
import type { AdviceRequest } from "./adviceClient";
import { canComputeAdvice } from "./adviceSelection";
import type { AdviceJob } from "./useAdviceJob";
import styles from "./AdviceRequestPanel.module.css";

export function AdviceRequestPanel({ request, job }: { request: AdviceRequest; job: AdviceJob }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { viewer } = useViewerEntry();
  const { state, compute } = job;
  const isSelf = viewer !== null && viewer.entryId === request.entryId;
  const supported = canComputeAdvice(request);

  return (
    <Card tone="muted" title={copy.computeTitle}>
      <p className={styles.hint}>{isSelf ? copy.computeBodySelf : copy.computeBodyOther}</p>
      {!supported ? <p role="note">{copy.computeUnsupportedSelection}</p> : null}
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
        <p className={styles.state}>{copy.computeUnavailable}</p>
      ) : null}
      {state.phase === "failed" ? <p className={styles.state}>{copy.computeFailed}</p> : null}
    </Card>
  );
}
