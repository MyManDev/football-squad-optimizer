/**
 * A waiting job, remembered for the tab: a reload picks the wait up where it was.
 *
 * A five-week plan takes minutes, and a member who reloads in the middle should not start
 * a second wait from zero or lose sight of the first. The job id is kept in
 * `sessionStorage` under the question it answers, so it lives as long as the tab and is
 * never read for another member, strategy, window, rival, switch or gameweek. It is
 * dropped the moment the job is terminal or its patience has run out. Storage that is
 * missing, full or forbidden only means there is nothing to resume.
 */

import type { AdviceRequest } from "./adviceClient";

const PREFIX = "squadopt.advice-job:";
const JOB_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export interface StoredAdviceJob {
  jobId: string;
  /** When the wait began, in epoch milliseconds: patience is counted from here. */
  startedAt: number;
}

/** The question a request asks, as one string: every field that changes the answer. */
export function adviceRequestKey(request: AdviceRequest): string {
  return [
    request.leagueId,
    request.entryId,
    request.strategy,
    request.window,
    request.rivalEntryId ?? "",
    request.top100Weight ?? 0,
    request.managersWord === true ? "word" : "",
    request.season ?? "",
    request.gameweek ?? "",
  ].join(":");
}

function storage(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

export function rememberJob(request: AdviceRequest, job: StoredAdviceJob): void {
  try {
    storage()?.setItem(PREFIX + adviceRequestKey(request), JSON.stringify(job));
  } catch {
    // Nothing to resume after a reload; the wait itself is unaffected.
  }
}

export function recallJob(request: AdviceRequest): StoredAdviceJob | null {
  try {
    const raw = storage()?.getItem(PREFIX + adviceRequestKey(request));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredAdviceJob> | null;
    if (
      !value ||
      typeof value.jobId !== "string" ||
      !JOB_ID.test(value.jobId) ||
      typeof value.startedAt !== "number" ||
      !Number.isFinite(value.startedAt)
    ) {
      return null;
    }
    return { jobId: value.jobId, startedAt: value.startedAt };
  } catch {
    return null;
  }
}

export function forgetJob(request: AdviceRequest): void {
  try {
    storage()?.removeItem(PREFIX + adviceRequestKey(request));
  } catch {
    // Already gone, as far as this page can tell.
  }
}
