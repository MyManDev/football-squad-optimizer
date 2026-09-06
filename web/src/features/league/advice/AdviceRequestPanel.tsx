/**
 * Hesapla: the member's button, and every state it can land in.
 *
 * The selection (strategy, window) comes from the URL the controls and templates
 * already share; the rival comes from the league's own member list, never typed in;
 * the viewer's claim says whose squad the computation starts from. Every state is a
 * sentence the member can act on — queued, running with the published answer
 * showing, done with the capture identity beside it, honestly unavailable when only
 * the static site is there.
 *
 * The job itself belongs to the page: the panel asks for a computation and reports its
 * state, and the page hands the finished answer to the advice card beside it.
 */

import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { useViewerEntry } from "../identity/useViewerEntry";
import type { EntryView } from "../types";
import { rivalCandidates, selectedAdviceRequest } from "./adviceSelection";
import type { AdviceJob } from "./useAdviceJob";
import styles from "./AdviceRequestPanel.module.css";

export function AdviceRequestPanel({
  leagueId,
  entryId,
  members,
  job,
}: {
  leagueId: number;
  entryId: number;
  members: EntryView[];
  job: AdviceJob;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { viewer } = useViewerEntry();
  const [searchParams, setSearchParams] = useSearchParams();
  const { state, compute } = job;

  const request = selectedAdviceRequest(searchParams, leagueId, entryId, members);
  const candidates = rivalCandidates(members, entryId);
  const isSelf = viewer !== null && viewer.entryId === entryId;

  function setRival(value: string): void {
    const next = new URLSearchParams(searchParams);
    if (value === "") next.delete("rival");
    else next.set("rival", value);
    setSearchParams(next);
  }

  return (
    <Card tone="muted" title={copy.computeTitle}>
      <p className={styles.hint}>{isSelf ? copy.computeBodySelf : copy.computeBodyOther}</p>
      <div className={styles.controls}>
        <label className={styles.rivalLabel}>
          {copy.computeRival}
          <select
            className={styles.rivalSelect}
            value={request.rivalEntryId === null ? "" : String(request.rivalEntryId)}
            onChange={(event) => setRival(event.target.value)}
          >
            <option value="">{copy.computeRivalNearest}</option>
            {candidates.map((member) => (
              <option key={member.entry_id ?? 0} value={String(member.entry_id)}>
                {member.manager_name ?? `#${member.entry_id}`}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={styles.compute}
          disabled={state.phase === "requesting" || state.phase === "waiting"}
          onClick={() => compute(request)}
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
          <Badge tone="good">{copy.computeDone}</Badge>{" "}
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
