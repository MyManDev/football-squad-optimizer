/**
 * The compute flow as a state machine: request, wait with the published answer
 * showing, land on the computed one.
 *
 * While the backend works, the member is not staring at a spinner: the previously
 * published saf-puan/1 baseline is fetched and shown as the fallback — the plan's
 * "beklerken önceden yayınlanmış cevap gösterilir". Every terminal state is explicit,
 * and "the backend cannot help" degrades to whatever the static tree can show,
 * never to an error page.
 *
 * Every phase after idle carries the request it answers, so a page can tell a result
 * that belongs to the selection on screen from one left behind by an earlier selection.
 *
 * Patience follows the window asked for, the wait is polled less often after its first
 * minute, a failure keeps the service's coded reason so the panel can say what happened,
 * and the job id is remembered for the tab so a reload resumes the wait. While it waits, the
 * state carries how the wait is going, each part as the service last said it.
 */

import { cancellableDelay, isTimeoutError, withRequestDeadline } from "../../../data/request";
import { useCallback, useEffect, useRef, useState } from "react";

import type { WindowSize } from "../../../lib/decisionVocabulary";
import type {
  AdviceClient,
  AdviceJobProgress,
  AdviceJobWorkers,
  AdviceRequest,
  AdviceSource,
} from "./adviceClient";
import { AdviceApiError, newIdempotencyKey } from "./adviceClient";
import {
  adviceRequestKey,
  forgetJob,
  recallJob,
  rememberJob,
  type StoredAdviceJob,
} from "./adviceJobStore";
import { AdviceContextError, AdviceResponseError, checkedAdvice } from "./adviceResponse";
import type { PlanInfeasibility } from "./planInfeasibility";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";

const POLL_INTERVAL_MS = 2000;
// A long solve is asked about less often once its first minute has passed.
const SLOW_POLL_INTERVAL_MS = 5000;
const SLOW_POLL_AFTER_MS = 60_000;
/**
 * A poll the service refused for now (too many asks, or not available this moment) is not
 * the job's end: the wait backs off and keeps the job. Anything the service said it no
 * longer knows, 404 or 410, still ends it.
 */
const TEMPORARY_REFUSALS = new Set([408, 425, 429, 503]);
/** The longest one refused poll waits, whatever the service's `Retry-After` asks. */
export const REFUSAL_PAUSE_CEILING_MS = 60_000;

function pollInterval(startedAt: number, now: number): number {
  return now - startedAt < SLOW_POLL_AFTER_MS ? POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS;
}

/**
 * How long to wait after the `refusals`-th refusal in a row: what `Retry-After` asked, but
 * never less than the ordinary interval; without one, the interval doubled per refusal.
 */
function refusalPause(retryAfterSeconds: number | null, interval: number, refusals: number) {
  const asked =
    retryAfterSeconds === null
      ? interval * 2 ** refusals
      : Math.max(retryAfterSeconds * 1000, interval);
  return Math.min(asked, REFUSAL_PAUSE_CEILING_MS);
}
/** How long the solver has after this client first sees it running, per window. */
export const PATIENCE_MS: Record<WindowSize, number> = { 1: 180_000, 3: 360_000, 5: 600_000 };
export const QUEUE_PATIENCE_MS = 15 * 60_000;
// Bound each network read or write, including custom clients that ignore cancellation.
const REQUEST_ALLOWANCE_MS = 30_000;

function waitDeadline(job: StoredAdviceJob, window: WindowSize): number {
  return job.runningSince === undefined
    ? job.startedAt + QUEUE_PATIENCE_MS
    : job.runningSince + (PATIENCE_MS[window] ?? PATIENCE_MS[1]);
}

/** The page's own reasons for a failure, beside the service's codes. */
export const PATIENCE_EXHAUSTED = "PATIENCE_EXHAUSTED";
export const ANSWER_UNREADABLE = "ANSWER_UNREADABLE";
export const ANSWER_MISMATCH = "ANSWER_MISMATCH";
export const ANSWER_OTHER_CAPTURE = "ANSWER_OTHER_CAPTURE";

/**
 * The answer a selection already received, carried by a later attempt for that same
 * selection while it runs and after it fails or is refused. Pressing Compute again replaces
 * the state with the new attempt, and an attempt with no answer of its own would otherwise
 * take the plan off the page because a second request did not succeed.
 */
export interface EarlierAnswer {
  envelope: LeagueViewEnvelope<EntryAdvice>;
  source: AdviceSource;
}

export interface WaitingPhase {
  phase: "waiting";
  request: AdviceRequest;
  jobId: string;
  /** Where the job stands, as the service said it; null until it has, after a reload. */
  status: "queued" | "running" | null;
  fallback: LeagueViewEnvelope<EntryAdvice> | null;
  earlier?: EarlierAnswer | null;
  /** The job's place in line while it is queued; absent until the service says it. */
  queuePosition?: number;
  /** The documents solved while it runs; absent until the service says it. */
  progress?: AdviceJobProgress;
  /** The workers at work; absent until the service says it. */
  workers?: AdviceJobWorkers;
  /** How many times the service has answered this wait, so the page can mark each answer. */
  answers?: number;
}

export type ComputePhase =
  | { phase: "idle" }
  | { phase: "requesting"; request: AdviceRequest; earlier?: EarlierAnswer | null }
  | WaitingPhase
  | {
      phase: "done";
      request: AdviceRequest;
      envelope: LeagueViewEnvelope<EntryAdvice>;
      source: AdviceSource;
    }
  | {
      phase: "unavailable";
      request: AdviceRequest;
      reason?: string | null;
      earlier?: EarlierAnswer | null;
    }
  | {
      phase: "failed";
      request: AdviceRequest;
      /** A service code or one of the page's own; the panel turns it into a sentence. */
      reason?: string | null;
      retryAfterSeconds?: number | null;
      infeasibility?: PlanInfeasibility;
      terminalJobId?: string;
      earlier?: EarlierAnswer | null;
    };

export interface AdviceJob {
  state: ComputePhase;
  compute: (request: AdviceRequest) => void;
  /** Pick up a wait this tab began before a reload; false when there is none to pick up. */
  resume?: (request: AdviceRequest) => boolean;
  /** Read once without starting a job; an absent, stale or unreadable answer stays silent. */
  readCached?: (request: AdviceRequest) => void;
  reset: () => void;
}

/** Whether two requests ask the same question: same member, strategy, window, rival and switches. */
export function sameAdviceRequest(left: AdviceRequest, right: AdviceRequest): boolean {
  return (
    adviceRequestKey(left) === adviceRequestKey(right) &&
    left.run?.run_id === right.run?.run_id &&
    left.run?.stage === right.run?.stage &&
    (left.deviceAlternatives ?? false) === (right.deviceAlternatives ?? false) &&
    (left.deviceRun ?? false) === (right.deviceRun ?? false) &&
    left.leagueId === right.leagueId &&
    left.entryId === right.entryId &&
    left.strategy === right.strategy &&
    left.window === right.window &&
    left.season === right.season &&
    left.gameweek === right.gameweek &&
    (left.rivalEntryId ?? null) === (right.rivalEntryId ?? null) &&
    (left.top100Weight ?? 0) === (right.top100Weight ?? 0) &&
    (left.managersWord ?? false) === (right.managersWord ?? false) &&
    (left.chip ?? null) === (right.chip ?? null) &&
    (left.model ?? "current") === (right.model ?? "current")
  );
}

/**
 * The next state of an attempt, carrying the answer the same selection already had.
 *
 * A finished state is its own answer and an idle one has no selection. Any other state
 * keeps the answer of the state it replaces, when that state was for the same request.
 */
function carrying(previous: ComputePhase, next: ComputePhase): ComputePhase {
  if (next.phase === "idle" || next.phase === "done" || previous.phase === "idle") return next;
  if (!sameAdviceRequest(previous.request, next.request)) return next;
  const earlier =
    previous.phase === "done"
      ? { envelope: previous.envelope, source: previous.source }
      : (previous.earlier ?? null);
  return earlier ? { ...next, earlier } : next;
}

function failure(error: unknown): { reason: string | null; retryAfterSeconds: number | null } {
  if (error instanceof AdviceApiError) {
    return { reason: error.code, retryAfterSeconds: error.retryAfterSeconds };
  }
  if (error instanceof AdviceContextError)
    return { reason: ANSWER_MISMATCH, retryAfterSeconds: null };
  if (error instanceof AdviceResponseError) {
    return { reason: ANSWER_UNREADABLE, retryAfterSeconds: null };
  }
  return { reason: null, retryAfterSeconds: null };
}

export function useAdviceJob(
  client: AdviceClient,
  allowPublishedBaseline = true,
  expectedSnapshotId?: string | null,
  requireMatchingSnapshot = false,
): AdviceJob {
  const [state, replaceState] = useState<ComputePhase>({ phase: "idle" });
  // Every transition goes through `carrying`, so no call site can drop the earlier answer.
  const setState = useCallback(
    (next: ComputePhase | ((previous: ComputePhase) => ComputePhase)) =>
      replaceState((previous) =>
        carrying(previous, typeof next === "function" ? next(previous) : next),
      ),
    [],
  );
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  // The request a Compute press is still being answered for. A second press for the same
  // selection, before the button has had a render to disable itself, is the same click.
  const submitting = useRef<AdviceRequest | null>(null);

  useEffect(() => {
    return () => {
      generation.current += 1;
      active.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    active.current?.abort();
    active.current = null;
    submitting.current = null;
    setState({ phase: "idle" });
  }, [setState]);

  const readCached = useCallback(
    (request: AdviceRequest) => {
      if (active.current) return;
      const run = ++generation.current;
      const controller = new AbortController();
      active.current = controller;
      void withRequestDeadline(
        async (signal) => {
          const read = await client.readAdvice(request, { signal, publishedFallback: false });
          if (read.kind !== "advice" || signal.aborted || generation.current !== run) return;
          checkedAdvice(read.envelope, request);
          const snapshot = read.envelope.payload.source_snapshot_id;
          if (
            expectedSnapshotId != null &&
            (snapshot != null || request.publicEntry || requireMatchingSnapshot) &&
            snapshot !== expectedSnapshotId
          )
            return;
          setState((prev) =>
            prev.phase === "idle"
              ? { phase: "done", request, envelope: read.envelope, source: read.source }
              : prev,
          );
        },
        { signal: controller.signal, timeoutMs: REQUEST_ALLOWANCE_MS },
      )
        .catch(() => {
          // A cache miss or failed read leaves the ordinary Compute panel in place.
        })
        .finally(() => {
          if (active.current === controller) active.current = null;
        });
    },
    [client, expectedSnapshotId, requireMatchingSnapshot, setState],
  );

  const start = useCallback(
    (request: AdviceRequest, resumed: StoredAdviceJob | null) => {
      const run = ++generation.current;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      const { signal } = controller;
      const call = <T>(
        operation: (signal: AbortSignal) => Promise<T>,
        timeoutMs = REQUEST_ALLOWANCE_MS,
      ) => withRequestDeadline(operation, { signal, timeoutMs });
      let readAfterMissingJob = false;
      const alive = () => generation.current === run && !signal.aborted;
      const fail = (
        error?: unknown,
        reason?: string,
        infeasibility?: PlanInfeasibility,
        terminalJobId?: string,
      ) => {
        if (!alive()) return;
        const stated = failure(error);
        setState({
          phase: "failed",
          request,
          ...stated,
          reason: reason ?? stated.reason,
          ...(infeasibility ? { infeasibility } : {}),
          ...(terminalJobId ? { terminalJobId } : {}),
        });
      };
      setState(
        resumed
          ? { phase: "waiting", request, jobId: resumed.jobId, status: null, fallback: null }
          : { phase: "requesting", request },
      );

      void (async () => {
        let waiting: StoredAdviceJob;
        let status: WaitingPhase["status"] = null;
        if (resumed) {
          waiting = resumed;
        } else {
          let outcome;
          try {
            // One key for this click, whatever the transport retries underneath it.
            outcome = await call(
              (signal) =>
                client.requestAdvice(request, { signal, idempotencyKey: newIdempotencyKey() }),
              client.localRequestAllowanceMs?.(request),
            );
            if (outcome.kind === "advice") checkedAdvice(outcome.envelope, request);
          } catch (error) {
            fail(error, isTimeoutError(error) ? PATIENCE_EXHAUSTED : undefined);
            return;
          }
          if (!alive()) return;
          if (outcome.kind === "advice") {
            if (
              (request.publicEntry || requireMatchingSnapshot) &&
              expectedSnapshotId != null &&
              outcome.envelope.payload.source_snapshot_id !== expectedSnapshotId
            ) {
              fail(undefined, ANSWER_OTHER_CAPTURE);
              return;
            }
            setState({
              phase: "done",
              request,
              envelope: outcome.envelope,
              source: outcome.source,
            });
            return;
          }
          if (outcome.kind === "unavailable") {
            if (outcome.infeasibility) {
              fail(undefined, outcome.reason ?? undefined, outcome.infeasibility);
              return;
            }
            setState({ phase: "unavailable", request, reason: outcome.reason ?? null });
            return;
          }
          status = outcome.status ?? "queued";
          const startedAt = Date.now();
          waiting = {
            jobId: outcome.jobId,
            startedAt,
            runningSince: status === "running" ? startedAt : undefined,
          };
          rememberJob(request, waiting);
        }
        const { jobId, startedAt } = waiting;

        // A job: fetch the published baseline once, show it while we wait.
        let fallback: LeagueViewEnvelope<EntryAdvice> | null = null;
        try {
          const published = allowPublishedBaseline
            ? await call((signal) =>
                client.readPublished(
                  {
                    ...request,
                    strategy: "saf-puan",
                    window: 1,
                    rivalEntryId: null,
                    top100Weight: undefined,
                    managersWord: undefined,
                    chip: undefined,
                  },
                  { signal },
                ),
              )
            : null;
          if (published?.kind === "advice") fallback = published.envelope;
        } catch {
          fallback = null; // the wait is just quieter
        }
        if (!alive()) return;
        setState({ phase: "waiting", request, jobId, status, fallback });

        // A wait picked up after a reload has heard nothing yet: its first question takes no
        // delay, and it is asked even if the baseline's read has used up the patience.
        let askNow = resumed !== null;
        let answers = 0;
        let attempt: number | undefined;
        let progress: AdviceJobProgress | undefined;
        // Refusals in a row, and the pause the last one asked for before the next poll.
        let refusals = 0;
        let pause: number | null = null;
        while (askNow || Date.now() < waitDeadline(waiting, request.window)) {
          if (!askNow) {
            const now = Date.now();
            await cancellableDelay(
              Math.min(
                pause ?? pollInterval(startedAt, now),
                waitDeadline(waiting, request.window) - now,
              ),
              signal,
            );
            pause = null;
            if (!alive()) return;
          }
          askNow = false;
          let job;
          try {
            job = await call((signal) => client.readJob(jobId, { signal }));
          } catch (error) {
            if (!alive()) return;
            if (error instanceof AdviceApiError && TEMPORARY_REFUSALS.has(error.status)) {
              // Refused for now, not forgotten: the job and its remembered record stay.
              refusals += 1;
              pause = refusalPause(
                error.retryAfterSeconds,
                pollInterval(startedAt, Date.now()),
                refusals,
              );
              continue;
            }
            if (
              error instanceof AdviceResponseError ||
              (error instanceof AdviceApiError && error.status >= 400 && error.status < 500)
            ) {
              forgetJob(request);
              // A remembered job the service no longer knows is not this visit's
              // failure: the page is simply back where a fresh visit starts.
              if (resumed && error instanceof AdviceApiError && error.status === 404) {
                setState({ phase: "idle" });
                readAfterMissingJob = true;
              } else {
                fail(error);
              }
              return;
            }
            continue; // one flaky poll is not a failed computation
          }
          if (!alive()) return;
          refusals = 0;
          if (job.status === "completed") {
            forgetJob(request);
            let read;
            try {
              read = await call((signal) => client.readAdvice(request, { signal }));
              if (read.kind === "advice") checkedAdvice(read.envelope, request);
            } catch (error) {
              // Completed but the answer cannot be read: an honest failure, not a wait
              // that never ends. A stale read from a superseded request changes nothing.
              fail(error, failure(error).reason ?? ANSWER_UNREADABLE);
              return;
            }
            if (!alive()) return;
            if (read.kind === "advice") {
              if (
                (request.publicEntry || requireMatchingSnapshot) &&
                expectedSnapshotId != null &&
                read.envelope.payload.source_snapshot_id !== expectedSnapshotId
              ) {
                fail(undefined, ANSWER_OTHER_CAPTURE);
                return;
              }
              setState({ phase: "done", request, envelope: read.envelope, source: read.source });
            } else {
              fail(undefined, ANSWER_UNREADABLE); // completed but unreadable: say so
            }
            return;
          }
          if (job.status === "failed" || job.status === "cancelled") {
            forgetJob(request);
            fail(
              undefined,
              job.errorCode ?? undefined,
              job.infeasibility,
              job.errorCode === "CHIP_NOT_HELD" ? jobId : undefined,
            );
            return;
          }
          if (job.status === "running" && waiting.runningSince === undefined) {
            waiting = { ...waiting, runningSince: Math.max(startedAt, Date.now()) };
            rememberJob(request, waiting);
          }
          answers += 1;
          // A poll that could not read the count does not take it back: `done` only goes up
          // within an attempt, and a new attempt starts again.
          const sameRun = job.status === "running" && job.attempt === attempt;
          progress = job.progress ?? (sameRun ? progress : undefined);
          attempt = job.attempt;
          setState({
            phase: "waiting",
            request,
            jobId,
            status: job.status,
            fallback,
            queuePosition: job.queuePosition,
            progress,
            workers: job.workers,
            answers,
          });
        }
        if (alive()) {
          forgetJob(request);
          fail(undefined, PATIENCE_EXHAUSTED);
        }
      })()
        .catch((error) => {
          if (alive()) {
            forgetJob(request);
            fail(error);
          }
        })
        .finally(() => {
          if (active.current === controller) active.current = null;
          if (generation.current === run) submitting.current = null;
          if (readAfterMissingJob && generation.current === run) readCached(request);
        });
    },
    [
      client,
      allowPublishedBaseline,
      expectedSnapshotId,
      readCached,
      requireMatchingSnapshot,
      setState,
    ],
  );

  const compute = useCallback(
    (request: AdviceRequest) => {
      if (submitting.current && sameAdviceRequest(submitting.current, request)) return;
      submitting.current = request;
      start(request, null);
    },
    [start],
  );

  const resume = useCallback(
    (request: AdviceRequest) => {
      const remembered = recallJob(request);
      if (!remembered) return false;
      const now = Date.now();
      if (
        now < (remembered.runningSince ?? remembered.startedAt) ||
        now >= waitDeadline(remembered, request.window)
      ) {
        forgetJob(request);
        return false;
      }
      start(request, remembered);
      return true;
    },
    [start],
  );

  return { state, compute, resume, readCached, reset };
}
